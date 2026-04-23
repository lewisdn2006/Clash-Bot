#!/usr/bin/env python3
"""
Clan Games Challenge Cycler
===========================
Standalone helper to cycle bad Clan Games challenges on the current account.

Behavior:
- Uses the same account OCR/approval path as Autoclash
- Performs the same post-account zoom-out (scroll down 5 times)
- Uses the same Clan Games stand drag/find/click routine
- Detects valid challenges via clan_games_challenge_*.png templates
- Trashes invalid challenge slots in one pass
- Shows an always-on-top transparent overlay with boxes/labels for valid detections

Run:
    python clangamescycler.py
"""

from __future__ import annotations

import random
import threading
import time
import queue
import re
import tempfile
import subprocess
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import pyautogui

import Autoclash as AC
import vision as _vision

try:
    import tkinter as tk
    HAS_TK = True
except Exception:
    HAS_TK = False


GridCoord = Tuple[int, int]
BBox = Tuple[int, int, int, int]


GRID_COORDS: List[GridCoord] = [
    (793, 311),
    (1047, 311),
    (1295, 311),
    (1548, 311),
    (793, 624),
    (1047, 624),
    (1295, 624),
    (1548, 624),
]

COOLDOWN_SECONDS = 10 * 60 + 30
COOLDOWN_DETECTED_PENALTY_SECONDS = 10 * 60
ACCOUNT_NAME_MIN_CONFIDENCE = 0.75
BB_SIDE_TEMPLATE = "clan_games_bbside.png"
BB_SIDE_CONFIDENCE = 0.85

SETTINGS_MENU_COORD = (1852, 841)
ACCOUNT_SWITCH_MENU_COORD = (1245, 244)
ACCOUNT_SWITCH_BOX = (1321, 496, 1917, 1080)

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
    "djbillgates23": "DJBillGates123",
    "djbillgates24": "DJBillGates24",
    "djbillgates25": "DJBillGates25",
    "djbillgates26": "DJBillGates26",
    "djbillgates27": "DJBillGates27",
    "djbillgates28": "DJBillGates28",
    "djbillgates29": "DJBillGates29",
}


class OverlayWindow:
    """Transparent topmost overlay that draws detected valid challenges."""

    def __init__(self) -> None:
        self.enabled = HAS_TK
        self._queue: "queue.Queue[Tuple[str, object]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if not self.enabled:
            AC.log("Overlay: tkinter unavailable, overlay disabled")
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self.enabled:
            return
        self._queue.put(("stop", None))

    def show_detections(self, detections: List[Dict[str, object]], title: str = "") -> None:
        if not self.enabled:
            return
        self._queue.put(("draw", (detections, title)))

    def clear(self) -> None:
        if not self.enabled:
            return
        self._queue.put(("clear", None))

    def _run(self) -> None:
        root = tk.Tk()
        root.title("Clan Games Overlay")
        root.overrideredirect(True)
        root.attributes("-topmost", True)

        transparent_color = "#ff00ff"
        root.configure(bg=transparent_color)
        try:
            root.attributes("-transparentcolor", transparent_color)
        except Exception:
            AC.log("Overlay: transparent color not supported; using semi-transparent window")
            root.attributes("-alpha", 0.35)

        screen_w, screen_h = pyautogui.size()
        root.geometry(f"{screen_w}x{screen_h}+0+0")

        canvas = tk.Canvas(root, width=screen_w, height=screen_h, bg=transparent_color, highlightthickness=0)
        canvas.pack(fill="both", expand=True)

        def process_queue() -> None:
            try:
                while True:
                    msg, payload = self._queue.get_nowait()
                    if msg == "stop":
                        root.destroy()
                        return
                    if msg == "clear":
                        canvas.delete("all")
                    elif msg == "draw":
                        canvas.delete("all")
                        detections, title = payload  # type: ignore[misc]

                        if title:
                            canvas.create_text(
                                12,
                                12,
                                text=title,
                                anchor="nw",
                                fill="#00ff00",
                                font=("Arial", 14, "bold"),
                            )

                        for det in detections:
                            shape = det.get("shape", "rect")  # type: ignore[call-arg]
                            label = det.get("label", "")  # type: ignore[call-arg]
                            score = float(det.get("score", 0.0))  # type: ignore[call-arg]

                            if shape == "circle":
                                cx, cy = det["center"]  # type: ignore[index]
                                radius = int(det.get("radius", 12))  # type: ignore[call-arg]
                                canvas.create_oval(
                                    cx - radius,
                                    cy - radius,
                                    cx + radius,
                                    cy + radius,
                                    outline="#00ffff",
                                    width=2,
                                )
                                canvas.create_rectangle(
                                    cx + 10,
                                    cy - 20,
                                    cx + 150,
                                    cy,
                                    fill="#002233",
                                    outline="#00ffff",
                                )
                                canvas.create_text(
                                    cx + 14,
                                    cy - 10,
                                    text=label,
                                    anchor="w",
                                    fill="#00ffff",
                                    font=("Arial", 10, "bold"),
                                )
                            else:
                                x1, y1, x2, y2 = det["bbox"]  # type: ignore[index]
                                canvas.create_rectangle(x1, y1, x2, y2, outline="#00ff00", width=2)
                                canvas.create_rectangle(x1, y1 - 20, x1 + 170, y1, fill="#001a00", outline="#00ff00")
                                canvas.create_text(
                                    x1 + 4,
                                    y1 - 10,
                                    text=f"{label} ({score:.3f})",
                                    anchor="w",
                                    fill="#00ff00",
                                    font=("Arial", 10, "bold"),
                                )
            except queue.Empty:
                pass

            root.after(60, process_queue)

        root.after(60, process_queue)
        root.mainloop()


def _get_image_folder_path() -> Path:
    script_dir = Path(__file__).parent
    if AC.CONFIG.get("image_folder") == ".":
        return script_dir
    return Path(AC.CONFIG["image_folder"])


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "", value or "").strip().lower()


def _preprocess_for_ocr(pil_image) -> np.ndarray:
    img_np = np.array(pil_image)
    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
    upscaled = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    blur = cv2.GaussianBlur(upscaled, (3, 3), 0)
    _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return thresh


def _ocr_tsv_records_in_region(region: Tuple[int, int, int, int]) -> List[Dict[str, object]]:
    x1, y1, x2, y2 = region
    width, height = x2 - x1, y2 - y1
    screenshot = _vision.safe_screenshot(region=(x1, y1, width, height))
    processed = _preprocess_for_ocr(screenshot)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        image_path = tmp.name
        cv2.imwrite(image_path, processed)

    records: List[Dict[str, object]] = []
    try:
        result = subprocess.run(
            [AC.TESSERACT_PATH, image_path, "stdout", "tsv"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            AC.log(f"Cycler OCR: tesseract returned code {result.returncode}")
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

            text_norm = _normalize_text(text)
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
            w = int(cols[index_map["width"]])
            h = int(cols[index_map["height"]])

            abs_x1 = x1 + left // 2
            abs_y1 = y1 + top // 2
            abs_x2 = abs_x1 + max(1, w // 2)
            abs_y2 = abs_y1 + max(1, h // 2)
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
    except Exception as exc:
        AC.log(f"Cycler OCR: Failed parsing sidebar text: {exc}")
        return []
    finally:
        try:
            os.remove(image_path)
        except Exception:
            pass

    return records


def _normalize_ocr_confidence(raw_conf: float) -> float:
    """Normalize OCR confidence to 0..1 scale (TSV often returns 0..100)."""
    if raw_conf <= 1.0:
        return max(0.0, min(1.0, raw_conf))
    return max(0.0, min(1.0, raw_conf / 100.0))


def _match_visible_switch_accounts(candidates: Dict[str, str]) -> Dict[str, Dict[str, object]]:
    """Return visible candidate accounts keyed by ingame name with click center and OCR metadata."""
    visible: Dict[str, Dict[str, object]] = {}
    ocr_rows = _ocr_tsv_records_in_region(ACCOUNT_SWITCH_BOX)

    for ingame_name, switch_name in candidates.items():
        target_norm = _normalize_text(switch_name)
        best_row = None
        best_score = -1.0

        for row in ocr_rows:
            row_norm = row["text_norm"]  # type: ignore[index]
            if len(row_norm) < 4:
                continue  # skip short fragments — single chars always substring-match long names
            # When a fragment is a substring of the target, require it to cover ≥80% of the
            # target's length to prevent short shared substrings causing false positives.
            fragment_match = (row_norm in target_norm and len(row_norm) >= len(target_norm) * 0.8)
            if target_norm in row_norm or fragment_match:
                conf = _normalize_ocr_confidence(float(row["conf"]))  # type: ignore[index]
                if conf < ACCOUNT_NAME_MIN_CONFIDENCE:
                    continue
                if conf > best_score:
                    best_row = row
                    best_score = conf

        if best_row is not None:
            visible[ingame_name] = {
                "switch_name": switch_name,
                "center": best_row["center"],
                "bbox": best_row["bbox"],
                "ocr_text": best_row["text"],
                "ocr_conf": best_score,
            }

    return visible


def _time_remaining(last_trash_time: Optional[float], now: float) -> float:
    if last_trash_time is None:
        return 0.0
    elapsed = now - last_trash_time
    remaining = COOLDOWN_SECONDS - elapsed
    return max(0.0, remaining)


def _set_min_remaining_cooldown(last_trash_by_ingame: Dict[str, float], ingame_name: str, min_remaining_seconds: float) -> None:
    """Ensure account has at least min_remaining_seconds cooldown remaining."""
    if not ingame_name:
        return
    now = time.time()
    current_remaining = _time_remaining(last_trash_by_ingame.get(ingame_name), now)
    target_remaining = max(current_remaining, min_remaining_seconds)
    synthetic_last_trash = now - (COOLDOWN_SECONDS - target_remaining)
    last_trash_by_ingame[ingame_name] = synthetic_last_trash


def _format_remaining(seconds: float) -> str:
    whole = int(max(0, seconds))
    mins, secs = divmod(whole, 60)
    return f"{mins:02d}:{secs:02d}"


def _open_account_switch_menu() -> None:
    AC.log("Cycler: Opening settings menu")
    click_and_wait(*SETTINGS_MENU_COORD, action_desc="settings menu click")
    AC.log("Cycler: Opening account switch menu")
    click_and_wait(*ACCOUNT_SWITCH_MENU_COORD, action_desc="account switch menu click")
    time.sleep(1.0)


def _scroll_switch_box_once_down() -> None:
    x1, y1, x2, y2 = ACCOUNT_SWITCH_BOX
    center_x = (x1 + x2) // 2
    center_y = (y1 + y2) // 2
    pyautogui.moveTo(center_x, center_y, duration=0.1)

    # Scroll while cursor stays in the account list box.
    # Avoid AC.scroll_api here because it recenters the mouse first.
    try:
        AC._send_wheel(-abs(int(AC.WHEEL_DELTA)))  # type: ignore[attr-defined]
    except Exception:
        pyautogui.scroll(-abs(int(AC.WHEEL_DELTA)))

    AC.log("Cycler: Scrolled account switch box down once")
    time.sleep(0.5)


def _scroll_switch_box_once_up() -> None:
    x1, y1, x2, y2 = ACCOUNT_SWITCH_BOX
    center_x = (x1 + x2) // 2
    center_y = (y1 + y2) // 2
    pyautogui.moveTo(center_x, center_y, duration=0.1)

    # Scroll while cursor stays in the account list box.
    # Avoid AC.scroll_api here because it recenters the mouse first.
    try:
        AC._send_wheel(abs(int(AC.WHEEL_DELTA)))  # type: ignore[attr-defined]
    except Exception:
        pyautogui.scroll(abs(int(AC.WHEEL_DELTA)))

    AC.log("Cycler: Scrolled account switch box up once")
    time.sleep(0.5)


def scroll_challenge_list_once_down(challenge_region: Tuple[int, int, int, int]) -> None:
    """Scroll challenge list down (double action) from region center."""
    x1, y1, x2, y2 = challenge_region
    center_x = (x1 + x2) // 2
    center_y = (y1 + y2) // 2
    pyautogui.moveTo(center_x, center_y, duration=0.1)

    # Two downward scroll actions while keeping cursor in-region
    # (avoid recentering behavior).
    scroll_amount = AC.WHEEL_DELTA * 2
    for _ in range(2):
        try:
            AC._send_wheel(-abs(int(scroll_amount)))  # type: ignore[attr-defined]
        except Exception:
            pyautogui.scroll(-abs(int(scroll_amount)))
        time.sleep(0.12)

    AC.log("Cycler: Scrolled challenge list down (double action)")
    time.sleep(0.6)


def _build_account_overlay_detections(
    visible_accounts: Dict[str, Dict[str, object]],
    cooldown_remaining: Dict[str, float],
) -> List[Dict[str, object]]:
    detections: List[Dict[str, object]] = []
    for ingame_name, data in visible_accounts.items():
        remaining = cooldown_remaining.get(ingame_name, 0.0)
        detections.append(
            {
                "bbox": data["bbox"],
                "label": f"{ingame_name} [{_format_remaining(remaining)}]",
                "score": float(data.get("ocr_conf", 0.0)),
            }
        )
    return detections


def choose_and_switch_account(
    last_trash_by_ingame: Dict[str, float],
    overlay: OverlayWindow,
    validate_selection: bool,
    pause_after_overlay: bool,
) -> bool:
    """
    Select account from switcher according to cooldown policy:
    - Search for off-cooldown accounts by scrolling down up to 20 times
    - If multiple off-cooldown accounts are visible, click highest one
    - If none found, scroll up 20 times to reset list position
    - Then scroll down until finding the single account with lowest cooldown remaining
    """
    now = time.time()

    all_candidates = dict(INGAME_TO_SWITCH_NAME)
    cooldown_remaining: Dict[str, float] = {
        ingame: _time_remaining(last_trash_by_ingame.get(ingame), now)
        for ingame in all_candidates
    }

    off_cd = [name for name, rem in cooldown_remaining.items() if rem <= 0]

    _open_account_switch_menu()

    max_scroll_attempts = 20

    def find_visible_with_scroll(
        candidates: Dict[str, str],
        title_prefix: str,
        scroll_direction: str = "down",
    ) -> Dict[str, Dict[str, object]]:
        """Scan visible accounts and scroll down until matches are found or attempts exhausted."""
        for scan_idx in range(max_scroll_attempts + 1):
            visible_now = _match_visible_switch_accounts(candidates)
            if visible_now:
                overlay.show_detections(
                    _build_account_overlay_detections(visible_now, cooldown_remaining),
                    title=title_prefix,
                )
                pause_if_overlay_enabled(pause_after_overlay, title_prefix.lower())
                return visible_now

            if scan_idx < max_scroll_attempts:
                AC.log(
                    f"Cycler: No matching account visible ({title_prefix.lower()} scan {scan_idx + 1}/{max_scroll_attempts + 1}) - scrolling {scroll_direction}"
                )
                overlay.clear()
                if scroll_direction == "up":
                    _scroll_switch_box_once_up()
                else:
                    _scroll_switch_box_once_down()

        return {}

    visible: Dict[str, Dict[str, object]] = {}

    if off_cd:
        pool = {name: all_candidates[name] for name in off_cd}
        AC.log(f"Cycler: Off-cooldown accounts available: {off_cd}")
        visible = find_visible_with_scroll(pool, "Account candidates", scroll_direction="down")

    if not visible:
        next_ready = min(cooldown_remaining.items(), key=lambda kv: kv[1])[0]
        AC.log(
            "Cycler: No off-cooldown account found after 20 down-scrolls; "
            "resetting list by scrolling up 20 times"
        )

        overlay.clear()
        for _ in range(20):
            _scroll_switch_box_once_up()

        next_pool = {next_ready: all_candidates[next_ready]}
        AC.log(
            "Cycler: Searching for lowest-cooldown account "
            f"'{next_ready}' (remaining {_format_remaining(cooldown_remaining[next_ready])})"
        )
        visible = find_visible_with_scroll(next_pool, "Next cooldown account", scroll_direction="down")

        if not visible:
            AC.log("Cycler: Could not find target account after reset + down-scroll search")
            return False

    # Click highest (smallest y) among visible candidates
    selected_ingame, selected_data = min(
        visible.items(), key=lambda item: item[1]["center"][1]  # type: ignore[index]
    )
    selected_center = selected_data["center"]  # type: ignore[index]
    selected_switch_name = selected_data["switch_name"]  # type: ignore[index]
    AC.log(
        f"Cycler: Switching to '{selected_ingame}' via '{selected_switch_name}' "
        f"at {selected_center}"
    )

    if validate_selection:
        AC.log("Cycler: Account validation mode is ON")
        while True:
            user_input = input(
                f"Switch to '{selected_ingame}' via '{selected_switch_name}' at {selected_center}? "
                "Type yes to continue: "
            ).strip().lower()
            if user_input in ("yes", "y"):
                break
            AC.log("Cycler: Waiting for explicit 'yes' before selecting account")

    AC.click_with_jitter(*selected_center)
    AC.random_delay()
    AC.log("Cycler: Waiting 3 seconds after account switch selection")
    time.sleep(3.0)
    overlay.clear()

    load_ok_template = "account_load_okay.png"
    found_load_ok = False
    for attempt in range(1, 6):
        load_ok_coords = AC.find_template(load_ok_template)
        if load_ok_coords:
            AC.log(
                f"Cycler: Found '{load_ok_template}' at {load_ok_coords} "
                f"(attempt {attempt}/5) - clicking"
            )
            AC.click_with_jitter(*load_ok_coords)
            AC.random_delay()
            found_load_ok = True
            break

        if attempt < 5:
            AC.log(f"Cycler: '{load_ok_template}' not found (attempt {attempt}/5) - retrying")
            time.sleep(1.0)

    if not found_load_ok:
        AC.log(f"Cycler: '{load_ok_template}' not found after 5 attempts - continuing")

    return True


def ask_validate_account_choice_mode() -> bool:
    """Prompt once at startup: require manual yes before account selection or not."""
    while True:
        answer = input("Validate account choice before clicking? (yes/no): ").strip().lower()
        if answer in ("yes", "y"):
            AC.log("Cycler: Validate account choice = YES")
            return True
        if answer in ("no", "n"):
            AC.log("Cycler: Validate account choice = NO")
            return False
        print("Please enter yes or no.")


def ask_pause_after_overlay_mode() -> bool:
    """Prompt once at startup: independently pause after each overlay render or not."""
    while True:
        answer = input("Validate overlay view (pause after overlay is shown)? (yes/no): ").strip().lower()
        if answer in ("yes", "y"):
            AC.log("Cycler: Pause after overlay = YES")
            return True
        if answer in ("no", "n"):
            AC.log("Cycler: Pause after overlay = NO")
            return False
        print("Please enter yes or no.")


def pause_if_overlay_enabled(pause_after_overlay: bool, context: str) -> None:
    if not pause_after_overlay:
        return
    input(f"Overlay shown ({context}). Press Enter to continue...")


def _discover_challenge_templates() -> List[str]:
    prefix = AC.CONFIG.get("clan_games_challenge_prefix", "clan_games_challenge_")
    image_folder = _get_image_folder_path()
    templates = sorted(path.name for path in image_folder.glob(f"{prefix}*.png") if path.is_file())
    return templates


def _load_template_gray(template_name: str) -> Optional[np.ndarray]:
    image_folder = _get_image_folder_path()
    template_path = image_folder / template_name
    if not template_path.exists():
        AC.log(f"Cycler: Template not found: {template_path}")
        return None
    template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
    if template is None:
        AC.log(f"Cycler: Failed to load template: {template_path}")
    return template


def detect_template_bbox(
    template_name: str,
    confidence: float,
    search_region: Optional[Tuple[int, int, int, int]] = None,
) -> Optional[Dict[str, object]]:
    template = _load_template_gray(template_name)
    if template is None:
        return None

    if search_region is not None:
        x1, y1, x2, y2 = search_region
        screenshot = _vision.safe_screenshot(region=(x1, y1, x2 - x1, y2 - y1))
        offset_x, offset_y = x1, y1
    else:
        screenshot = _vision.safe_screenshot()
        offset_x, offset_y = 0, 0

    screenshot_np = np.array(screenshot)
    screenshot_gray = cv2.cvtColor(screenshot_np, cv2.COLOR_RGB2GRAY)
    result = cv2.matchTemplate(screenshot_gray, template, cv2.TM_CCOEFF_NORMED)
    _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)

    if max_val < confidence:
        return None

    template_h, template_w = template.shape
    abs_x1 = int(max_loc[0] + offset_x)
    abs_y1 = int(max_loc[1] + offset_y)
    abs_x2 = abs_x1 + int(template_w)
    abs_y2 = abs_y1 + int(template_h)
    center_x = abs_x1 + template_w // 2
    center_y = abs_y1 + template_h // 2

    return {
        "template": template_name,
        "label": template_name.replace(".png", ""),
        "score": float(max_val),
        "center": (center_x, center_y),
        "bbox": (abs_x1, abs_y1, abs_x2, abs_y2),
    }


def detect_template_bboxes(
    template_name: str,
    confidence: float,
    search_region: Optional[Tuple[int, int, int, int]] = None,
) -> List[Dict[str, object]]:
    """Return all distinct template matches above threshold."""
    template = _load_template_gray(template_name)
    if template is None:
        return []

    if search_region is not None:
        x1, y1, x2, y2 = search_region
        screenshot = _vision.safe_screenshot(region=(x1, y1, x2 - x1, y2 - y1))
        offset_x, offset_y = x1, y1
    else:
        screenshot = _vision.safe_screenshot()
        offset_x, offset_y = 0, 0

    screenshot_np = np.array(screenshot)
    screenshot_gray = cv2.cvtColor(screenshot_np, cv2.COLOR_RGB2GRAY)
    result = cv2.matchTemplate(screenshot_gray, template, cv2.TM_CCOEFF_NORMED)

    template_h, template_w = template.shape
    ys, xs = np.where(result >= confidence)
    if len(xs) == 0:
        return []

    candidates: List[Dict[str, object]] = []
    for x, y in zip(xs.tolist(), ys.tolist()):
        score = float(result[y, x])
        abs_x1 = int(x + offset_x)
        abs_y1 = int(y + offset_y)
        abs_x2 = abs_x1 + int(template_w)
        abs_y2 = abs_y1 + int(template_h)
        center_x = abs_x1 + template_w // 2
        center_y = abs_y1 + template_h // 2
        candidates.append(
            {
                "template": template_name,
                "label": template_name.replace(".png", ""),
                "score": score,
                "center": (center_x, center_y),
                "bbox": (abs_x1, abs_y1, abs_x2, abs_y2),
            }
        )

    candidates.sort(key=lambda item: float(item["score"]), reverse=True)

    deduped: List[Dict[str, object]] = []
    min_sep = max(14, int(min(template_w, template_h) * 0.5))
    for cand in candidates:
        cx, cy = cand["center"]  # type: ignore[index]
        if any(
            ((cx - ex) ** 2 + (cy - ey) ** 2) ** 0.5 < min_sep
            for ex, ey in (d["center"] for d in deduped)
        ):
            continue
        deduped.append(cand)

    return deduped


def nearest_left_grid_point(anchor: GridCoord, grid_coords: List[GridCoord]) -> Optional[GridCoord]:
    ax, ay = anchor
    left_candidates = [coord for coord in grid_coords if coord[0] < ax]
    if not left_candidates:
        return None
    return min(left_candidates, key=lambda c: ((ax - c[0]) ** 2 + (ay - c[1]) ** 2))


def detect_builder_side_protected_slots() -> Tuple[List[GridCoord], List[Dict[str, object]]]:
    """
    Detect builder-side markers and map each to nearest grid point on its left.
    Returns (protected_slots, overlay_detections_for_bbside).
    """
    markers = detect_template_bboxes(BB_SIDE_TEMPLATE, BB_SIDE_CONFIDENCE)
    if not markers:
        return [], []

    overlays: List[Dict[str, object]] = []
    protected_set: set[GridCoord] = set()

    for marker in markers:
        overlays.append(
            {
                "bbox": marker["bbox"],
                "label": "bbside",
                "score": float(marker["score"]),
                "shape": "rect",
            }
        )

        marker_center = marker["center"]  # type: ignore[index]
        protected_slot = nearest_left_grid_point(marker_center, GRID_COORDS)
        if protected_slot is not None:
            protected_set.add(protected_slot)

    for slot in sorted(protected_set):
        overlays.append(
            {
                "shape": "circle",
                "center": slot,
                "radius": 11,
                "label": "builder challenge",
                "score": 1.0,
            }
        )

    return list(protected_set), overlays


def detect_valid_challenges(
    challenge_templates: List[str],
    confidence: float,
    challenge_region: Tuple[int, int, int, int],
) -> List[Dict[str, object]]:
    """Return all valid challenge detections (all instances) for overlay/filtering."""

    detections: List[Dict[str, object]] = []

    for template_name in challenge_templates:
        matches = detect_template_bboxes(template_name, confidence, search_region=challenge_region)
        if not matches:
            continue
        for match in matches:
            detections.append(
                {
                    "template": template_name,
                    "label": template_name.replace("clan_games_challenge_", "").replace(".png", ""),
                    "score": float(match["score"]),
                    "center": match["center"],
                    "bbox": match["bbox"],
                }
            )

    return detections


def coord_inside_any_bbox(coord: GridCoord, detections: List[Dict[str, object]]) -> bool:
    x, y = coord
    for det in detections:
        x1, y1, x2, y2 = det["bbox"]  # type: ignore[index]
        if x1 <= x <= x2 and y1 <= y <= y2:
            return True
    return False


def click_and_wait(x: int, y: int, action_desc: str = "") -> None:
    AC.click_with_jitter(x, y)
    AC.random_delay()
    if action_desc:
        AC.log(f"Cycler: Waiting 1 second after {action_desc}")
    time.sleep(1.0)


def is_active_challenge_pixel_yellow(
    pixel: Tuple[int, int] = (890, 459),
    target_yellow: Tuple[int, int, int] = (245, 215, 80),
    tolerance: float = 90.0,
) -> bool:
    """Return True when the active-challenge indicator pixel is close to yellow."""
    x, y = pixel
    try:
        shot = _vision.safe_screenshot(region=(x, y, 1, 1))
        rgb = shot.getpixel((0, 0))
        if isinstance(rgb, tuple) and len(rgb) >= 3:
            r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
        else:
            AC.log(f"Cycler: Unexpected pixel format at {pixel}: {rgb}")
            return False

        tr, tg, tb = target_yellow
        distance = ((r - tr) ** 2 + (g - tg) ** 2 + (b - tb) ** 2) ** 0.5
        AC.log(f"Cycler: Active challenge pixel RGB=({r},{g},{b}), yellow distance={distance:.1f}")
        return distance <= tolerance
    except Exception as exc:
        AC.log(f"Cycler: Failed active-challenge pixel check at {pixel}: {exc}")
        return False


def ensure_approved_account_with_fender_handling(max_attempts: int = 100) -> bool:
    """
    Verify approved account name, with special handling for OCR result 'Fender'.

    If 'Fender' is detected, search for return_home.png, click it when found,
    then restart account-name searching.
    """
    for attempt in range(1, max_attempts + 1):
        name = AC.read_account_name()
        name_norm = (name or "").strip().lower()

        if name_norm in AC.APPROVED_ACCOUNTS:
            AC.current_account_name = name
            AC.log(f"Approved account detected: {name}")
            return True

        if name_norm == "fender":
            AC.log("Cycler: OCR found 'Fender' - attempting return-home recovery")
            home_attempt = 0
            while home_attempt < 30:
                home_attempt += 1
                home_coords = AC.find_template("return_home.png")
                if home_coords:
                    AC.log(
                        f"Cycler: Found 'return_home.png' at {home_coords} "
                        f"(attempt {home_attempt}/30) - clicking"
                    )
                    AC.click_with_jitter(*home_coords)
                    AC.random_delay()
                    time.sleep(1.0)
                    break
                AC.log(f"Cycler: 'return_home.png' not found (attempt {home_attempt}/30)")
                time.sleep(1.0)
            else:
                AC.log("Cycler: return_home.png not found after 30 attempts — giving up on Fender recovery")

            AC.log("Cycler: Return-home click complete - restarting account name search")
            time.sleep(1.0)
            continue

        AC.log(f"Cycler: Account name attempt {attempt}/{max_attempts} failed (got '{name}')")
        AC.scroll_random(AC.WHEEL_DELTA * 3)
        time.sleep(0.5)

    AC.log("Cycler: Could not verify approved account after retries.")
    return False


def open_clan_games_stand() -> Tuple[bool, bool]:
    """Reproduce stand drag/find/click behavior from Autoclash Clan Games flow.

    Returns:
        (opened_ok, cooldown_detected)
    """
    stand_template = AC.CONFIG.get("clan_games_stand_template", "clan_games_stand.png")
    stand_confidence = float(AC.CONFIG.get("clan_games_stand_confidence", AC.CONFIG["confidence_threshold"]))
    stand_retry_attempts = int(AC.CONFIG.get("clan_games_stand_retry_attempts", 10))
    stand_retry_delay = float(AC.CONFIG.get("clan_games_stand_retry_delay", 1.0))

    AC.log("Cycler: Dragging map twice before searching for Clan Games stand")
    for drag_num in range(1, 3):
        AC.log(f"Cycler: Dragging map ({drag_num}/2) from (733,291) to (1177,958)")
        pyautogui.moveTo(733, 291, duration=0.1)
        pyautogui.dragTo(1177, 958, duration=0.4, button="left")
        time.sleep(0.2)

    stand_coords = None
    for attempt in range(1, stand_retry_attempts + 1):
        AC.log(f"Cycler: Searching for stand '{stand_template}' (attempt {attempt}/{stand_retry_attempts})")
        stand_coords = AC.find_template(stand_template, confidence=stand_confidence)
        if stand_coords:
            AC.log(f"Cycler: Found stand at {stand_coords}, clicking")
            click_and_wait(*stand_coords, action_desc="stand click")
            AC.log("Cycler: Waiting 2 seconds for challenges screen to load")
            time.sleep(2.0)
            break
        if attempt < stand_retry_attempts:
            time.sleep(stand_retry_delay)

    if not stand_coords:
        AC.log("Cycler: Stand not found after retries")
        return False, False

    cooldown_template = AC.CONFIG.get("clan_games_cooldown_template", "clan_games_cooldown.png")
    cooldown_coords = AC.find_template(cooldown_template)
    if cooldown_coords:
        AC.log(f"Cycler: Cooldown detected at {cooldown_coords}, exiting menu")
        click_and_wait(1704, 79, action_desc="menu exit click (cooldown)")
        return False, True

    if is_active_challenge_pixel_yellow((890, 459)):
        AC.log("Cycler: Active challenge indicator detected at (890,459) - exiting menu and continuing")
        click_and_wait(1704, 79, action_desc="menu exit click (active challenge)")
        return False, True

    return True, False


def trash_challenge_at_slot(slot_coord: GridCoord, start_template: str, overlay: Optional[OverlayWindow] = None) -> bool:
    """
    Trash/start sequence based on existing flow:
    - click challenge slot
    - find start button
    - click start, wait 1 sec, click start again
    """
    AC.log(f"Cycler: Selecting slot at {slot_coord}")
    AC.click_with_jitter(*slot_coord)

    # Clear overlay immediately at click time to avoid interfering with
    # start-button template matching.
    if overlay is not None:
        overlay.clear()

    AC.random_delay()
    AC.log("Cycler: Waiting 1 second after slot selection")
    time.sleep(1.0)

    start_coords = AC.find_template(start_template)
    if not start_coords:
        AC.log("Cycler: Start button not found after slot click")
        return False

    AC.log(f"Cycler: Start button found at {start_coords}; performing double-click sequence")
    AC.click_with_jitter(*start_coords)
    AC.random_delay()
    time.sleep(1.0)
    AC.click_with_jitter(*start_coords)
    AC.random_delay()
    AC.log("Cycler: Clicking confirmation/okay at (1120, 667)")
    AC.click_with_jitter(1120, 667)
    AC.random_delay()
    time.sleep(1.5)
    return True


def pick_invalid_slots(detections: List[Dict[str, object]], grid_coords: List[GridCoord]) -> List[GridCoord]:
    return [coord for coord in grid_coords if not coord_inside_any_bbox(coord, detections)]


def run_single_account_cycle(overlay: OverlayWindow, pause_after_overlay: bool) -> Tuple[Optional[str], bool, bool, bool]:
    """Execute challenge cycling on current account.

    Returns:
        (ingame_name, trashed_any, cooldown_detected, stop_all)
    """
    AC.log("Cycler: Verifying approved account name via OCR")
    if not ensure_approved_account_with_fender_handling():
        AC.log("Cycler: Account verification failed")
        return None, False, False, False

    current_ingame = _normalize_text(AC.current_account_name or "")
    if current_ingame:
        AC.log(f"Cycler: Running cycle on account '{current_ingame}'")

    AC.log("Cycler: Account verified, scrolling down 5 times")
    AC.scroll_down_5_times(AC.WHEEL_DELTA * 3)

    stand_opened, cooldown_detected = open_clan_games_stand()
    if not stand_opened:
        AC.log("Cycler: Could not open Clan Games stand (or cooldown active)")
        return current_ingame or None, False, cooldown_detected, False

    challenge_region = AC.CONFIG.get("clan_games_challenge_region", (700, 200, 1700, 800))
    challenge_confidence = float(AC.CONFIG.get("clan_games_challenge_confidence", AC.CONFIG["confidence_threshold"]))
    start_template = AC.CONFIG.get("clan_games_start_template", "clan_games_start.png")
    challenge_templates = _discover_challenge_templates()

    if not challenge_templates:
        AC.log("Cycler: No clan_games_challenge_*.png templates found")
        click_and_wait(1704, 79, action_desc="menu exit click (no templates)")
        return current_ingame or None, False, False, False

    AC.log(f"Cycler: Loaded {len(challenge_templates)} valid challenge template(s)")
    trashed_any = False
    scrolled_for_second_page = False

    # First page scan
    detections_pass1 = detect_valid_challenges(challenge_templates, challenge_confidence, challenge_region)
    bb_protected_1, bb_overlay_1 = detect_builder_side_protected_slots()
    overlay.show_detections(detections_pass1 + bb_overlay_1, title="Challenge scan")
    pause_if_overlay_enabled(pause_after_overlay, "challenge scan")
    AC.log(f"Cycler: Found {len(detections_pass1)} valid challenge(s)")
    if bb_protected_1:
        AC.log(f"Cycler: Builder-side marker(s) found; protecting slots {sorted(bb_protected_1)}")

    invalid_slots = pick_invalid_slots(detections_pass1, GRID_COORDS)
    if bb_protected_1:
        protected_set_1 = set(bb_protected_1)
        invalid_slots = [coord for coord in invalid_slots if coord not in protected_set_1]
    AC.log(f"Cycler: Invalid slot candidates: {invalid_slots}")

    # If first page has no trash candidates, scroll once and re-check unseen challenges.
    if not invalid_slots:
        AC.log("Cycler: No invalid slots on first page; scrolling once to check remaining challenges")
        overlay.clear()
        scroll_challenge_list_once_down(challenge_region)
        scrolled_for_second_page = True

        AC.log(
            f"Cycler: Re-scanning all {len(challenge_templates)} templates in challenge region {challenge_region}"
        )
        detections_pass1 = detect_valid_challenges(
            challenge_templates,
            challenge_confidence,
            challenge_region,
        )
        bb_protected_1, bb_overlay_1 = detect_builder_side_protected_slots()
        overlay.show_detections(detections_pass1 + bb_overlay_1, title="Challenge scan (after scroll)")
        pause_if_overlay_enabled(pause_after_overlay, "challenge scan after scroll")
        AC.log(f"Cycler: After scroll found {len(detections_pass1)} valid challenge(s)")
        if bb_protected_1:
            AC.log(f"Cycler: After scroll builder marker(s) found; protecting slots {sorted(bb_protected_1)}")

        invalid_slots = pick_invalid_slots(detections_pass1, GRID_COORDS)
        if bb_protected_1:
            protected_set_1 = set(bb_protected_1)
            invalid_slots = [coord for coord in invalid_slots if coord not in protected_set_1]
        AC.log(f"Cycler: After scroll invalid slot candidates: {invalid_slots}")

    if invalid_slots:
        target = random.choice(invalid_slots)
        AC.log(f"Cycler: Chosen invalid slot: {target}")
        if trash_challenge_at_slot(target, start_template, overlay):
            trashed_any = True
    else:
        AC.log("Cycler: No invalid slots found; skipping trash action")
        if scrolled_for_second_page:
            AC.log("Cycler: No trash candidates after scroll check - stopping script (job done)")
            click_and_wait(1704, 79, action_desc="final menu exit click")
            overlay.clear()
            return current_ingame or None, False, False, True

    click_and_wait(1704, 79, action_desc="final menu exit click")
    overlay.clear()
    AC.log("Cycler: Single-account cycle complete")
    return current_ingame or None, trashed_any, False, False


def main() -> None:
    AC.log("=" * 60)
    AC.log("CLAN GAMES CYCLER START")
    AC.log("=" * 60)

    overlay = OverlayWindow()
    overlay.start()

    validate_selection = ask_validate_account_choice_mode()
    pause_after_overlay = ask_pause_after_overlay_mode()

    last_trash_by_ingame: Dict[str, float] = {}

    try:
        while True:
            current_ingame, trashed_any, cooldown_detected, stop_all = run_single_account_cycle(overlay, pause_after_overlay)

            if stop_all:
                AC.log("Cycler: Stop condition reached - exiting main loop")
                break

            if current_ingame and cooldown_detected:
                _set_min_remaining_cooldown(
                    last_trash_by_ingame,
                    current_ingame,
                    COOLDOWN_DETECTED_PENALTY_SECONDS,
                )
                AC.log(
                    f"Cycler: Cooldown detected in-game for '{current_ingame}' -> "
                    f"set at least {_format_remaining(COOLDOWN_DETECTED_PENALTY_SECONDS)} remaining"
                )

            if current_ingame and trashed_any:
                last_trash_by_ingame[current_ingame] = time.time()
                AC.log(
                    f"Cycler: Cooldown started for '{current_ingame}' "
                    f"({COOLDOWN_SECONDS} seconds)"
                )

            if not choose_and_switch_account(last_trash_by_ingame, overlay, validate_selection, pause_after_overlay):
                AC.log("Cycler: Account switch failed; waiting 5 seconds then retrying")
                time.sleep(5.0)
                continue

            AC.log("Cycler: Account switched; starting next cycle")
            time.sleep(2.0)
    except KeyboardInterrupt:
        AC.log("Cycler: Stopped by user (Ctrl+C)")
    except Exception as exc:
        AC.log(f"Cycler: Fatal error: {exc}")
        import traceback
        traceback.print_exc()
    finally:
        overlay.stop()
        time.sleep(0.2)
        AC.log("Cycler: Exiting")


if __name__ == "__main__":
    main()
