#!/usr/bin/env python3
"""
Clan Scout
==========
Searches for Capital Hall 10 clans that are open to anyone and bookmarks
them, using the lewis3 account.

Entry point for ClanScouterWorker in AutomationWorker.py:
    run_scouter(stop_check, status_emit) -> int   (returns bookmark count)
"""

from __future__ import annotations

import ctypes
import os
import queue
import random
import re
import subprocess
import tempfile
import threading
import time
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

# ---------------------------------------------------------------------------
# Overlay
# ---------------------------------------------------------------------------

class OverlayWindow:
    """Transparent topmost overlay that highlights regions being scanned."""

    def __init__(self) -> None:
        self.enabled = HAS_TK
        self._queue: "queue.Queue[Tuple[str, object]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if not self.enabled:
            AC.log("Scout Overlay: tkinter unavailable, overlay disabled")
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self.enabled:
            return
        self._queue.put(("stop", None))

    def show_regions(self, regions: List[Dict], title: str = "") -> None:
        if not self.enabled:
            return
        self._queue.put(("draw", (regions, title)))

    def clear(self) -> None:
        if not self.enabled:
            return
        self._queue.put(("clear", None))

    def _run(self) -> None:
        root = tk.Tk()
        root.title("Clan Scout Overlay")
        root.overrideredirect(True)
        root.attributes("-topmost", True)

        transparent_color = "#ff00ff"
        root.configure(bg=transparent_color)
        try:
            root.attributes("-transparentcolor", transparent_color)
        except Exception:
            root.attributes("-alpha", 0.35)

        screen_w, screen_h = pyautogui.size()
        root.geometry(f"{screen_w}x{screen_h}+0+0")

        canvas = tk.Canvas(
            root, width=screen_w, height=screen_h,
            bg=transparent_color, highlightthickness=0,
        )
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
                        regions, title = payload  # type: ignore[misc]
                        if title:
                            canvas.create_text(
                                12, 12,
                                text=title,
                                anchor="nw",
                                fill="#ffff00",
                                font=("Arial", 14, "bold"),
                            )
                        for reg in regions:
                            x1, y1, x2, y2 = reg["bbox"]
                            color = reg.get("color", "#00ff00")
                            label = reg.get("label", "")
                            canvas.create_rectangle(x1, y1, x2, y2, outline=color, width=2)
                            if label:
                                lw = len(label) * 8 + 8
                                canvas.create_rectangle(
                                    x1, y1 - 20, x1 + lw, y1,
                                    fill="#001a00", outline=color,
                                )
                                canvas.create_text(
                                    x1 + 4, y1 - 10,
                                    text=label,
                                    anchor="w",
                                    fill=color,
                                    font=("Arial", 10, "bold"),
                                )
            except queue.Empty:
                pass
            root.after(60, process_queue)

        root.after(60, process_queue)
        root.mainloop()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLANS_BOX: Tuple[int, int, int, int] = (223, 451, 1310, 1036)
CLANS_BOX_CENTER: Tuple[int, int] = (
    (223 + 1310) // 2,   # 766
    (451 + 1036) // 2,   # 743
)

CAPITAL_HALL_REGION: Tuple[int, int, int, int] = (1044, 542, 1132, 582)

BOOKMARK_TEMPLATE = "bookmark_clan.png"

MAX_BOOKMARKS = 100
MAX_RETRIES = 5
CONSECUTIVE_SAME_THRESHOLD = 10
POSITION_Y_TOLERANCE = 10  # pixels — if Y shifts by less than this, treat as "same"

# 4-click sequence to open the clan search list (1 s pause between each)
OPEN_SEARCH_SEQUENCE: List[Tuple[int, int]] = [
    (67, 58),
    (1166, 80),
    (955, 213),
    (1077, 354),
]

SETTINGS_MENU_COORD: Tuple[int, int] = (1852, 841)
ACCOUNT_SWITCH_MENU_COORD: Tuple[int, int] = (1245, 244)
ACCOUNT_SWITCH_BOX: Tuple[int, int, int, int] = (1321, 496, 1917, 1080)

ACCOUNT_NAME_MIN_CONFIDENCE = 0.75
LEWIS3_SWITCH_NAME = "TrustworthyLewis3"

EXIT_CLAN_SEARCH_COORD: Tuple[int, int] = (91, 362)
EXIT_CLAN_SCREEN_COORD: Tuple[int, int] = (278, 91)
CLAN_STATS_COORD: Tuple[int, int] = (300, 569)

# ---------------------------------------------------------------------------
# OCR helpers
# ---------------------------------------------------------------------------

def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "", value or "").strip().lower()


def _normalize_conf(raw: float) -> float:
    if raw <= 1.0:
        return max(0.0, min(1.0, raw))
    return max(0.0, min(1.0, raw / 100.0))


def _preprocess_for_ocr(pil_image) -> np.ndarray:
    img_np = np.array(pil_image)
    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
    up = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    blur = cv2.GaussianBlur(up, (3, 3), 0)
    _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return thresh


def _ocr_region(region: Tuple[int, int, int, int]) -> List[Dict]:
    """Screenshot a screen region, run Tesseract OCR, return word records."""
    x1, y1, x2, y2 = region
    w, h = x2 - x1, y2 - y1
    screenshot = _vision.safe_screenshot(region=(x1, y1, w, h))
    processed = _preprocess_for_ocr(screenshot)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        image_path = tmp.name
        cv2.imwrite(image_path, processed)

    records: List[Dict] = []
    try:
        result = subprocess.run(
            [AC.TESSERACT_PATH, image_path, "stdout", "tsv"],
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
        idx = {name: i for i, name in enumerate(header)}
        required = ["left", "top", "width", "height", "conf", "text"]
        if any(k not in idx for k in required):
            return []

        for line in lines[1:]:
            cols = line.split("\t")
            if len(cols) < len(header):
                continue

            text = cols[idx["text"]].strip()
            if not text:
                continue
            text_norm = _normalize_text(text)
            if not text_norm:
                continue

            try:
                conf = float(cols[idx["conf"]])
            except Exception:
                conf = -1.0
            if conf < 0:
                continue

            left = int(cols[idx["left"]])
            top = int(cols[idx["top"]])
            rw = int(cols[idx["width"]])
            rh = int(cols[idx["height"]])

            ax1 = x1 + left // 2
            ay1 = y1 + top // 2
            ax2 = ax1 + max(1, rw // 2)
            ay2 = ay1 + max(1, rh // 2)
            cx = (ax1 + ax2) // 2
            cy = (ay1 + ay2) // 2

            records.append({
                "text": text,
                "text_norm": text_norm,
                "conf": conf,
                "bbox": (ax1, ay1, ax2, ay2),
                "center": (cx, cy),
            })
    except Exception:
        return []
    finally:
        try:
            os.remove(image_path)
        except Exception:
            pass

    return records


def _find_phrase_in_region(
    region: Tuple[int, int, int, int],
    phrase_norm: str,
) -> Optional[Tuple[int, int]]:
    """
    OCR the region, group words into lines, and return the center of the
    first (topmost) line whose joined-normalised text contains phrase_norm.
    Returns None if not found.
    """
    records = _ocr_region(region)
    if not records:
        return None

    sorted_recs = sorted(records, key=lambda r: r["center"][1])
    lines: List[List[Dict]] = []
    for rec in sorted_recs:
        placed = False
        for line in lines:
            if abs(rec["center"][1] - line[0]["center"][1]) < 20:
                line.append(rec)
                placed = True
                break
        if not placed:
            lines.append([rec])

    for line in sorted(lines, key=lambda ln: ln[0]["center"][1]):
        line_text = "".join(r["text_norm"] for r in line)
        if phrase_norm in line_text:
            cx = sum(r["center"][0] for r in line) // len(line)
            cy = sum(r["center"][1] for r in line) // len(line)
            return (cx, cy)

    return None


def _text_present_in_region(
    region: Tuple[int, int, int, int],
    target_norm: str,
) -> bool:
    """Return True if any OCR token from the region contains target_norm."""
    records = _ocr_region(region)
    return any(target_norm in r["text_norm"] for r in records)


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

def _with_retry(
    action,
    description: str,
    max_retries: int = MAX_RETRIES,
    delay: float = 1.0,
):
    """
    Call action(), retrying up to max_retries times on exception.
    Raises RuntimeError if all attempts fail.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            return action()
        except Exception as exc:
            last_exc = exc
            AC.log(f"Scout: '{description}' failed (attempt {attempt}/{max_retries}): {exc}")
            if attempt < max_retries:
                time.sleep(delay)
    raise RuntimeError(
        f"Scout: '{description}' failed after {max_retries} attempts"
    ) from last_exc


# ---------------------------------------------------------------------------
# Account switch
# ---------------------------------------------------------------------------

def _open_account_switch_menu() -> None:
    AC.click_with_jitter(*SETTINGS_MENU_COORD)
    AC.random_delay()
    time.sleep(1.0)
    AC.click_with_jitter(*ACCOUNT_SWITCH_MENU_COORD)
    AC.random_delay()
    time.sleep(1.5)


def switch_to_lewis3() -> bool:
    """
    Open the account switcher and click lewis3 (TrustworthyLewis3).
    Returns True on success, False if the account could not be found.
    """
    target_norm = _normalize_text(LEWIS3_SWITCH_NAME)
    _open_account_switch_menu()

    x1, y1, x2, y2 = ACCOUNT_SWITCH_BOX
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

    # Scroll to top first so we always start from the beginning of the list
    pyautogui.moveTo(cx, cy, duration=0.1)
    for _ in range(10):
        try:
            AC._send_wheel(abs(int(AC.WHEEL_DELTA)))
        except Exception:
            pyautogui.scroll(3)
        time.sleep(0.15)

    for _scan in range(25):
        records = _ocr_region(ACCOUNT_SWITCH_BOX)
        best_center = None
        best_score = -1.0

        for rec in records:
            rnorm = rec["text_norm"]
            if target_norm in rnorm or rnorm in target_norm:
                conf = _normalize_conf(float(rec["conf"]))
                if conf >= ACCOUNT_NAME_MIN_CONFIDENCE and conf > best_score:
                    best_center = rec["center"]
                    best_score = conf

        if best_center:
            AC.log(f"Scout: Clicking {LEWIS3_SWITCH_NAME} at {best_center}")
            AC.click_with_jitter(*best_center)
            AC.random_delay()
            time.sleep(4.0)
            load_ok = AC.find_template("account_load_okay.png")
            if load_ok:
                AC.click_with_jitter(*load_ok)
                AC.random_delay()
                time.sleep(2.0)
            return True

        # Not visible yet — scroll down
        pyautogui.moveTo(cx, cy, duration=0.1)
        try:
            AC._send_wheel(-abs(int(AC.WHEEL_DELTA)))
        except Exception:
            pyautogui.scroll(-3)
        time.sleep(0.4)

    AC.log("Scout: Could not find TrustworthyLewis3 in account switcher")
    return False


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

def _open_clan_search(stop_check) -> None:
    """Perform the clan search opening sequence.

    Clicks through OPEN_SEARCH_SEQUENCE, then before the final search button
    click: clicks the search input field (300 px left of the search button),
    types a random letter to populate results, then clicks search.
    """
    penultimate = len(OPEN_SEARCH_SEQUENCE) - 2
    final_x, final_y = OPEN_SEARCH_SEQUENCE[-1]

    for i, (x, y) in enumerate(OPEN_SEARCH_SEQUENCE):
        if stop_check():
            return
        if i == penultimate:
            # Click the search clans tab, then populate the search field
            AC.click_with_jitter(x, y)
            time.sleep(1.0)
            if stop_check():
                return
            # Click the search input field (300 px left of the search button)
            AC.click_with_jitter(final_x - 300, final_y)
            # Wait for the Android text field to register focus before typing
            time.sleep(0.8)
            letter = random.choice("abcdefghijklmnopqrstuvwxyz")
            # Send the letter as a direct WM_CHAR message to the game window.
            # This bypasses the SendInput injection path and hits the window's
            # message queue directly, which Google Play Games forwards to Android.
            _WM_CHAR = 0x0102
            _u32 = ctypes.windll.user32
            hwnd = _u32.GetForegroundWindow()
            if hwnd:
                _u32.PostMessageW(hwnd, _WM_CHAR, ord(letter), 1)
            time.sleep(0.3)
        elif i < len(OPEN_SEARCH_SEQUENCE) - 1:
            AC.click_with_jitter(x, y)
            time.sleep(1.0)
        else:
            # Final click — the search button
            AC.click_with_jitter(x, y)

    time.sleep(1.0)  # wait for the list to load
    # Deselect the search bar so scrolling works
    AC.click_with_jitter(222, 634)
    time.sleep(0.3)


def _exit_clan_search() -> None:
    AC.click_with_jitter(*EXIT_CLAN_SEARCH_COORD)
    time.sleep(1.0)


def _scroll_clans_list_down() -> None:
    cx, cy = CLANS_BOX_CENTER
    pyautogui.moveTo(cx, cy, duration=0.1)
    try:
        AC._send_wheel(-abs(int(AC.WHEEL_DELTA)))
    except Exception:
        pyautogui.scroll(-3)
    time.sleep(0.5)


# ---------------------------------------------------------------------------
# Bookmark
# ---------------------------------------------------------------------------

def _try_bookmark() -> bool:
    """
    Find and click bookmark_clan.png.
    Returns True if clicked (new bookmark), False if the image was not found
    (which means the clan is already bookmarked).
    """
    coords = AC.find_template(BOOKMARK_TEMPLATE)
    if coords:
        AC.click_with_jitter(*coords)
        AC.random_delay()
        time.sleep(0.5)
        return True
    return False


# ---------------------------------------------------------------------------
# Consecutive-same-position helper
# ---------------------------------------------------------------------------

_SENTINEL = object()


def _positions_match(a, b) -> bool:
    """True if both are None, or both are (x, y) with Y within POSITION_Y_TOLERANCE."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a[1] - b[1]) <= POSITION_Y_TOLERANCE


# ---------------------------------------------------------------------------
# Main scouter loop
# ---------------------------------------------------------------------------

def run_scouter(stop_check, status_emit) -> int:
    """
    Main clan-scouting loop.

    Switches to lewis3, opens the clan search list, scrolls through clans,
    and bookmarks any that have Capital Hall 10 and are open to anyone.
    Resets the list when it appears exhausted (10 consecutive identical
    results), then starts over.  Stops when bookmark_count reaches
    MAX_BOOKMARKS or stop_check() returns True (space key / GUI stop).

    Parameters
    ----------
    stop_check : callable() -> bool
        Returns True the instant the worker should halt.
    status_emit : callable(phase: str, message: str)
        Used to push progress updates to the GUI.

    Returns
    -------
    int
        Total number of bookmarks made this session.
    """
    bookmark_count = 0

    overlay = OverlayWindow()
    overlay.start()

    # ── Switch to lewis3 ────────────────────────────────────────────────────
    status_emit("Setup", "Switching to lewis3…")

    def _do_switch():
        if not switch_to_lewis3():
            raise RuntimeError("Could not find or click lewis3 in account switcher")

    _with_retry(_do_switch, "switch to lewis3")

    if stop_check():
        return bookmark_count

    # ── Outer loop: re-open the clan list each time we hit the bottom ────────
    while not stop_check() and bookmark_count < MAX_BOOKMARKS:

        status_emit("Opening", "Opening clan search menu…")

        def _do_open():
            _open_clan_search(stop_check)

        _with_retry(_do_open, "open clan search")

        if stop_check():
            break

        # ── Inner loop: scan and process clans ───────────────────────────────
        same_count = 0
        last_pos = _SENTINEL  # sentinel = first iteration, no previous result

        while not stop_check() and bookmark_count < MAX_BOOKMARKS:

            status_emit(
                "Scanning",
                f"Searching for 'Anyone Can Join'… "
                f"(bookmarks: {bookmark_count}/{MAX_BOOKMARKS})",
            )

            # --- OCR the clan list for "anyone can join" ---
            overlay.clear()
            try:
                found_pos: Optional[Tuple[int, int]] = _with_retry(
                    lambda: _find_phrase_in_region(CLANS_BOX, "anyonecanjoin"),
                    "OCR clan list",
                )
            except RuntimeError as exc:
                status_emit("Error", str(exc))
                break

            # Show result on overlay after OCR completes (never during screenshot)
            if found_pos is not None:
                overlay.show_regions(
                    [{"bbox": CLANS_BOX, "label": f"Found: {found_pos}", "color": "#00ff00"}],
                    "Clan Scout — found 'Anyone Can Join'",
                )
            else:
                overlay.show_regions(
                    [{"bbox": CLANS_BOX, "label": "Not found — scrolling", "color": "#ff4444"}],
                    "Clan Scout — scanning",
                )

            # --- Track consecutive identical results ---
            if last_pos is _SENTINEL:
                same_count = 1
                last_pos = found_pos
            elif _positions_match(found_pos, last_pos):
                same_count += 1
            else:
                same_count = 1
                last_pos = found_pos

            if same_count >= CONSECUTIVE_SAME_THRESHOLD:
                status_emit(
                    "Reset",
                    f"Same result {CONSECUTIVE_SAME_THRESHOLD} times in a row — "
                    f"list exhausted. Resetting…",
                )
                _exit_clan_search()
                break  # re-enter outer loop which will re-open the list

            # --- Examine and optionally bookmark the clan ---
            if found_pos is not None:
                status_emit("Found", f"'Anyone Can Join' at {found_pos}. Checking clan…")

                try:
                    _with_retry(
                        lambda: AC.click_with_jitter(*found_pos),
                        "click clan listing",
                    )
                except RuntimeError as exc:
                    status_emit("Error", str(exc))
                    break

                time.sleep(1.0)
                if stop_check():
                    break

                try:
                    _with_retry(
                        lambda: AC.click_with_jitter(*CLAN_STATS_COORD),
                        "open clan stats",
                    )
                except RuntimeError as exc:
                    status_emit("Error", str(exc))
                    break

                time.sleep(1.0)
                if stop_check():
                    break

                # Check for Capital Hall level 10 via template match
                overlay.clear()  # clear before screenshot
                status_emit("Checking", "Scanning for capital_hall_10.png…")
                cap10_pos = AC.find_template("capital_hall_10.png", confidence=0.99)
                AC.log(f"Scout: capital_hall_10.png match: {cap10_pos}")

                if cap10_pos:
                    status_emit("Capital Hall 10", "Capital Hall 10 found — bookmarking…")
                    bookmarked = _try_bookmark()  # overlay is clear — safe for find_template screenshot
                    if bookmarked:
                        bookmark_count += 1
                        status_emit(
                            "Bookmarked",
                            f"Bookmarked! Total: {bookmark_count}/{MAX_BOOKMARKS}",
                        )
                    else:
                        status_emit("Skip", "Clan already bookmarked — moving on")
                    # Show result after all screenshots are done
                    cx, cy = cap10_pos
                    overlay.show_regions(
                        [{"bbox": (cx - 40, cy - 40, cx + 40, cy + 40), "label": "Cap Hall 10!", "color": "#00ff00"}],
                        "Clan Scout — Capital Hall 10 found",
                    )
                else:
                    status_emit("Skip", "Capital Hall 10 not found — skipping")
                    overlay.show_regions(
                        [{"bbox": (10, 40, 260, 70), "label": "No Cap Hall 10 here", "color": "#ff4444"}],
                        "Clan Scout — not Capital Hall 10",
                    )

                # Exit the clan stats screen
                try:
                    _with_retry(
                        lambda: AC.click_with_jitter(*EXIT_CLAN_SCREEN_COORD),
                        "exit clan screen",
                    )
                except RuntimeError as exc:
                    status_emit("Error", str(exc))
                    break

                time.sleep(0.5)

            else:
                status_emit("Scanning", "No 'Anyone Can Join' visible — scrolling down…")

            # Scroll the clan list down regardless of whether we found a clan
            _scroll_clans_list_down()
            time.sleep(2.0)  # allow the list to finish scrolling before next OCR scan

    overlay.stop()
    status_emit("Done", f"Clan Scouter finished. Total bookmarks: {bookmark_count}")
    return bookmark_count
