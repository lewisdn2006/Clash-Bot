"""
Automation Workers — QThread subclasses that own all automation logic.
=====================================================================
The GUI never calls Autoclash / Autoclash_BB directly.  It creates a worker,
connects to its signals, and starts it.  The worker emits signals that the GUI
connects via slots.

Workers
-------
* HomeVillageWorker      — single-account infinite/finite battle loop
* FillAccountsWorker     — multi-account fill-until-full loop
* BuilderBaseWorker      — single-account BB loop
* BBFillAccountsWorker   — multi-account BB fill loop
* ClanGamesWorker        — Clan Games challenge cycler (all accounts)
"""

from __future__ import annotations

import re
import os
import time
import tempfile
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import cv2
import numpy as np
import pyautogui
from PySide6.QtCore import QThread, Signal

# ---------------------------------------------------------------------------
# Automation imports (unchanged modules)
# ---------------------------------------------------------------------------
import sys

sys.path.insert(0, str(Path(__file__).parent))

from Autoclash import (
    CONFIG,
    APPROVED_ACCOUNTS,
    log,
    update_account_stats,
    ensure_approved_account,
    phase1_enter_battle,
    phase2_prepare,
    phase2_execute,
    phase3_wait_for_return,
    phase4_upgrade,
    upgrade_account,
    rush_upgrade_account,
    pop_gem_upgrades_disabled,
    LOOT_TRACKER,
    space_listener as home_space_listener,
)
import Autoclash
import Autoclash_BB
import vision as _vision
import clangamescycler
import clangamesmaster
import clanscouter
import capitalraider
import bot_reporter

# ---------------------------------------------------------------------------
# Vision overlay patch
# ---------------------------------------------------------------------------
# Workers (except ClanGamesWorker which manages its own overlay) set this
# callback to self.overlay_draw.emit so that every successful find_template
# call draws a detection rect on the overlay in real-time.

_overlay_callback = None   # callable(detections: list, title: str) | None


def _set_overlay_callback(fn):
    """Set (or clear with None) the active overlay draw callback."""
    global _overlay_callback
    _overlay_callback = fn


def _install_vision_patch():
    """Monkey-patch vision.find_template once so every match emits to the
    overlay when a worker has registered a callback."""
    import vision as _vis
    import cv2 as _cv2
    from pathlib import Path as _Path

    _orig = _vis.find_template

    def _patched(template_path, threshold=0.75, screenshot=None,
                 region=None, find_mode="best", bgr=False):
        coords, max_val = _orig(
            template_path=template_path,
            threshold=threshold,
            screenshot=screenshot,
            region=region,
            find_mode=find_mode,
            bgr=bgr,
        )
        cb = _overlay_callback
        if coords is not None and cb is not None:
            try:
                label = _Path(template_path).stem
                tpl = _cv2.imread(str(template_path), _cv2.IMREAD_GRAYSCALE)
                if tpl is not None:
                    th, tw = tpl.shape[:2]
                    cx, cy = coords
                    det = {
                        "shape": "rect",
                        "bbox": (cx - tw // 2, cy - th // 2,
                                 cx + tw // 2, cy + th // 2),
                        "label": label,
                        "score": max_val,
                    }
                    cb([det], f"Found: {label}")
            except Exception:
                pass
        return coords, max_val

    _vis.find_template = _patched


_install_vision_patch()

# ---------------------------------------------------------------------------
# Shared constants (previously lived inside AutoclashGUI class)
# ---------------------------------------------------------------------------
SETTINGS_MENU_COORD = (1852, 841)
ACCOUNT_SWITCH_MENU_COORD = (1245, 244)
ACCOUNT_SWITCH_BOX = (1321, 496, 1917, 1080)
FAILURE_RECOVERY_THRESHOLD = 100
HARD_RESET_CLOSE_COORD = (1859, 16)
HARD_RESET_RELAUNCH_COORD = (340, 160)
HARD_RESET_POST_LAUNCH_COORD = (1517, 148)

INGAME_TO_SWITCH_NAME: Dict[str, str] = {
    "lewis": "CarefreeZenLewis",
    "williamleeming": "HomelessLewis2",
    "steve": "BrokenSiennaa",
    "lewis8": "FreshLewis8",
    "lewis7": "CurlyLewis7",
    "lewis6": "WelcomedLewis6",
    "lewis5": "SincereLewis5",
    "lewis4": "IconLewis4",
    "lewis3": "TrustworthyLewis3",
    "djbillgates22": "DJBillGates22",
    "djbillgates23": "DJBillGates123",
    "djbillgates24": "DJBillGates24",
    "djbillgates25": "DJBillGates25",
    "djbillgates26": "DJBillGates26",
    "djbillgates27": "DJBillGates27",
    "djbillgates28": "DJBillGates28",
    "djbillgates29": "DJBillGates29",
}

# Maps in-game OCR name → account key for accounts where the two differ.
# Currently empty — all accounts have matching OCR name and internal key.
OCR_NAME_TO_KEY: Dict[str, str] = {}


# ═══════════════════════════════════════════════════════════════════════════
# Helpers shared by all workers
# ═══════════════════════════════════════════════════════════════════════════

def normalize_account_name(name: str) -> str:
    return (name or "").strip().lower()


def _worker_pauseable_sleep(seconds: float) -> None:
    """Sleep for `seconds` honouring pause/stop on the default session every 0.1 s."""
    sess = Autoclash._default_session
    iters = max(1, int(seconds * 10))
    for _ in range(iters):
        if sess.stop_requested:
            break
        if sess.pause_requested:
            Autoclash.check_pause(sess)
        time.sleep(0.1)


def _normalize_text_for_ocr(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "", value or "").strip().lower()


def _normalize_ocr_confidence(raw_conf: float) -> float:
    if raw_conf <= 1.0:
        return max(0.0, min(1.0, raw_conf))
    return max(0.0, min(1.0, raw_conf / 100.0))


def _preprocess_for_ocr(pil_image) -> np.ndarray:
    image_np = np.array(pil_image)
    gray = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY)
    upscaled = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    blur = cv2.GaussianBlur(upscaled, (3, 3), 0)
    _thr, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return thresh


def _ocr_tsv_records_in_region(region: Tuple[int, int, int, int]) -> list:
    x1, y1, x2, y2 = region
    width, height = x2 - x1, y2 - y1
    screenshot = _vision.safe_screenshot(region=(x1, y1, width, height))
    processed = _preprocess_for_ocr(screenshot)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        image_path = tmp.name
        cv2.imwrite(image_path, processed)

    records: list = []
    try:
        result = subprocess.run(
            [Autoclash.TESSERACT_PATH, image_path, "stdout", "tsv"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return []

        lines = result.stdout.splitlines()
        if not lines:
            return []

        header = lines[0].split("\t")
        index_map = {name: idx for idx, name in enumerate(header)}
        required = ["left", "top", "width", "height", "conf", "text"]
        if any(name not in index_map for name in required):
            return []

        for line in lines[1:]:
            cols = line.split("\t")
            if len(cols) < len(header):
                continue

            text = cols[index_map["text"]].strip()
            if not text:
                continue
            text_norm = _normalize_text_for_ocr(text)
            if not text_norm:
                continue

            try:
                conf = float(cols[index_map["conf"]])
            except Exception:
                conf = -1.0
            if conf < 0:
                continue

            left = int(cols[index_map["left"]])
            top = int(cols[index_map["top"]])
            rect_w = int(cols[index_map["width"]])
            rect_h = int(cols[index_map["height"]])

            abs_x1 = x1 + left // 2
            abs_y1 = y1 + top // 2
            abs_x2 = abs_x1 + max(1, rect_w // 2)
            abs_y2 = abs_y1 + max(1, rect_h // 2)
            center_x = (abs_x1 + abs_x2) // 2
            center_y = (abs_y1 + abs_y2) // 2

            records.append(
                {
                    "text": text,
                    "text_norm": text_norm,
                    "conf": conf,
                    "bbox": (abs_x1, abs_y1, abs_x2, abs_y2),
                    "center": (center_x, center_y),
                }
            )
    except Exception:
        return []
    finally:
        try:
            os.remove(image_path)
        except Exception:
            pass

    return records


# ═══════════════════════════════════════════════════════════════════════════
# Account-switching helpers (shared by fill workers)
# ═══════════════════════════════════════════════════════════════════════════

def _match_visible_switch_accounts(candidates: Dict[str, str]) -> dict:
    visible: dict = {}
    ocr_rows = _ocr_tsv_records_in_region(ACCOUNT_SWITCH_BOX)
    log(f"SwitchOCR: {len(ocr_rows)} rows in switch box — {[r['text'] for r in ocr_rows]}")

    for ingame_name, switch_name in candidates.items():
        target_norm = _normalize_text_for_ocr(switch_name)
        best_row = None
        best_score = -1.0

        for row in ocr_rows:
            row_norm = row["text_norm"]
            if len(row_norm) < 4:
                continue  # Skip short fragments — single chars/junk always substring-match account names
            # When a fragment is a substring of the target, require it to cover ≥80% of the
            # target's length — otherwise short shared substrings (e.g. "illgates" matching
            # every djbillgatesXX account) produce false positives.
            fragment_match = (row_norm in target_norm and
                              len(row_norm) >= len(target_norm) * 0.8)
            if target_norm in row_norm or fragment_match:
                conf = _normalize_ocr_confidence(float(row["conf"]))
                log(f"SwitchOCR: '{row['text']}' matched '{switch_name}' conf={conf:.2f}")
                if conf < 0.85:
                    log(f"SwitchOCR: rejected — conf {conf:.2f} < 0.85")
                    continue
                if conf > best_score:
                    best_row = row
                    best_score = conf

        if best_row is not None:
            log(f"SwitchOCR: ACCEPTED '{ingame_name}' — OCR='{best_row['text']}' conf={best_score:.2f} center={best_row['center']}")
            visible[ingame_name] = {
                "switch_name": switch_name,
                "center": best_row["center"],
                "bbox": best_row["bbox"],
                "ocr_text": best_row["text"],
                "ocr_conf": best_score,
            }
        else:
            log(f"SwitchOCR: no match accepted for '{switch_name}' (target_norm='{target_norm}')")

    return visible


def _open_account_switch_menu():
    Autoclash.click_with_jitter(*SETTINGS_MENU_COORD)
    Autoclash.random_delay()
    _worker_pauseable_sleep(1.0)
    Autoclash.click_with_jitter(*ACCOUNT_SWITCH_MENU_COORD)
    Autoclash.random_delay()
    _worker_pauseable_sleep(1.0)


def _scroll_switch_box_once(direction: str = "down"):
    x1, y1, x2, y2 = ACCOUNT_SWITCH_BOX
    center_x = (x1 + x2) // 2
    center_y = (y1 + y2) // 2
    pyautogui.moveTo(center_x, center_y, duration=0.1)
    delta = abs(int(Autoclash.WHEEL_DELTA))
    try:
        Autoclash._send_wheel(-delta if direction == "down" else delta)
    except Exception:
        pyautogui.scroll(-delta if direction == "down" else delta)
    _worker_pauseable_sleep(0.5)


def _click_account_load_okay_if_present() -> bool:
    load_ok_template = "account_load_okay.png"
    for attempt in range(1, 6):
        coords = Autoclash.find_template(load_ok_template)
        if coords:
            Autoclash.click_with_jitter(*coords)
            Autoclash.random_delay()
            return True
        if attempt < 5:
            _worker_pauseable_sleep(1.0)
    return False


def _click_confirm_if_present() -> bool:
    """Check for confirm.png and click it if found (e.g. post-login or post-restart dialogs)."""
    coords = Autoclash.find_template("confirm.png")
    if coords:
        Autoclash.click_with_jitter(*coords)
        Autoclash.random_delay()
        return True
    return False


def _ensure_approved_account_with_return_home(max_attempts: int = 100, stop_fn=None) -> Optional[str]:
    for attempt in range(1, max_attempts + 1):
        if stop_fn is not None and stop_fn():
            return None

        name = Autoclash.read_account_name()
        name_norm = normalize_account_name(name)

        matched = Autoclash._match_approved_account(name_norm)
        if matched:
            Autoclash._default_session.current_account_name = matched
            return matched

        if name_norm == "fender":
            for _retry in range(20):
                if stop_fn is not None and stop_fn():
                    return None
                home_coords = Autoclash.find_template("return_home.png")
                if home_coords:
                    Autoclash.click_with_jitter(*home_coords)
                    Autoclash.random_delay()
                    _worker_pauseable_sleep(1.0)
                    break
                _worker_pauseable_sleep(1.0)
            continue

        if attempt < max_attempts:
            Autoclash.scroll_random(Autoclash.WHEEL_DELTA * 3)
            _worker_pauseable_sleep(0.5)

    return None


def _switch_to_target_fill_account(candidate_accounts: List[str]) -> Optional[str]:
    if not candidate_accounts:
        return None

    candidate_map = {
        account: INGAME_TO_SWITCH_NAME.get(account, account)
        for account in candidate_accounts
    }
    log(f"SwitchAcct: looking for {candidate_map}")

    _open_account_switch_menu()
    log("SwitchAcct: account switch menu opened")

    def find_visible_with_scroll(scroll_direction: str = "down"):
        max_scroll_attempts = 50
        for scan_idx in range(max_scroll_attempts + 1):
            if Autoclash._default_session.pause_requested:
                Autoclash.check_pause(Autoclash._default_session)
            if Autoclash._default_session.stop_requested:
                return {}
            log(f"SwitchAcct: scan {scan_idx}/{max_scroll_attempts} direction={scroll_direction}")
            visible = _match_visible_switch_accounts(candidate_map)
            if visible:
                log(f"SwitchAcct: found {list(visible.keys())} at scan {scan_idx}")
                cb = _overlay_callback
                if cb is not None:
                    dets = [
                        {"bbox": d["bbox"], "label": f"{name} ({d['ocr_conf']:.0%})", "score": d["ocr_conf"]}
                        for name, d in visible.items()
                    ]
                    cb(dets, "Switch — account found")
                return visible
            if scan_idx < max_scroll_attempts:
                _scroll_switch_box_once(scroll_direction)
        log(f"SwitchAcct: exhausted {max_scroll_attempts} scrolls ({scroll_direction}), not found")
        return {}

    visible_accounts = find_visible_with_scroll("down")
    if not visible_accounts:
        log("SwitchAcct: not found scrolling down — resetting to top and retrying")
        for _ in range(50):
            _scroll_switch_box_once("up")
        visible_accounts = find_visible_with_scroll("down")
        if not visible_accounts:
            log(f"SwitchAcct: FAILED — could not find any of {list(candidate_map.keys())} in switch menu")
            return None

    selected_account, selected_data = min(
        visible_accounts.items(), key=lambda item: item[1]["center"][1]
    )
    log(f"SwitchAcct: clicking '{selected_account}' at {selected_data['center']}")

    Autoclash.click_with_jitter(*selected_data["center"])
    Autoclash.random_delay()
    _worker_pauseable_sleep(3.0)
    _click_account_load_okay_if_present()
    _click_confirm_if_present()

    confirmed = _ensure_approved_account_with_return_home(
        max_attempts=120,
        stop_fn=lambda: Autoclash._default_session.stop_requested,
    )
    log(f"SwitchAcct: confirmed account = '{confirmed}' (wanted one of {candidate_accounts})")
    if confirmed:
        if confirmed in candidate_accounts:
            return confirmed
        # Check if the OCR name maps to a different account key (populate OCR_NAME_TO_KEY if needed)
        mapped_key = OCR_NAME_TO_KEY.get(confirmed)
        if mapped_key and mapped_key in candidate_accounts:
            log(f"SwitchAcct: OCR name '{confirmed}' mapped to account key '{mapped_key}'")
            return mapped_key
    return None


# ═══════════════════════════════════════════════════════════════════════════
# Recovery / failure-watchdog mixin
# ═══════════════════════════════════════════════════════════════════════════

class _RecoveryMixin:
    """Adds failure-watchdog / error-recovery to any worker."""

    _last_failure_key: Optional[str] = None
    _same_failure_count: int = 0

    def _reset_failure_watchdog(self):
        self._last_failure_key = None
        self._same_failure_count = 0

    def _register_failure(self, failure_key: str) -> int:
        key = (failure_key or "unknown").strip().lower()
        if key == self._last_failure_key:
            self._same_failure_count += 1
        else:
            self._last_failure_key = key
            self._same_failure_count = 1
        return self._same_failure_count

    def _scan_and_click_known_error_templates(self) -> bool:
        try:
            if Autoclash.check_for_error_button():
                return True
        except Exception as exc:
            log(f"Worker: Error while calling check_for_error_button: {exc}")

        templates_to_try = [
            ("return_home.png", "return_home"),
            ("account_load_okay.png", "account_load_okay"),
            (CONFIG.get("try_again_button", "try_again_button.png"), "try_again_button"),
            (CONFIG.get("reload_game_button", "reload_game.png"), "reload_game"),
        ]
        for template_name, label in templates_to_try:
            if not template_name:
                continue
            coords = Autoclash.find_template(template_name)
            if coords:
                self.status_update.emit("Recovery", f"Detected {label}; clicking to recover...")
                Autoclash.click_with_jitter(*coords)
                time.sleep(2)
                return True
        return False

    def _perform_hard_game_restart(self):
        self.status_update.emit("Recovery", "No known error popup found. Performing hard game restart...")
        pyautogui.hotkey('alt', 'f4')  # Close game window
        # Backup (old click-to-close): pyautogui.click(*HARD_RESET_CLOSE_COORD)
        time.sleep(5)
        pyautogui.doubleClick(*HARD_RESET_RELAUNCH_COORD, interval=0.2)
        # Backup (old post-launch click): pyautogui.click(*HARD_RESET_POST_LAUNCH_COORD)
        time.sleep(20)
        _click_confirm_if_present()

    def _handle_repeated_failure(self, failure_key: str, action_label: str = "Recovery") -> bool:
        count = self._register_failure(failure_key)
        if count < FAILURE_RECOVERY_THRESHOLD:
            return False

        self.status_update.emit(action_label, f"'{failure_key}' failed {count} times. Running full error recovery...")
        self._reset_failure_watchdog()

        if self._scan_and_click_known_error_templates():
            self.status_update.emit(action_label, "Recovered via detected error popup. Retrying process...")
            time.sleep(2)
            return True

        self._perform_hard_game_restart()
        self.status_update.emit(action_label, "Game restarted. Retrying current process...")
        return True


# ═══════════════════════════════════════════════════════════════════════════
# Context-switch helpers (shared)
# ═══════════════════════════════════════════════════════════════════════════

def _builder_attack_button_visible() -> bool:
    try:
        cv_img = Autoclash_BB.screenshot_cv()
        coords = Autoclash_BB.find_template(
            cv_img,
            Autoclash_BB.CONFIG["BBattack"],
            min(Autoclash_BB.CONFIG.get("TEMPLATE_THRESH_DEFAULT", 0.85), 0.84),
            log_not_found=False,
        )
        return coords is not None
    except Exception:
        return False


class _ContextMixin:
    """Provides helpers for ensuring correct village context."""

    def _ensure_home_village_context(self, max_attempts: int = 60) -> bool:
        if not _builder_attack_button_visible():
            return True

        self.status_update.emit("Context", "Builder Base detected. Returning to Home Village...")

        drag_pairs = [((1288, 513), (289, 624)), ((289, 624), (1288, 513))]
        drag_index = 0

        for attempt in range(1, max_attempts + 1):
            if self._stop_requested:
                return False

            boat_coords = Autoclash.find_template("BB_boat.png")
            if boat_coords:
                self.status_update.emit("Context", f"Found BB boat at {boat_coords}, clicking...")
                Autoclash.click_with_jitter(*boat_coords)
                Autoclash.random_delay()
                time.sleep(1.5)
                return True

            self.status_update.emit("Context", f"Searching BB boat ({attempt}/{max_attempts})")

            start, end = drag_pairs[drag_index]
            drag_index = 1 - drag_index

            pyautogui.moveTo(*start, duration=0.1)
            pyautogui.dragTo(*end, duration=0.45, button="left")
            time.sleep(0.25)

            try:
                Autoclash.scroll_down_api(Autoclash.WHEEL_DELTA * 3)
            except Exception:
                pyautogui.scroll(-abs(int(Autoclash.WHEEL_DELTA * 3)))
            time.sleep(0.3)

        self.status_update.emit("Context", "Failed to locate BB boat during recovery loop")
        return False

    def _prepare_builder_base_after_switch(self, max_attempts: int = 5) -> bool:
        for attempt in range(1, max_attempts + 1):
            self.status_update.emit("BB Prep", f"Preparing Builder Base view (attempt {attempt}/{max_attempts})")

            _click_account_load_okay_if_present()
            return_home_coords = Autoclash.find_template("return_home.png")
            if return_home_coords:
                Autoclash.click_with_jitter(*return_home_coords)
                Autoclash.random_delay()
                time.sleep(1.0)

            for _ in range(2):
                try:
                    Autoclash.scroll_down_api(Autoclash.WHEEL_DELTA * 3)
                except Exception:
                    pyautogui.scroll(-abs(int(Autoclash.WHEEL_DELTA * 3)))
                time.sleep(0.25)

            for _ in range(2):
                pyautogui.moveTo(777, 752, duration=0.1)
                pyautogui.dragTo(1011, 291, duration=0.45, button="left")
                time.sleep(0.25)

            Autoclash.click_with_jitter(511, 752)
            Autoclash.random_delay()
            time.sleep(1.5)

            if _builder_attack_button_visible():
                self.status_update.emit("BB Prep", "Builder attack button found")
                return True

            self.status_update.emit("BB Prep", "Builder attack button not found, retrying...")
            time.sleep(1.0)

        return False


# ═══════════════════════════════════════════════════════════════════════════
# 1) HomeVillageWorker
# ═══════════════════════════════════════════════════════════════════════════

class HomeVillageWorker(QThread, _RecoveryMixin, _ContextMixin):
    """Runs continuous Home Village battles, emitting progress via signals."""

    status_update = Signal(str, str)          # (phase, message)
    battle_completed = Signal(str, dict, float, int)  # (account, snapshot, duration, walls)
    account_detected = Signal(str)            # normalised account name
    gem_upgrades_disabled = Signal(str)       # account name for which gem upgrades were disabled
    overlay_draw = Signal(list, str)          # (detections, title)
    overlay_clear = Signal()
    error_occurred = Signal(str)
    finished = Signal()

    def __init__(self, account_settings_getter, apply_settings_fn, parent=None):
        super().__init__(parent)
        self._stop_requested = False
        self._get_account_settings = account_settings_getter
        self._apply_settings = apply_settings_fn

    def stop(self):
        self._stop_requested = True
        Autoclash._default_session.stop_requested = True

    # noinspection PyUnresolvedReferences
    def run(self):  # noqa: C901
        try:
            bot_reporter.start()
            self.status_update.emit("Initializing", "Starting automation...")
            bot_reporter.update_phase("Initializing", "Starting automation...")
            bot_reporter.log("Home Village automation started")
            self.overlay_draw.emit([], "Home Village — Initialising")
            _set_overlay_callback(self.overlay_draw.emit)
            home_space_listener.start()

            num_runs = CONFIG.get("num_runs")
            infinite_mode = num_runs is None or num_runs <= 0
            run_count = 0
            total_upgrades = 0

            while not self._stop_requested:
                if Autoclash._default_session.pause_requested:
                    Autoclash.check_pause(Autoclash._default_session)
                self.overlay_draw.emit([], "Home Village — Checking village context")
                if not self._ensure_home_village_context(max_attempts=60):
                    if self._stop_requested:
                        break
                    self._handle_repeated_failure("home.context.recovery", action_label="Context")
                    self.status_update.emit("Context", "Could not return to Home Village yet, retrying...")
                    time.sleep(2)
                    continue

                self.overlay_draw.emit([], "Home Village — Detecting account")
                self.status_update.emit("Account", "Detecting active account...")
                bot_reporter.update_phase("Account", "Detecting active account...")
                if not ensure_approved_account():
                    if self._stop_requested:
                        break
                    self._handle_repeated_failure("home.account.detect", action_label="Account")
                    self.status_update.emit("Account", "Failed to detect approved account")
                    bot_reporter.update_phase("Account", "Failed to detect approved account")
                    time.sleep(2)
                    continue

                detected = normalize_account_name(Autoclash._default_session.current_account_name or "")
                if not detected:
                    self._handle_repeated_failure("home.account.empty", action_label="Account")
                    self.status_update.emit("Account", "Detected account name is empty")
                    bot_reporter.update_phase("Account", "Detected account name is empty")
                    time.sleep(2)
                    continue

                self.account_detected.emit(detected)
                bot_reporter.update_account(detected)
                settings = self._get_account_settings(detected)
                self._apply_settings(settings)
                self.status_update.emit("Account", f"Using '{detected}' settings")
                bot_reporter.update_phase("Account", f"Using '{detected}' settings")
                bot_reporter.log(f"Account active: {detected}")

                run_count += 1
                if not infinite_mode and run_count > num_runs:
                    break

                self.status_update.emit(f"Battle {run_count}", f"Starting battle {run_count}...")
                bot_reporter.update_phase(f"Battle {run_count}", f"Starting battle {run_count}...")

                try:
                    battle_start = time.time()
                    Autoclash._default_session.walls_upgraded_this_battle = 0

                    # Phase 1
                    self.overlay_draw.emit([], f"Home Village — Battle {run_count}: Entering battle")
                    self.status_update.emit("Phase 1", "Entering battle...")
                    bot_reporter.update_phase("Phase 1", "Entering battle...")
                    if not phase1_enter_battle(skip_account_check=False):
                        if self._stop_requested:
                            break
                        self._handle_repeated_failure("home.phase1.enter", action_label="Phase 1")
                        log("ERROR: Failed to enter battle")
                        time.sleep(3)
                        continue

                    confirmed = normalize_account_name(Autoclash._default_session.current_account_name or "")
                    if confirmed:
                        self.account_detected.emit(confirmed)
                        bot_reporter.update_account(confirmed)
                        confirmed_settings = self._get_account_settings(confirmed)
                        self._apply_settings(confirmed_settings)
                        self.status_update.emit("Account", f"Using '{confirmed}' settings")
                        bot_reporter.update_phase("Account", f"Using '{confirmed}' settings")

                    # Phase 2A
                    self.overlay_draw.emit([], f"Home Village — Battle {run_count}: Preparing")
                    self.status_update.emit("Phase 2A", "Preparing battle...")
                    bot_reporter.update_phase("Phase 2A", "Preparing battle...")
                    if not phase2_prepare():
                        if self._stop_requested:
                            break
                        self._handle_repeated_failure("home.phase2a.prepare", action_label="Phase 2A")
                        time.sleep(3)
                        continue

                    # Phase 2B
                    self.overlay_draw.emit([], f"Home Village — Battle {run_count}: Deploying troops")
                    self.status_update.emit("Phase 2B", "Deploying troops...")
                    bot_reporter.update_phase("Phase 2B", "Deploying troops...")
                    if not phase2_execute():
                        if self._stop_requested:
                            break
                        self._handle_repeated_failure("home.phase2b.execute", action_label="Phase 2B")
                        time.sleep(3)
                        continue

                    # Phase 3
                    self.overlay_draw.emit([], f"Home Village — Battle {run_count}: Waiting for return")
                    self.status_update.emit("Phase 3", "Waiting for battle to end...")
                    bot_reporter.update_phase("Phase 3", "Waiting for battle to end...")
                    if not phase3_wait_for_return():
                        if self._stop_requested:
                            break
                        self._handle_repeated_failure("home.phase3.return", action_label="Phase 3")
                        time.sleep(3)
                        continue

                    # Phase 4
                    self.status_update.emit("Loading", "Waiting for Phase 4 to load...")
                    bot_reporter.update_phase("Loading", "Waiting for Phase 4 to load...")
                    time.sleep(5)

                    if CONFIG.get("auto_upgrade_walls", True):
                        self.overlay_draw.emit([], f"Home Village — Battle {run_count}: Upgrading walls")
                        self.status_update.emit("Phase 4", "Upgrading walls...")
                        bot_reporter.update_phase("Phase 4", "Upgrading walls...")
                        phase4_upgrade()
                        _walls = Autoclash._default_session.walls_upgraded_this_battle
                        if _walls:
                            total_upgrades += _walls
                            bot_reporter.report_upgrade(
                                Autoclash._default_session.current_account_name or detected,
                                "walls", total_upgrades,
                            )
                    else:
                        self.status_update.emit("Phase 4", "Phase 4 skipped (auto upgrade disabled)")
                        bot_reporter.update_phase("Phase 4", "Phase 4 skipped (auto upgrade disabled)")

                    if CONFIG.get("auto_upgrade_storages", True):
                        self.overlay_draw.emit([], f"Home Village — Battle {run_count}: Upgrading account")
                        self.status_update.emit("Phase 5", "Upgrading account...")
                        bot_reporter.update_phase("Phase 5", "Upgrading account...")
                        upgrade_account()
                        total_upgrades += 1
                        bot_reporter.report_upgrade(
                            Autoclash._default_session.current_account_name or detected,
                            "account upgrade", total_upgrades,
                        )
                    else:
                        self.status_update.emit("Phase 5", "Phase 5 skipped (auto upgrade storages disabled)")
                        bot_reporter.update_phase("Phase 5", "Phase 5 skipped (auto upgrade storages disabled)")

                    disabled_acct = pop_gem_upgrades_disabled()
                    if disabled_acct:
                        self.gem_upgrades_disabled.emit(disabled_acct)

                    battle_duration = time.time() - battle_start
                    snapshot = getattr(LOOT_TRACKER, "last_snapshot", None)
                    account_name = Autoclash._default_session.current_account_name
                    walls = Autoclash._default_session.walls_upgraded_this_battle

                    if account_name and snapshot:
                        try:
                            update_account_stats(account_name, snapshot, battle_duration, walls)
                            self.battle_completed.emit(account_name, snapshot, battle_duration, walls)
                            log(f"[OK] Stats saved for '{account_name}' (+{walls} walls)")
                            _gold = snapshot.get("gold", 0) if isinstance(snapshot, dict) else 0
                            _elixir = snapshot.get("elixir", 0) if isinstance(snapshot, dict) else 0
                            _dark = snapshot.get("dark_elixir", snapshot.get("dark", 0)) if isinstance(snapshot, dict) else 0
                            bot_reporter.report_battle_complete(account_name, _gold, _elixir, _dark, run_count)
                        except Exception as e:
                            log(f"[ERROR] saving stats: {e}")
                    else:
                        if not account_name:
                            log("[WARN] Stats update skipped: No account name")
                        if not snapshot:
                            log("[WARN] Stats update skipped: No loot snapshot")

                    self._reset_failure_watchdog()
                    self.overlay_draw.emit([], f"Home Village — Battle {run_count} complete")
                    self.status_update.emit("Idle", f"Battle {run_count} completed!")
                    bot_reporter.update_phase("Idle", f"Battle {run_count} completed!")
                    time.sleep(2.0)

                except Exception as e:
                    log(f"ERROR in battle {run_count}: {e}")
                    self.status_update.emit("Error", f"Error in battle {run_count}: {e}")
                    bot_reporter.report_error(f"Error in battle {run_count}: {e}")
                    if self._stop_requested:
                        break
                    self._handle_repeated_failure("home.battle.exception", action_label="Error")
                    time.sleep(2.0)

            home_space_listener.stop()

            if self._stop_requested:
                self.status_update.emit("Stopped", "Automation stopped by user")
                bot_reporter.update_phase("Stopped", "Automation stopped by user")
            else:
                self.status_update.emit("Complete", "Automation completed!")
                bot_reporter.update_phase("Complete", "Automation completed!")

        except Exception as e:
            log(f"FATAL ERROR in home automation thread: {e}")
            self.error_occurred.emit(str(e))
            bot_reporter.report_error(f"FATAL: {e}")
        finally:
            _set_overlay_callback(None)
            self.overlay_clear.emit()
            bot_reporter.stop()
            self.finished.emit()


# ═══════════════════════════════════════════════════════════════════════════
# 2) FillAccountsWorker
# ═══════════════════════════════════════════════════════════════════════════

class FillAccountsWorker(QThread, _RecoveryMixin, _ContextMixin):
    """Iterates over selected accounts, fills each until storages are full."""

    status_update = Signal(str, str)
    battle_completed = Signal(str, dict, float, int)
    account_detected = Signal(str)
    fill_progress = Signal(int, int)              # (completed_count, total)
    overlay_draw = Signal(list, str)              # (detections, title)
    overlay_clear = Signal()
    error_occurred = Signal(str)
    finished = Signal()

    def __init__(
        self,
        selected_accounts: List[str],
        account_settings_getter,
        apply_settings_fn,
        parent=None,
    ):
        super().__init__(parent)
        self._stop_requested = False
        self.selected_accounts = list(selected_accounts)
        self.completed_accounts: Set[str] = set()
        self._get_account_settings = account_settings_getter
        self._apply_settings = apply_settings_fn

    def stop(self):
        self._stop_requested = True
        Autoclash._default_session.stop_requested = True

    @staticmethod
    def _are_storages_full() -> bool:
        return bool(Autoclash.check_gold_full()) and bool(Autoclash.check_elixir_full())

    def _run_single_fill_battle(self, battle_index: int, target_account: str) -> str:
        try:
            battle_start = time.time()
            Autoclash._default_session.walls_upgraded_this_battle = 0

            self.overlay_draw.emit([], f"Fill Accounts — Battle {battle_index}: Checking context")
            if not self._ensure_home_village_context(max_attempts=60):
                if self._stop_requested:
                    return "stop"
                return "failed"

            self.overlay_draw.emit([], f"Fill Accounts — Battle {battle_index}: Entering battle")
            self.status_update.emit("Phase 1", "Entering battle...")
            if not phase1_enter_battle(skip_account_check=False):
                if self._stop_requested:
                    return "stop"
                time.sleep(3)
                return "failed"

            confirmed = normalize_account_name(Autoclash._default_session.current_account_name or "")
            if not confirmed or confirmed != target_account:
                self.status_update.emit("Account", f"Account changed to '{confirmed}' while targeting '{target_account}'")
                return "wrong-account"

            self.overlay_draw.emit([], f"Fill Accounts — Battle {battle_index}: Preparing")
            self.status_update.emit("Phase 2A", "Preparing battle...")
            if not phase2_prepare():
                if self._stop_requested:
                    return "stop"
                time.sleep(3)
                return "failed"

            self.overlay_draw.emit([], f"Fill Accounts — Battle {battle_index}: Deploying troops")
            self.status_update.emit("Phase 2B", "Deploying troops...")
            if not phase2_execute():
                if self._stop_requested:
                    return "stop"
                time.sleep(3)
                return "failed"

            self.overlay_draw.emit([], f"Fill Accounts — Battle {battle_index}: Waiting for return")
            self.status_update.emit("Phase 3", "Waiting for battle to end...")
            if not phase3_wait_for_return():
                if self._stop_requested:
                    return "stop"
                time.sleep(3)
                return "failed"

            battle_duration = time.time() - battle_start
            snapshot = getattr(LOOT_TRACKER, "last_snapshot", None)
            account_name = Autoclash._default_session.current_account_name

            if account_name and snapshot:
                update_account_stats(account_name, snapshot, battle_duration, walls_upgraded=0)
                self.battle_completed.emit(account_name, snapshot, battle_duration, 0)

            self.overlay_draw.emit([], f"Fill Accounts — Battle {battle_index} complete")
            self.status_update.emit("Idle", f"Battle {battle_index} completed on '{target_account}'")
            time.sleep(2.0)
            return "ok"
        except Exception as exc:
            self.status_update.emit("Error", f"Error in fill battle {battle_index}: {exc}")
            return "failed"

    # noinspection PyUnresolvedReferences
    def run(self):  # noqa: C901
        try:
            self.status_update.emit("Initializing", "Starting Fill Accounts automation...")
            self.overlay_draw.emit([], "Fill Accounts — Initialising")
            _set_overlay_callback(self.overlay_draw.emit)
            home_space_listener.start()

            battle_count = 0

            while not self._stop_requested:
                remaining = [a for a in self.selected_accounts if a not in self.completed_accounts]
                if not remaining:
                    break

                self.fill_progress.emit(len(self.completed_accounts), len(self.selected_accounts))

                self.overlay_draw.emit([], "Fill Accounts — Switching account")
                target = _switch_to_target_fill_account(remaining)
                if not target:
                    if self._stop_requested:
                        break
                    self._handle_repeated_failure("fill.switch.account", action_label="Switch")
                    time.sleep(3)
                    continue

                self.account_detected.emit(target)
                Autoclash._default_session.current_account_name = target

                target_settings = self._get_account_settings(target).copy()
                target_settings["auto_upgrade_walls"] = False
                self._apply_settings(target_settings)
                self.status_update.emit("Account", f"Using '{target}' settings (auto-upgrade forced OFF)")

                if not self._ensure_home_village_context(max_attempts=60):
                    if self._stop_requested:
                        break
                    self._handle_repeated_failure("fill.context.recovery", action_label="Context")
                    time.sleep(2)
                    continue

                if self._are_storages_full():
                    self.completed_accounts.add(target)
                    self.status_update.emit("Storage", f"'{target}' already full. Marked complete.")
                    continue

                while not self._stop_requested:
                    if self._are_storages_full():
                        self.completed_accounts.add(target)
                        self.status_update.emit("Storage", f"'{target}' is now full.")
                        break

                    battle_count += 1
                    self.status_update.emit("Battle", f"Starting fill battle {battle_count} on '{target}'...")
                    result = self._run_single_fill_battle(battle_count, target)

                    if result == "stop":
                        break
                    if result == "ok":
                        self._reset_failure_watchdog()
                        continue
                    if result == "failed":
                        self._handle_repeated_failure("fill.battle.failed", action_label="Battle")
                    if result == "wrong-account":
                        self._handle_repeated_failure("fill.battle.wrong_account", action_label="Account")
                        break

            home_space_listener.stop()

            if self._stop_requested:
                self.status_update.emit("Stopped", "Fill Accounts stopped by user")
            else:
                self.status_update.emit("Complete", "Fill Accounts completed: all selected accounts are full")

        except Exception as exc:
            log(f"FATAL ERROR in fill automation thread: {exc}")
            self.error_occurred.emit(str(exc))
        finally:
            _set_overlay_callback(None)
            self.overlay_clear.emit()
            self.finished.emit()


# ═══════════════════════════════════════════════════════════════════════════
# 3) CycleAccountsWorker
# ═══════════════════════════════════════════════════════════════════════════

class CycleAccountsWorker(QThread, _RecoveryMixin, _ContextMixin):
    """Cycles through selected accounts indefinitely, doing N attacks on each."""

    status_update = Signal(str, str)
    battle_completed = Signal(str, dict, float, int)
    account_detected = Signal(str)
    overlay_draw = Signal(list, str)          # (detections, title)
    overlay_clear = Signal()
    error_occurred = Signal(str)
    finished = Signal()

    def __init__(
        self,
        selected_accounts: List[str],
        attacks_per_account: int,
        account_settings_getter,
        apply_settings_fn,
        parent=None,
    ):
        super().__init__(parent)
        self._stop_requested = False
        self.selected_accounts = list(selected_accounts)
        self.attacks_per_account = attacks_per_account
        self._get_account_settings = account_settings_getter
        self._apply_settings = apply_settings_fn

    def stop(self):
        self._stop_requested = True
        Autoclash._default_session.stop_requested = True

    def _run_single_cycle_battle(self, battle_index: int, target_account: str,
                                 account_attack_counts: dict, account_upgrade_counts: dict) -> str:
        try:
            battle_start = time.time()
            Autoclash._default_session.walls_upgraded_this_battle = 0

            self.overlay_draw.emit([], f"Cycle Accounts — Battle {battle_index}: Checking context")
            if not self._ensure_home_village_context(max_attempts=60):
                if self._stop_requested:
                    return "stop"
                return "failed"

            self.overlay_draw.emit([], f"Cycle Accounts — Battle {battle_index}: Entering battle")
            self.status_update.emit("Phase 1", "Entering battle...")
            bot_reporter.update_phase("Phase 1", "Entering battle...")
            if not phase1_enter_battle(skip_account_check=False):
                if self._stop_requested:
                    return "stop"
                time.sleep(3)
                return "failed"

            confirmed = normalize_account_name(Autoclash._default_session.current_account_name or "")
            if not confirmed or confirmed != target_account:
                self.status_update.emit("Account", f"Account changed to '{confirmed}' while targeting '{target_account}'")
                return "wrong-account"

            if Autoclash._default_session.pause_requested:
                Autoclash.check_pause(Autoclash._default_session)
            if self._stop_requested:
                return "stop"

            self.overlay_draw.emit([], f"Cycle Accounts — Battle {battle_index}: Preparing")
            self.status_update.emit("Phase 2A", "Preparing battle...")
            bot_reporter.update_phase("Phase 2A", "Preparing battle...")
            if not phase2_prepare():
                if self._stop_requested:
                    return "stop"
                time.sleep(3)
                return "failed"

            if Autoclash._default_session.pause_requested:
                Autoclash.check_pause(Autoclash._default_session)
            if self._stop_requested:
                return "stop"

            self.overlay_draw.emit([], f"Cycle Accounts — Battle {battle_index}: Deploying troops")
            self.status_update.emit("Phase 2B", "Deploying troops...")
            bot_reporter.update_phase("Phase 2B", "Deploying troops...")
            if not phase2_execute():
                if self._stop_requested:
                    return "stop"
                time.sleep(3)
                return "failed"

            if Autoclash._default_session.pause_requested:
                Autoclash.check_pause(Autoclash._default_session)
            if self._stop_requested:
                return "stop"

            self.overlay_draw.emit([], f"Cycle Accounts — Battle {battle_index}: Waiting for return")
            self.status_update.emit("Phase 3", "Waiting for battle to end...")
            bot_reporter.update_phase("Phase 3", "Waiting for battle to end...")
            if not phase3_wait_for_return():
                if self._stop_requested:
                    return "stop"
                time.sleep(3)
                return "failed"

            if Autoclash._default_session.pause_requested:
                Autoclash.check_pause(Autoclash._default_session)
            if self._stop_requested:
                return "stop"

            # Phase 4 — wall upgrades (respects each account's own setting)
            self.status_update.emit("Loading", "Waiting for Phase 4 to load...")
            bot_reporter.update_phase("Loading", "Waiting for Phase 4 to load...")
            time.sleep(5)
            if CONFIG.get("auto_upgrade_walls", True):
                self.overlay_draw.emit([], f"Cycle Accounts — Battle {battle_index}: Upgrading walls")
                self.status_update.emit("Phase 4", "Upgrading walls...")
                bot_reporter.update_phase("Phase 4", "Upgrading walls...")
                phase4_upgrade()
                _walls = Autoclash._default_session.walls_upgraded_this_battle
                if _walls:
                    _upg_acct = Autoclash._default_session.current_account_name or target_account
                    account_upgrade_counts[_upg_acct] = account_upgrade_counts.get(_upg_acct, 0) + _walls
                    bot_reporter.report_upgrade(_upg_acct, "walls", account_upgrade_counts[_upg_acct])
            else:
                self.status_update.emit("Phase 4", "Phase 4 skipped (auto upgrade disabled)")
                bot_reporter.update_phase("Phase 4", "Phase 4 skipped (auto upgrade disabled)")

            if CONFIG.get("auto_upgrade_storages", True):
                self.overlay_draw.emit([], f"Cycle Accounts — Battle {battle_index}: Upgrading account")
                self.status_update.emit("Phase 5", "Upgrading account...")
                bot_reporter.update_phase("Phase 5", "Upgrading account...")
                upgrade_account()
                _upg_acct = Autoclash._default_session.current_account_name or target_account
                account_upgrade_counts[_upg_acct] = account_upgrade_counts.get(_upg_acct, 0) + 1
                bot_reporter.report_upgrade(_upg_acct, "account upgrade", account_upgrade_counts[_upg_acct])
            else:
                self.status_update.emit("Phase 5", "Phase 5 skipped (auto upgrade storages disabled)")
                bot_reporter.update_phase("Phase 5", "Phase 5 skipped (auto upgrade storages disabled)")

            battle_duration = time.time() - battle_start
            snapshot = getattr(LOOT_TRACKER, "last_snapshot", None)
            account_name = Autoclash._default_session.current_account_name
            walls = Autoclash._default_session.walls_upgraded_this_battle

            if account_name and snapshot:
                update_account_stats(account_name, snapshot, battle_duration, walls)
                self.battle_completed.emit(account_name, snapshot, battle_duration, walls)
                _gold = snapshot.get("gold", 0) if isinstance(snapshot, dict) else 0
                _elixir = snapshot.get("elixir", 0) if isinstance(snapshot, dict) else 0
                _dark = snapshot.get("dark_elixir", snapshot.get("dark", 0)) if isinstance(snapshot, dict) else 0
                account_attack_counts[account_name] = account_attack_counts.get(account_name, 0) + 1
                bot_reporter.report_battle_complete(account_name, _gold, _elixir, _dark, account_attack_counts[account_name])

            self.overlay_draw.emit([], f"Cycle Accounts — Battle {battle_index} complete")
            self.status_update.emit("Idle", f"Battle {battle_index} completed on '{target_account}'")
            bot_reporter.update_phase("Idle", f"Battle {battle_index} completed on '{target_account}'")
            time.sleep(2.0)
            return "ok"
        except Exception as exc:
            self.status_update.emit("Error", f"Error in cycle battle {battle_index}: {exc}")
            bot_reporter.report_error(f"Error in cycle battle {battle_index}: {exc}")
            return "failed"

    # noinspection PyUnresolvedReferences
    def run(self):  # noqa: C901
        try:
            bot_reporter.start()
            self.status_update.emit("Initializing", "Starting Cycle Accounts automation...")
            bot_reporter.update_phase("Initializing", "Starting Cycle Accounts automation...")
            bot_reporter.log("Cycle Accounts automation started")
            self.overlay_draw.emit([], "Cycle Accounts — Initialising")
            _set_overlay_callback(self.overlay_draw.emit)
            home_space_listener.start()

            battle_count = 0
            account_index = 0
            consecutive_switch_failures = 0
            account_attack_counts: dict = {}
            account_upgrade_counts: dict = {}

            while not self._stop_requested:
                target = self.selected_accounts[account_index % len(self.selected_accounts)]
                account_index += 1

                self.overlay_draw.emit([], f"Cycle Accounts — Switching to '{target}'")
                self.status_update.emit("Switch", f"Switching to account '{target}'...")
                bot_reporter.update_phase("Switch", f"Switching to account '{target}'...")
                bot_reporter.log(f"Switching to account: {target}")
                switched = _switch_to_target_fill_account([target])
                if not switched:
                    if self._stop_requested:
                        break
                    consecutive_switch_failures += 1
                    self.status_update.emit(
                        "Switch",
                        f"Failed to switch to '{target}', skipping... "
                        f"({consecutive_switch_failures}/{len(self.selected_accounts)} consecutive failures)"
                    )
                    bot_reporter.update_phase(
                        "Switch",
                        f"Failed to switch to '{target}', skipping... "
                        f"({consecutive_switch_failures}/{len(self.selected_accounts)} consecutive failures)"
                    )
                    bot_reporter.report_error(f"Failed to switch to account '{target}'")
                    if consecutive_switch_failures >= len(self.selected_accounts):
                        consecutive_switch_failures = 0
                        self.status_update.emit("Recovery", "All accounts failed to switch — performing hard game restart...")
                        bot_reporter.update_phase("Recovery", "All accounts failed to switch — performing hard game restart...")
                        bot_reporter.log("All accounts failed to switch — performing hard game restart")
                        self._perform_hard_game_restart()
                    time.sleep(3)
                    continue

                consecutive_switch_failures = 0

                self.account_detected.emit(switched)
                bot_reporter.update_account(switched)
                bot_reporter.log(f"Account active: {switched}")
                Autoclash._default_session.current_account_name = switched

                target_settings = self._get_account_settings(switched).copy()
                self._apply_settings(target_settings)
                self.status_update.emit("Account", f"Using '{switched}' settings")
                bot_reporter.update_phase("Account", f"Using '{switched}' settings")

                if not self._ensure_home_village_context(max_attempts=60):
                    if self._stop_requested:
                        break
                    time.sleep(2)
                    continue

                attacks_done = 0
                while not self._stop_requested and attacks_done < self.attacks_per_account:
                    battle_count += 1
                    attacks_done += 1
                    self.status_update.emit(
                        "Battle",
                        f"Attack {attacks_done}/{self.attacks_per_account} on '{target}' (total: {battle_count})..."
                    )
                    bot_reporter.update_phase(
                        "Battle",
                        f"Attack {attacks_done}/{self.attacks_per_account} on '{target}' (total: {battle_count})..."
                    )
                    result = self._run_single_cycle_battle(battle_count, target, account_attack_counts, account_upgrade_counts)

                    if result == "stop":
                        break
                    if result == "ok":
                        self._reset_failure_watchdog()
                        continue
                    if result == "failed":
                        self._handle_repeated_failure("cycle.battle.failed", action_label="Battle")
                    if result == "wrong-account":
                        self._handle_repeated_failure("cycle.battle.wrong_account", action_label="Account")
                        break

            home_space_listener.stop()

            if self._stop_requested:
                self.status_update.emit("Stopped", "Cycle Accounts stopped by user")
                bot_reporter.update_phase("Stopped", "Cycle Accounts stopped by user")

        except Exception as exc:
            log(f"FATAL ERROR in cycle accounts thread: {exc}")
            self.error_occurred.emit(str(exc))
            bot_reporter.report_error(f"FATAL: {exc}")
        finally:
            _set_overlay_callback(None)
            self.overlay_clear.emit()
            bot_reporter.stop()
            self.finished.emit()


# ═══════════════════════════════════════════════════════════════════════════
# 4) BuilderBaseWorker
# ═══════════════════════════════════════════════════════════════════════════

class BuilderBaseWorker(QThread, _RecoveryMixin):
    """Single-account Builder Base battle loop."""

    status_update = Signal(str, str)
    battle_completed = Signal(int, int)    # (battle_count, stars)
    overlay_draw = Signal(list, str)       # (detections, title)
    overlay_clear = Signal()
    error_occurred = Signal(str)
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True
        Autoclash_BB._default_session.shutdown_requested = True

    def run(self):
        try:
            self.status_update.emit("Initializing", "Starting BB automation...")
            self.overlay_draw.emit([], "Builder Base — Initialising")
            _set_overlay_callback(self.overlay_draw.emit)
            Autoclash_BB.space_listener.start()

            battle_count = 0

            while not self._stop_requested and not Autoclash_BB._default_session.shutdown_requested:
                self.status_update.emit(f"Battle {battle_count + 1}", f"Starting BB battle {battle_count + 1}...")

                try:
                    self.overlay_draw.emit([], f"Builder Base — Battle {battle_count + 1}: Finding match")
                    self.status_update.emit("Phase 1", "Finding match...")
                    if not Autoclash_BB.phase1_find_match():
                        if self._stop_requested or Autoclash_BB._default_session.shutdown_requested:
                            break
                        self._handle_repeated_failure("bb.phase1.find_match", action_label="Phase 1")
                        time.sleep(2)
                        continue

                    time.sleep(1)

                    self.overlay_draw.emit([], f"Builder Base — Battle {battle_count + 1}: Attacking")
                    self.status_update.emit("Phase 2", "Executing attack...")
                    try:
                        _p2_ok = Autoclash_BB.phase2_attack()
                    except SystemExit:
                        _p2_ok = False
                        self.status_update.emit("Phase 2", "BB battle timed out — treating as failure")
                    if not _p2_ok:
                        if self._stop_requested or Autoclash_BB._default_session.shutdown_requested:
                            break
                        self._handle_repeated_failure("bb.phase2.attack", action_label="Phase 2")
                        time.sleep(2)
                        continue

                    battle_count += 1
                    stars = Autoclash_BB.stats.get("last_battle_stars", 0)
                    Autoclash_BB.stats["battles_completed"] = battle_count
                    self._reset_failure_watchdog()
                    self.battle_completed.emit(battle_count, stars)
                    self.overlay_draw.emit([], f"Builder Base — Battle {battle_count} complete  ({stars} stars)")
                    self.status_update.emit("Idle", f"BB Battle {battle_count} completed! Stars: {stars}")
                    time.sleep(2)

                except Exception as e:
                    log(f"ERROR in BB battle {battle_count}: {e}")
                    self.status_update.emit("Error", f"Error in BB battle {battle_count}: {e}")
                    if self._stop_requested or Autoclash_BB._default_session.shutdown_requested:
                        break
                    self._handle_repeated_failure("bb.battle.exception", action_label="Error")
                    time.sleep(2)

            Autoclash_BB.space_listener.stop()

            if self._stop_requested or Autoclash_BB._default_session.shutdown_requested:
                self.status_update.emit("Stopped", "BB Automation stopped")
            else:
                self.status_update.emit("Complete", f"BB Automation completed! Total: {battle_count}")

        except Exception as e:
            log(f"FATAL ERROR in BB automation thread: {e}")
            self.error_occurred.emit(str(e))
        finally:
            _set_overlay_callback(None)
            self.overlay_clear.emit()
            Autoclash_BB._default_session.shutdown_requested = False
            self.finished.emit()


# ═══════════════════════════════════════════════════════════════════════════
# 4) BBFillAccountsWorker
# ═══════════════════════════════════════════════════════════════════════════

class BBFillAccountsWorker(QThread, _RecoveryMixin, _ContextMixin):
    """Builder Base fill-accounts mode."""

    status_update = Signal(str, str)
    battle_completed = Signal(int, int)    # (count, stars)
    account_detected = Signal(str)
    fill_progress = Signal(int, int)
    overlay_draw = Signal(list, str)       # (detections, title)
    overlay_clear = Signal()
    error_occurred = Signal(str)
    finished = Signal()

    def __init__(self, selected_accounts: List[str], parent=None):
        super().__init__(parent)
        self._stop_requested = False
        self.selected_accounts = list(selected_accounts)
        self.completed_accounts: Set[str] = set()

    def stop(self):
        self._stop_requested = True
        Autoclash_BB._default_session.shutdown_requested = True

    @staticmethod
    def _are_bb_storages_full() -> bool:
        return bool(Autoclash.check_gold_full()) and bool(Autoclash.check_elixir_full())

    def _bb_stopped(self) -> bool:
        return self._stop_requested or Autoclash_BB._default_session.shutdown_requested

    # noinspection PyUnresolvedReferences
    def run(self):  # noqa: C901
        original_thresh = Autoclash_BB.CONFIG.get("TEMPLATE_THRESH_DEFAULT", 0.85)
        try:
            self.status_update.emit("Initializing", "Starting BB Fill Accounts automation...")
            self.overlay_draw.emit([], "BB Fill Accounts — Initialising")
            _set_overlay_callback(self.overlay_draw.emit)
            Autoclash_BB._default_session.shutdown_requested = False
            Autoclash_BB.space_listener.start()
            Autoclash_BB.CONFIG["TEMPLATE_THRESH_DEFAULT"] = min(original_thresh, 0.84)

            Autoclash_BB.stats["battles_completed"] = 0
            Autoclash_BB.stats["total_stars"] = 0
            Autoclash_BB.stats["last_battle_stars"] = 0
            Autoclash_BB.stats["star_counts"] = {i: 0 for i in range(7)}
            Autoclash_BB.stats["start_time"] = time.time()

            battle_count = 0

            while not self._bb_stopped():
                remaining = [a for a in self.selected_accounts if a not in self.completed_accounts]
                if not remaining:
                    break

                self.fill_progress.emit(len(self.completed_accounts), len(self.selected_accounts))

                self.overlay_draw.emit([], "BB Fill Accounts — Switching account")
                target = _switch_to_target_fill_account(remaining)
                if not target:
                    if self._bb_stopped():
                        break
                    self._handle_repeated_failure("bbfill.switch.account", action_label="Switch")
                    time.sleep(3)
                    continue

                self.account_detected.emit(target)

                self.overlay_draw.emit([], f"BB Fill Accounts — Preparing BB for '{target}'")
                if not self._prepare_builder_base_after_switch(max_attempts=5):
                    if self._bb_stopped():
                        break
                    self._handle_repeated_failure("bbfill.prepare.after_switch", action_label="Switch")
                    time.sleep(2)
                    continue

                if self._are_bb_storages_full():
                    self.completed_accounts.add(target)
                    self.status_update.emit("Storage", f"'{target}' already full for BB. Marked complete.")
                    continue

                consecutive_p1_fail = 0
                while not self._bb_stopped():
                    if self._are_bb_storages_full():
                        self.completed_accounts.add(target)
                        self.status_update.emit("Storage", f"'{target}' is now full for BB.")
                        break

                    self.overlay_draw.emit([], f"BB Fill Accounts — Battle {battle_count + 1}: Finding match")
                    self.status_update.emit("Battle", f"Starting BB fill battle {battle_count + 1} on '{target}'...")

                    if not Autoclash_BB.phase1_find_match():
                        if self._bb_stopped():
                            break
                        consecutive_p1_fail += 1
                        self._handle_repeated_failure("bbfill.phase1.find_match", action_label="BB Find")

                        if consecutive_p1_fail >= 5:
                            consecutive_p1_fail = 0
                            if not self._prepare_builder_base_after_switch(max_attempts=5):
                                self._handle_repeated_failure("bbfill.prepare.after_retries", action_label="Switch")
                                break
                        time.sleep(2)
                        continue

                    consecutive_p1_fail = 0
                    time.sleep(1)

                    self.overlay_draw.emit([], f"BB Fill Accounts — Battle {battle_count + 1}: Attacking")
                    try:
                        _p2_ok = Autoclash_BB.phase2_attack()
                    except SystemExit:
                        _p2_ok = False
                        self.status_update.emit("Phase 2", "BB battle timed out — treating as failure")
                    if not _p2_ok:
                        if self._bb_stopped():
                            break
                        self._handle_repeated_failure("bbfill.phase2.attack", action_label="Phase 2")
                        time.sleep(2)
                        continue

                    battle_count += 1
                    stars = Autoclash_BB.stats.get("last_battle_stars", 0)
                    Autoclash_BB.stats["battles_completed"] = battle_count
                    self._reset_failure_watchdog()
                    self.battle_completed.emit(battle_count, stars)
                    self.overlay_draw.emit([], f"BB Fill Accounts — Battle {battle_count} complete  ({stars} stars)")
                    self.status_update.emit("Idle", f"BB fill battle {battle_count} complete on '{target}'")
                    time.sleep(2)

            Autoclash_BB.space_listener.stop()

            if self._bb_stopped():
                self.status_update.emit("Stopped", "BB Fill Accounts stopped")
            else:
                self.status_update.emit("Complete", "BB Fill Accounts completed: all selected accounts are full")

        except Exception as e:
            log(f"FATAL ERROR in BB fill automation thread: {e}")
            self.error_occurred.emit(str(e))
        finally:
            _set_overlay_callback(None)
            self.overlay_clear.emit()
            Autoclash_BB._default_session.shutdown_requested = False
            Autoclash_BB.CONFIG["TEMPLATE_THRESH_DEFAULT"] = original_thresh
            self.finished.emit()


# ═══════════════════════════════════════════════════════════════════════════
# ClanGamesWorker — Challenge cycler (all accounts)
# ═══════════════════════════════════════════════════════════════════════════

class ClanGamesWorker(QThread):
    """Runs the Clan Games challenge cycler in a background thread.

    Emits signals for GUI status updates and overlay drawing commands.
    Both ``validate_selection`` and ``pause_after_overlay`` are hard-coded
    to False (the prompts have been removed).
    """

    status_update = Signal(str, str)        # (phase, message)
    overlay_draw = Signal(list, str)         # (detections, title)
    overlay_clear = Signal()
    account_switched = Signal(str)           # ingame_name
    error_occurred = Signal(str)
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True

    def _stopped(self) -> bool:
        return self._stop_requested

    # ------------------------------------------------------------------

    def run(self):
        log("ClanGamesWorker: started")
        self.status_update.emit("Starting", "Clan Games Cycler starting…")

        last_trash_by_ingame: Dict[str, float] = {}

        try:
            while not self._stopped():
                # --- Run one account cycle ---
                self.status_update.emit("Cycle", "Verifying account…")
                current_ingame, trashed_any, cooldown_detected, stop_all = (
                    self._run_single_cycle()
                )

                if self._stopped():
                    break

                if stop_all:
                    self.status_update.emit("Complete", "All challenges cycled — nothing left to trash")
                    break

                if current_ingame and cooldown_detected:
                    clangamescycler._set_min_remaining_cooldown(
                        last_trash_by_ingame,
                        current_ingame,
                        clangamescycler.COOLDOWN_DETECTED_PENALTY_SECONDS,
                    )

                if current_ingame and trashed_any:
                    last_trash_by_ingame[current_ingame] = time.time()

                if self._stopped():
                    break

                # --- Switch account ---
                self.status_update.emit("Switching", "Switching account…")
                switched = self._choose_and_switch(last_trash_by_ingame)
                if not switched:
                    self.status_update.emit("Retry", "Account switch failed — retrying in 5s")
                    for _ in range(50):  # 5s in 0.1s ticks
                        if self._stopped():
                            break
                        time.sleep(0.1)
                    continue

                if current_ingame:
                    self.account_switched.emit(current_ingame)

                self.status_update.emit("Switched", "Account switched — next cycle in 2s")
                time.sleep(2.0)

        except Exception as e:
            log(f"ClanGamesWorker: Fatal error: {e}")
            import traceback
            traceback.print_exc()
            self.error_occurred.emit(str(e))
        finally:
            self.overlay_clear.emit()
            if self._stopped():
                self.status_update.emit("Stopped", "Clan Games Cycler stopped by user")
            self.finished.emit()

    # ------------------------------------------------------------------
    # Wrappers around clangamescycler functions that emit overlay signals
    # instead of calling the tkinter OverlayWindow directly.
    # ------------------------------------------------------------------

    def _run_single_cycle(self) -> Tuple[Optional[str], bool, bool, bool]:
        """Adapted from clangamescycler.run_single_account_cycle."""
        log("ClanGamesWorker: Verifying approved account name via OCR")
        if not clangamescycler.ensure_approved_account_with_fender_handling():
            log("ClanGamesWorker: Account verification failed")
            return None, False, False, False

        current_ingame = _normalize_text_for_ocr(Autoclash.current_account_name or "")
        if current_ingame:
            self.status_update.emit("Cycle", f"Running cycle on '{current_ingame}'")

        log("ClanGamesWorker: Scrolling down 5 times")
        Autoclash.scroll_down_5_times(Autoclash.WHEEL_DELTA * 3)

        stand_opened, cooldown_detected = clangamescycler.open_clan_games_stand()
        if not stand_opened:
            return current_ingame or None, False, cooldown_detected, False

        challenge_region = CONFIG.get("clan_games_challenge_region", (700, 200, 1700, 800))
        challenge_confidence = float(CONFIG.get("clan_games_challenge_confidence", CONFIG["confidence_threshold"]))
        start_template = CONFIG.get("clan_games_start_template", "clan_games_start.png")
        challenge_templates = clangamescycler._discover_challenge_templates()

        if not challenge_templates:
            clangamescycler.click_and_wait(1674, 109, action_desc="menu exit (no templates)")
            return current_ingame or None, False, False, False

        trashed_any = False
        scrolled_for_second_page = False

        # First page scan
        detections = clangamescycler.detect_valid_challenges(
            challenge_templates, challenge_confidence, challenge_region
        )
        bb_protected, bb_overlay = clangamescycler.detect_builder_side_protected_slots()
        self.overlay_draw.emit(detections + bb_overlay, "Challenge scan")
        self.status_update.emit("Scanning", f"Found {len(detections)} valid challenge(s)")

        invalid_slots = clangamescycler.pick_invalid_slots(detections, clangamescycler.GRID_COORDS)
        if bb_protected:
            protected_set = set(bb_protected)
            invalid_slots = [c for c in invalid_slots if c not in protected_set]

        if not invalid_slots:
            self.overlay_clear.emit()
            clangamescycler.scroll_challenge_list_once_down(challenge_region)
            scrolled_for_second_page = True

            detections = clangamescycler.detect_valid_challenges(
                challenge_templates, challenge_confidence, challenge_region
            )
            bb_protected, bb_overlay = clangamescycler.detect_builder_side_protected_slots()
            self.overlay_draw.emit(detections + bb_overlay, "Challenge scan (after scroll)")

            invalid_slots = clangamescycler.pick_invalid_slots(detections, clangamescycler.GRID_COORDS)
            if bb_protected:
                protected_set = set(bb_protected)
                invalid_slots = [c for c in invalid_slots if c not in protected_set]

        if invalid_slots:
            import random
            target = random.choice(invalid_slots)
            self.status_update.emit("Trashing", f"Trashing slot at {target}")
            self.overlay_clear.emit()
            if clangamescycler.trash_challenge_at_slot(target, start_template, overlay=None):
                trashed_any = True
        else:
            if scrolled_for_second_page:
                clangamescycler.click_and_wait(1674, 109, action_desc="final menu exit")
                self.overlay_clear.emit()
                return current_ingame or None, False, False, True  # stop_all

        clangamescycler.click_and_wait(1674, 109, action_desc="final menu exit")
        self.overlay_clear.emit()
        return current_ingame or None, trashed_any, False, False

    def _choose_and_switch(self, last_trash_by_ingame: Dict[str, float]) -> bool:
        """Adapted from clangamescycler.choose_and_switch_account — emits
        overlay signals instead of calling the tkinter overlay."""
        now = time.time()
        all_candidates = dict(clangamescycler.INGAME_TO_SWITCH_NAME)
        cooldown_remaining: Dict[str, float] = {
            ingame: clangamescycler._time_remaining(last_trash_by_ingame.get(ingame), now)
            for ingame in all_candidates
        }
        off_cd = [n for n, r in cooldown_remaining.items() if r <= 0]

        _open_account_switch_menu()

        max_scroll = 50

        def find_with_scroll(candidates, direction="down"):
            cand_map = {n: all_candidates[n] for n in candidates}
            for scan_idx in range(max_scroll + 1):
                visible = _match_visible_switch_accounts(cand_map)
                if visible:
                    overlay_dets = clangamescycler._build_account_overlay_detections(visible, cooldown_remaining)
                    self.overlay_draw.emit(overlay_dets, "Account candidates")
                    return visible
                if scan_idx < max_scroll:
                    self.overlay_clear.emit()
                    _scroll_switch_box_once(direction)
            return {}

        visible: dict = {}
        if off_cd:
            visible = find_with_scroll(off_cd, "down")

        if not visible:
            self.overlay_clear.emit()
            for _ in range(50):
                _scroll_switch_box_once("up")
            next_ready = min(cooldown_remaining.items(), key=lambda kv: kv[1])[0]
            visible = find_with_scroll([next_ready], "down")
            if not visible:
                return False

        selected_ingame, selected_data = min(
            visible.items(), key=lambda item: item[1]["center"][1]
        )
        Autoclash.click_with_jitter(*selected_data["center"])
        Autoclash.random_delay()
        time.sleep(3.0)
        self.overlay_clear.emit()
        _click_account_load_okay_if_present()
        return True


# ═══════════════════════════════════════════════════════════════════════════
# 6) ClanGamesMasterWorker — Combined attack + cycling bot
# ═══════════════════════════════════════════════════════════════════════════

class ClanGamesMasterWorker(QThread, _RecoveryMixin):
    """Runs the Clan Games Master Bot in a background thread.

    Combines the challenge-selection attack loop and challenge cycling across
    the 7 prepared accounts (williamleeming, lewis3–lewis8).
    """

    status_update     = Signal(str, str)   # (phase, message)
    account_changed   = Signal(str)         # current account name
    account_completed = Signal(str)         # account name when it reaches ~7000 pts
    mode_changed      = Signal(str)         # "Attacking" | "Cycling" | "Final Cycling"
    overlay_draw      = Signal(list, str)
    overlay_clear     = Signal()
    error_occurred    = Signal(str)
    finished          = Signal()

    def __init__(self, account_settings_getter, apply_settings_fn, parent=None):
        super().__init__(parent)
        self._stop_requested = False
        self._get_account_settings = account_settings_getter
        self._apply_settings = apply_settings_fn

    def stop(self):
        self._stop_requested = True
        Autoclash._default_session.stop_requested = True

    def _stopped(self) -> bool:
        return self._stop_requested

    def run(self):
        try:
            _set_overlay_callback(self.overlay_draw.emit)
            home_space_listener.start()

            def status_fn(phase: str, message: str) -> None:
                self.status_update.emit(phase, message)
                pl = phase.lower()
                ml = message.lower()
                if "attacking" in pl or "phase" in pl:
                    self.mode_changed.emit("Attacking")
                elif "final cycling" in pl or "final cycling" in ml:
                    self.mode_changed.emit("Final Cycling")
                elif "cycling" in pl or "cycling" in ml:
                    self.mode_changed.emit("Cycling")

            def apply_settings_fn(account_name: str) -> None:
                settings = self._get_account_settings(account_name)
                self._apply_settings(settings)
                self.account_changed.emit(account_name)

            def account_completed_fn(account_name: str) -> None:
                self.account_completed.emit(account_name)

            clangamesmaster.run_master_bot(
                stop_fn=self._stopped,
                status_fn=status_fn,
                account_completed_fn=account_completed_fn,
                apply_settings_fn=apply_settings_fn,
                overlay_fn=self.overlay_draw.emit,
                hard_reset_fn=self._perform_hard_game_restart,
            )

        except Exception as e:
            log(f"ClanGamesMasterWorker: Fatal error: {e}")
            import traceback
            traceback.print_exc()
            self.error_occurred.emit(str(e))
        finally:
            home_space_listener.stop()
            _set_overlay_callback(None)
            self.overlay_clear.emit()
            if self._stopped():
                self.status_update.emit("Stopped", "Clan Games Master Bot stopped by user")
            self.finished.emit()


# ═══════════════════════════════════════════════════════════════════════════
# 7) ClanScouterWorker
# ═══════════════════════════════════════════════════════════════════════════

class ClanScouterWorker(QThread):
    """Runs the Clan Scouter in a background thread.

    Switches to lewis3, then cycles through the clan search list bookmarking
    any Capital Hall 10 open-to-anyone clans it finds.  Space key or the GUI
    stop button halt it immediately.
    """

    status_update    = Signal(str, str)   # (phase, message)
    bookmark_changed = Signal(int)        # current bookmark count
    overlay_draw     = Signal(list, str)  # (detections, title)
    overlay_clear    = Signal()
    error_occurred   = Signal(str)
    finished         = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True

    def _stopped(self) -> bool:
        return self._stop_requested

    def run(self):
        log("ClanScouterWorker: started")
        _keyboard_registered = False
        try:
            # Register space key to allow instant stop
            try:
                import keyboard as _kb
                _kb.add_hotkey("space", self.stop)
                _keyboard_registered = True
            except Exception:
                log("ClanScouterWorker: keyboard module unavailable; space-stop disabled")

            self.overlay_draw.emit([], "Clan Scouter — Running")
            _set_overlay_callback(self.overlay_draw.emit)

            def _status(phase: str, msg: str):
                log(f"Scout: {phase} — {msg}")
                self.status_update.emit(phase, msg)
                self.overlay_draw.emit([], f"Clan Scouter — {phase}: {msg[:60]}")
                # Emit bookmark count whenever the message carries one
                m = re.search(r"Total:\s*(\d+)", msg)
                if m:
                    self.bookmark_changed.emit(int(m.group(1)))

            try:
                total = clanscouter.run_scouter(self._stopped, _status)
                if not self._stopped():
                    self.status_update.emit(
                        "Complete",
                        f"Scouter finished. Bookmarks made this session: {total}",
                    )
            except RuntimeError as exc:
                log(f"ClanScouterWorker: Aborted — {exc}")
                self.status_update.emit("Aborted", str(exc))
                self.error_occurred.emit(str(exc))

        except Exception as exc:
            log(f"ClanScouterWorker: Fatal error: {exc}")
            self.error_occurred.emit(str(exc))
        finally:
            _set_overlay_callback(None)
            self.overlay_clear.emit()
            if _keyboard_registered:
                try:
                    import keyboard as _kb
                    _kb.remove_hotkey("space")
                except Exception:
                    pass
            if self._stop_requested:
                self.status_update.emit("Stopped", "Clan Scouter stopped")
            self.finished.emit()


# ═══════════════════════════════════════════════════════════════════════════
# Clan Capital Raider Worker
# ═══════════════════════════════════════════════════════════════════════════

class ClanCapitalWorker(QThread, _RecoveryMixin, _ContextMixin):
    """Iterates over selected accounts and runs a full Clan Capital raid on each."""

    status_update = Signal(str, str)   # (phase, message)
    overlay_draw  = Signal(list, str)  # (detections, title)
    overlay_clear = Signal()
    error_occurred = Signal(str)
    finished = Signal()

    def __init__(
        self,
        selected_accounts: List[str],
        account_settings_getter,
        apply_settings_fn,
        return_to_main_clan: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._stop_requested = False
        self.selected_accounts = list(selected_accounts)
        self._get_account_settings = account_settings_getter
        self._apply_settings = apply_settings_fn
        self._return_to_main_clan = return_to_main_clan

    def stop(self):
        self._stop_requested = True
        Autoclash._default_session.stop_requested = True

    def run(self):
        log("ClanCapitalWorker: started")
        _keyboard_registered = False
        try:
            try:
                import keyboard as _kb
                _kb.add_hotkey("space", self.stop)
                _keyboard_registered = True
                log("ClanCapitalWorker: space-stop enabled")
            except Exception:
                log("ClanCapitalWorker: keyboard module unavailable; space-stop disabled")

            self.overlay_draw.emit([], "Capital Raid — Initialising")
            _set_overlay_callback(self.overlay_draw.emit)

            def _status(phase: str, msg: str):
                log(f"CapitalWorker: {phase} — {msg}")
                self.status_update.emit(phase, msg)
                self.overlay_draw.emit([], f"Capital Raid — {phase}: {msg[:60]}")

            _EXCLUDED_ACCOUNTS = {"lewis", "williamleeming"}

            for account in self.selected_accounts:
                if self._stop_requested:
                    break

                if account in _EXCLUDED_ACCOUNTS:
                    _status("Skip", f"Skipping excluded account '{account}'")
                    continue

                switched = None
                for attempt in range(1, 4):
                    if self._stop_requested:
                        break
                    _status("Switching", f"Switching to '{account}' (attempt {attempt}/3)…")
                    switched = _switch_to_target_fill_account([account])
                    if switched:
                        break
                    if attempt < 3:
                        self._handle_repeated_failure(
                            f"capital.switch.{account}", action_label="Switch"
                        )
                        time.sleep(3)

                if not switched:
                    _status("Warning", f"Could not switch to '{account}' after 3 attempts — skipping")
                    continue

                if not self._ensure_home_village_context(max_attempts=60):
                    if self._stop_requested:
                        break
                    _status("Warning", f"Could not reach home village on '{account}' — skipping")
                    continue

                # Find and join a valid Capital Hall 10 clan
                _status("ClanSearch", f"Finding a clan for '{account}'…")
                joined = capitalraider.find_and_join_clan(
                    stop_fn=lambda: self._stop_requested,
                    status_fn=_status,
                )
                if joined == "hard_reset_needed":
                    _status("Recovery", f"Clan search failed too many times for '{account}' — performing hard reset")
                    self._perform_hard_game_restart()
                    continue
                if not joined:
                    if self._stop_requested:
                        break
                    _status("Warning", f"Could not join a clan for '{account}' — skipping")
                    continue

                # Run raids, re-finding a new clan if the current one is exhausted
                while not self._stop_requested:
                    _status("Raiding", f"Starting capital raid for '{account}'…")
                    raid_result = capitalraider.run_capital_raid_for_account(
                        stop_fn=lambda: self._stop_requested,
                        status_fn=_status,
                    )

                    if raid_result == "clan_exhausted":
                        _status("ClanSearch", f"Clan exhausted — finding new clan for '{account}'…")
                        joined = capitalraider.find_and_join_clan(
                            stop_fn=lambda: self._stop_requested,
                            status_fn=_status,
                        )
                        if joined == "hard_reset_needed":
                            _status("Recovery", f"Clan search failed too many times for '{account}' — performing hard reset")
                            self._perform_hard_game_restart()
                            break
                        if not joined:
                            break
                        continue

                    break  # "done", "nav_failed", or "stopped"

                if not self._stop_requested and self._return_to_main_clan:
                    capitalraider.return_to_main_clan(
                        stop_fn=lambda: self._stop_requested,
                        status_fn=_status,
                    )

            if self._stop_requested:
                self.status_update.emit("Stopped", "Capital Raid stopped by user")
            else:
                self.status_update.emit("Complete", "Capital Raid complete for all selected accounts")

        except Exception as exc:
            log(f"ClanCapitalWorker: Fatal error: {exc}")
            self.error_occurred.emit(str(exc))
        finally:
            _set_overlay_callback(None)
            self.overlay_clear.emit()
            if _keyboard_registered:
                try:
                    import keyboard as _kb
                    _kb.remove_hotkey("space")
                except Exception:
                    pass
            self.finished.emit()


# ═══════════════════════════════════════════════════════════════════════════
# 8) UpgradeAccountsWorker
# ═══════════════════════════════════════════════════════════════════════════

# The djbillgates accounts available for upgrade cycling
DJBILLGATES_ACCOUNTS: List[str] = [
    "djbillgates22",
    "djbillgates23",
    "djbillgates24",
    "djbillgates25",
    "djbillgates26",
    "djbillgates27",
    "djbillgates28",
    "djbillgates29",
    "lewis3",
    "lewis4",
    "lewis5",
    "lewis6",
    "lewis7",
    "lewis8",
]

# All accounts available for the upgrade accounts feature
ALL_APPROVED_ACCOUNTS: List[str] = sorted([
    "lewis", "williamleeming", "steve",
    "lewis3", "lewis4", "lewis5", "lewis6", "lewis7", "lewis8",
    "djbillgates22", "djbillgates23", "djbillgates24", "djbillgates25",
    "djbillgates26", "djbillgates27", "djbillgates28", "djbillgates29",
    "djbillgates30", "djbillgates31", "djbillgates32", "djbillgates33",
    "djbillgates34", "djbillgates35", "djbillgates36", "djbillgates37",
    "djbillgates38", "djbillgates39", "djbillgates40", "djbillgates41",
])

# Per-account upgrade behaviour options
UPGRADE_BEHAVIOUR_FILL = 1      # Farm battles only — no upgrades, switch when storages full
UPGRADE_BEHAVIOUR_UPGRADE = 2   # Full upgrade_account() — storages, new buildings, any building (no TH)
UPGRADE_BEHAVIOUR_RUSH = 3      # rush_upgrade_account() — storages, new buildings, Town Hall only


class UpgradeAccountsWorker(QThread, _RecoveryMixin, _ContextMixin):
    """Cycles indefinitely through selected accounts using a per-account
    behaviour setting.

    Behaviour options (UPGRADE_BEHAVIOUR_* constants):
      1 — Fill Storages: farm until gold+elixir full, no Phase 5 upgrades.
      2 — Upgrade Account: existing upgrade_account() — storages, new
          buildings, any building except Town Hall.
      3 — Rush Account: rush_upgrade_account() — storages first, then new
          buildings, then Town Hall.  Returns False (switch) when nothing
          found, meaning the TH is already upgrading.

    Phase 4 (walls) is always skipped.
    """

    status_update = Signal(str, str)          # (phase, message)
    battle_completed = Signal(str, dict, float, int)
    account_detected = Signal(str)
    gem_upgrades_disabled = Signal(str)       # account name for which gem upgrades were disabled
    overlay_draw = Signal(list, str)          # (detections, title)
    overlay_clear = Signal()
    error_occurred = Signal(str)
    finished = Signal()

    def __init__(
        self,
        account_behaviours: Dict[str, int],
        account_settings_getter,
        apply_settings_fn,
        parent=None,
    ):
        super().__init__(parent)
        self._stop_requested = False
        self.account_behaviours: Dict[str, int] = dict(account_behaviours)
        self.selected_accounts: List[str] = list(account_behaviours.keys())
        self._get_account_settings = account_settings_getter
        self._apply_settings = apply_settings_fn

    def stop(self):
        self._stop_requested = True
        Autoclash._default_session.stop_requested = True

    @staticmethod
    def _resources_full_no_builder() -> bool:
        """Return True when both storages are full AND all builders are busy."""
        gold_full = bool(Autoclash.check_gold_full())
        elixir_full = bool(Autoclash.check_elixir_full())
        if not (gold_full and elixir_full):
            return False
        no_builders = Autoclash.find_template(
            "nobuilders.png",
            confidence=0.8,
            search_box=(835, 2, 1095, 129),
        )
        return bool(no_builders)

    def _run_single_upgrade_battle(self, battle_index: int, target_account: str, behaviour: int) -> str:
        """Run one full battle cycle (phases 1-3) then the appropriate Phase 5
        action based on *behaviour*.

        Returns
        -------
        "stop"              — stop was requested
        "failed"            — a phase failed
        "wrong-account"     — unexpected account detected after phase 1
        "ok"                — battle completed; caller decides whether to switch
        "ok_nothing_upgraded" — battle completed but Phase 5 found nothing (switch signal)
        """
        try:
            battle_start = time.time()
            Autoclash._default_session.walls_upgraded_this_battle = 0

            self.overlay_draw.emit([], f"Upgrade Accounts — Battle {battle_index}: Checking context")
            if not self._ensure_home_village_context(max_attempts=60):
                if self._stop_requested:
                    return "stop"
                return "failed"

            self.overlay_draw.emit([], f"Upgrade Accounts — Battle {battle_index}: Entering battle")
            self.status_update.emit("Phase 1", "Entering battle...")
            if not phase1_enter_battle(skip_account_check=False):
                if self._stop_requested:
                    return "stop"
                time.sleep(3)
                return "failed"

            confirmed = normalize_account_name(Autoclash._default_session.current_account_name or "")
            if not confirmed or confirmed != target_account:
                self.status_update.emit("Account", f"Account changed to '{confirmed}' while targeting '{target_account}'")
                return "wrong-account"

            self.overlay_draw.emit([], f"Upgrade Accounts — Battle {battle_index}: Preparing")
            self.status_update.emit("Phase 2A", "Preparing battle...")
            if not phase2_prepare():
                if self._stop_requested:
                    return "stop"
                time.sleep(3)
                return "failed"

            self.overlay_draw.emit([], f"Upgrade Accounts — Battle {battle_index}: Deploying troops")
            self.status_update.emit("Phase 2B", "Deploying troops...")
            if not phase2_execute():
                if self._stop_requested:
                    return "stop"
                time.sleep(3)
                return "failed"

            self.overlay_draw.emit([], f"Upgrade Accounts — Battle {battle_index}: Waiting for return")
            self.status_update.emit("Phase 3", "Waiting for battle to end...")
            if not phase3_wait_for_return():
                if self._stop_requested:
                    return "stop"
                time.sleep(3)
                return "failed"

            battle_duration = time.time() - battle_start
            snapshot = getattr(LOOT_TRACKER, "last_snapshot", None)
            account_name = Autoclash._default_session.current_account_name
            if account_name and snapshot:
                update_account_stats(account_name, snapshot, battle_duration, walls_upgraded=0)
                self.battle_completed.emit(account_name, snapshot, battle_duration, 0)

            # Phase 5 — depends on per-account behaviour
            self.status_update.emit("Loading", "Waiting for Phase 5 to load...")
            time.sleep(5)

            if behaviour == UPGRADE_BEHAVIOUR_FILL:
                # No upgrades — just farming; switch condition checked by caller
                self.status_update.emit("Phase 5", "Fill mode — no upgrades performed")
                self.overlay_draw.emit([], f"Upgrade Accounts — Battle {battle_index} complete (fill)")
                self.status_update.emit("Idle", f"Battle {battle_index} completed on '{target_account}' (fill)")
                time.sleep(2.0)
                return "ok"

            elif behaviour == UPGRADE_BEHAVIOUR_UPGRADE:
                self.overlay_draw.emit([], f"Upgrade Accounts — Battle {battle_index}: Upgrading account")
                self.status_update.emit("Phase 5", "Upgrading account...")
                phase5_found_something = upgrade_account()

            else:  # UPGRADE_BEHAVIOUR_RUSH
                self.overlay_draw.emit([], f"Upgrade Accounts — Battle {battle_index}: Rush upgrading account")
                self.status_update.emit("Phase 5", "Rush upgrading (storages → new buildings → Town Hall)...")
                phase5_found_something = rush_upgrade_account()

            disabled_acct = pop_gem_upgrades_disabled()
            if disabled_acct:
                self.gem_upgrades_disabled.emit(disabled_acct)

            self.overlay_draw.emit([], f"Upgrade Accounts — Battle {battle_index} complete")
            self.status_update.emit("Idle", f"Battle {battle_index} completed on '{target_account}'")
            time.sleep(2.0)
            return "ok" if phase5_found_something else "ok_nothing_upgraded"

        except Exception as exc:
            self.status_update.emit("Error", f"Error in upgrade battle {battle_index}: {exc}")
            return "failed"

    # noinspection PyUnresolvedReferences
    def run(self):  # noqa: C901
        try:
            self.status_update.emit("Initializing", "Starting Upgrade Accounts automation...")
            self.overlay_draw.emit([], "Upgrade Accounts — Initialising")
            _set_overlay_callback(self.overlay_draw.emit)
            home_space_listener.start()

            battle_count = 0
            account_index = 0
            consecutive_switch_failures = 0

            while not self._stop_requested:
                target = self.selected_accounts[account_index % len(self.selected_accounts)]
                account_index += 1
                behaviour = self.account_behaviours.get(target, UPGRADE_BEHAVIOUR_UPGRADE)

                self.overlay_draw.emit([], f"Upgrade Accounts — Switching to '{target}'")
                self.status_update.emit("Switch", f"Switching to account '{target}'...")
                switched = _switch_to_target_fill_account([target])
                if not switched:
                    if self._stop_requested:
                        break
                    consecutive_switch_failures += 1
                    self.status_update.emit(
                        "Switch",
                        f"Failed to switch to '{target}', skipping... "
                        f"({consecutive_switch_failures}/{len(self.selected_accounts)} consecutive failures)"
                    )
                    if consecutive_switch_failures >= len(self.selected_accounts):
                        consecutive_switch_failures = 0
                        self.status_update.emit("Recovery", "All accounts failed to switch — performing hard game restart...")
                        self._perform_hard_game_restart()
                    time.sleep(3)
                    continue

                consecutive_switch_failures = 0

                self.account_detected.emit(switched)
                Autoclash._default_session.current_account_name = switched

                target_settings = self._get_account_settings(switched).copy()
                target_settings["auto_upgrade_walls"] = False
                target_settings["auto_upgrade_storages"] = behaviour != UPGRADE_BEHAVIOUR_FILL
                self._apply_settings(target_settings)

                behaviour_labels = {
                    UPGRADE_BEHAVIOUR_FILL: "Fill Storages",
                    UPGRADE_BEHAVIOUR_UPGRADE: "Upgrade Account",
                    UPGRADE_BEHAVIOUR_RUSH: "Rush Account",
                }
                self.status_update.emit(
                    "Account",
                    f"Using '{switched}' — mode: {behaviour_labels.get(behaviour, '?')} (walls OFF)"
                )

                if not self._ensure_home_village_context(max_attempts=60):
                    if self._stop_requested:
                        break
                    time.sleep(2)
                    continue

                # Pre-battle switch checks per behaviour
                if behaviour == UPGRADE_BEHAVIOUR_FILL:
                    if self._are_storages_full():
                        self.status_update.emit(
                            "Skip",
                            f"'{switched}': storages already full (fill mode) — moving to next account"
                        )
                        continue
                else:
                    if self._resources_full_no_builder():
                        self.status_update.emit(
                            "Skip",
                            f"'{switched}': resources full and no free builder — skipping to next account"
                        )
                        continue

                # Run battles until the switch condition is met or stop is requested
                while not self._stop_requested:
                    battle_count += 1
                    self.status_update.emit("Battle", f"Starting upgrade battle {battle_count} on '{switched}'...")
                    result = self._run_single_upgrade_battle(battle_count, switched, behaviour)

                    if result == "stop":
                        break
                    if result in ("ok", "ok_nothing_upgraded"):
                        self._reset_failure_watchdog()
                        if result == "ok_nothing_upgraded":
                            if behaviour == UPGRADE_BEHAVIOUR_RUSH:
                                self.status_update.emit(
                                    "Switch",
                                    f"'{switched}': no storages, new buildings, or Town Hall available "
                                    f"— Town Hall must be upgrading, moving to next account"
                                )
                            else:
                                self.status_update.emit(
                                    "Switch",
                                    f"'{switched}': Phase 5 found nothing to upgrade — moving to next account"
                                )
                            break
                        # Check post-battle switch condition
                        if behaviour == UPGRADE_BEHAVIOUR_FILL:
                            if self._are_storages_full():
                                self.status_update.emit(
                                    "Switch",
                                    f"'{switched}': storages full (fill mode) — moving to next account"
                                )
                                break
                        else:
                            if self._resources_full_no_builder():
                                self.status_update.emit(
                                    "Switch",
                                    f"'{switched}': resources full and no free builder — moving to next account"
                                )
                                break
                        continue
                    if result == "failed":
                        self._handle_repeated_failure("upgrade.battle.failed", action_label="Battle")
                    if result == "wrong-account":
                        self._handle_repeated_failure("upgrade.battle.wrong_account", action_label="Account")
                        break

            home_space_listener.stop()

            if self._stop_requested:
                self.status_update.emit("Stopped", "Upgrade Accounts stopped by user")

        except Exception as exc:
            log(f"FATAL ERROR in upgrade accounts thread: {exc}")
            self.error_occurred.emit(str(exc))
        finally:
            _set_overlay_callback(None)
            self.overlay_clear.emit()
            self.finished.emit()


# ═══════════════════════════════════════════════════════════════════════════
# 9) AccountCreationWorker
# ═══════════════════════════════════════════════════════════════════════════

class AccountCreationWorker(QThread):
    """
    Creates a new Clash of Clans account from scratch, assigns a Supercell ID,
    and saves the result to created_accounts.json and Autoclash.py.

    Signals
    -------
    log_message  — (str) text log lines for display in the GUI
    finished     — () emitted when the flow completes successfully
    error        — (str) emitted if an exception terminates the flow
    """

    log_message = Signal(str)
    finished = Signal()
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        try:
            self.log_message.emit("AccountCreation: Importing accountcreator module...")
            import accountcreator as _ac

            self.log_message.emit("AccountCreation: Authorising Gmail API...")
            service = _ac.get_gmail_service()

            self.log_message.emit("AccountCreation: Starting account creation flow...")
            creator = _ac.AccountCreator(service)
            self.log_message.emit(
                f"AccountCreation: Target account — name='{creator._name}', "
                f"email='{creator._email}'"
            )
            creator.run()

            self.log_message.emit(
                f"AccountCreation: SUCCESS — account '{creator._name}' created."
            )

        except Exception as exc:
            log(f"FATAL ERROR in account creation thread: {exc}")
            self.error.emit(str(exc))
        finally:
            self.finished.emit()
