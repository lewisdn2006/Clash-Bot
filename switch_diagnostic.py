import os, re, time, datetime, subprocess, tempfile
import cv2
import numpy as np
import pyautogui
import vision as _vision
import Autoclash

SETTINGS_MENU_COORD       = (1852, 841)
ACCOUNT_SWITCH_MENU_COORD = (1245, 244)
ACCOUNT_SWITCH_BOX        = (1565, 450, 1917, 1080)

INGAME_TO_SWITCH_NAME = {
    "lewis":          "CarefreeZenLewis",
    "williamleeming": "HomelessLewis2",
    "steve":          "BrokenSiennaa",
    "lewis8":         "FreshLewis8",
    "lewis7":         "CurlyLewis7",
    "lewis6":         "WelcomedLewis6",
    "lewis5":         "SincereLewis5",
    "lewis4":         "IconLewis4",
    "lewis3":         "TrustworthyLewis3",
    "djbillgates22":  "DJBillGates22",
    "djbillgates23":  "DJBillGates123",
    "djbillgates24":  "DJBillGates24",
    "djbillgates25":  "DJBillGates25",
    "djbillgates26":  "DJBillGates26",
    "djbillgates27":  "DJBillGates27",
    "djbillgates28":  "DJBillGates28",
    "djbillgates29":  "DJBillGates29",
    "djbillgates30":  "DJBillGates30",
    "djbillgates31":  "DJBillGates31",
    "djbillgates32":  "DJBillGates32",
    "djbillgates33":  "DJBillGates33",
    "djbillgates34":  "DJBillGates34",
    "djbillgates35":  "DJBillGates35",
    "djbillgates38":  "DJBillGates38",
    "djbillgates39":  "DJBillGates39",
    "djbillgates40":  "DJBillGates40",
    "djbillgates41":  "DJBillGates41",
}

# ── Logging ──────────────────────────────────────────────────────────────────

LOG_DIR = r"C:\Users\fghgh\Desktop\Clash Bot\switch_diagnostic"
os.makedirs(LOG_DIR, exist_ok=True)
_session_ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
_log_path = os.path.join(LOG_DIR, f"diagnostic_{_session_ts}.txt")
_log_file = open(_log_path, "w", encoding="utf-8")

def log(msg: str):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    _log_file.write(line + "\n")
    _log_file.flush()

# ── Helper functions (verbatim from AutomationWorker.py) ──────────────────────

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

# ── OCR function (verbatim from AutomationWorker.py + save_prefix param) ─────

def _ocr_tsv_records_in_region(region, save_prefix=None) -> list:
    x1, y1, x2, y2 = region
    width, height = x2 - x1, y2 - y1
    screenshot = _vision.safe_screenshot(region=(x1, y1, width, height))

    if save_prefix:
        raw_path = os.path.join(LOG_DIR, f"{save_prefix}_raw.png")
        screenshot.save(raw_path)
        log(f"  [DIAG] Saved raw screenshot: {raw_path}")

    processed = _preprocess_for_ocr(screenshot)

    if save_prefix:
        proc_path = os.path.join(LOG_DIR, f"{save_prefix}_processed.png")
        cv2.imwrite(proc_path, processed)
        log(f"  [DIAG] Saved preprocessed image: {proc_path}")

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

# ── Scroll helper (verbatim from AutomationWorker.py) ────────────────────────

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
    time.sleep(0.5)

# ── Diagnostic scan ───────────────────────────────────────────────────────────

def diagnostic_scan(scan_index: int, candidates: dict) -> dict:
    """Run one OCR scan of the switch box. Logs every row Tesseract sees,
    and for each candidate account shows exactly why it was accepted or rejected."""
    save_prefix = f"scan_{scan_index:03d}"
    log(f"\n--- SCAN {scan_index} ---")

    ocr_rows = _ocr_tsv_records_in_region(ACCOUNT_SWITCH_BOX, save_prefix=save_prefix)
    log(f"  Tesseract returned {len(ocr_rows)} row(s):")
    for row in ocr_rows:
        log(f"    raw='{row['text']}' norm='{row['text_norm']}' conf={row['conf']:.1f} center={row['center']}")

    visible = {}
    for ingame_name, switch_name in candidates.items():
        target_norm = _normalize_text_for_ocr(switch_name)
        best_row = None
        best_score = -1.0

        for row in ocr_rows:
            row_norm = row["text_norm"]
            if len(row_norm) < 4:
                continue
            fragment_match = (row_norm in target_norm and len(row_norm) >= len(target_norm) * 0.8)
            if target_norm in row_norm or fragment_match:
                conf = _normalize_ocr_confidence(float(row["conf"]))
                exact_match = (row_norm == target_norm)
                if exact_match:
                    log(f"  MATCH [{ingame_name}]: '{row['text']}' EXACT — bypassing threshold, conf={conf:.2f}")
                    if conf > best_score:
                        best_row = row
                        best_score = conf
                elif conf < 0.80:
                    log(f"  MATCH [{ingame_name}]: '{row['text']}' REJECTED — conf={conf:.2f} < 0.80")
                else:
                    log(f"  MATCH [{ingame_name}]: '{row['text']}' ACCEPTED — conf={conf:.2f}")
                    if conf > best_score:
                        best_row = row
                        best_score = conf

        if best_row is not None:
            log(f"  >>> FOUND '{ingame_name}' ({switch_name}) — OCR='{best_row['text']}' conf={best_score:.2f} center={best_row['center']}")
            visible[ingame_name] = {
                "switch_name": switch_name,
                "center": best_row["center"],
                "bbox": best_row["bbox"],
                "ocr_text": best_row["text"],
                "ocr_conf": best_score,
            }
        else:
            log(f"  >>> NOT FOUND '{ingame_name}' ({switch_name}) — target_norm='{target_norm}'")

    return visible

# ── Main ──────────────────────────────────────────────────────────────────────

def run_diagnostic():
    log("=" * 60)
    log("SWITCH DIAGNOSTIC")
    log(f"Session: {_session_ts}")
    log(f"ACCOUNT_SWITCH_BOX = {ACCOUNT_SWITCH_BOX}")
    log(f"Accounts to find: {list(INGAME_TO_SWITCH_NAME.keys())}")
    log("=" * 60)

    log("Starting in 3 seconds — switch to the game window now...")
    time.sleep(3)

    log("Pressing Escape x2 to close any menus...")
    pyautogui.press('escape')
    time.sleep(0.5)
    pyautogui.press('escape')
    time.sleep(0.5)

    log("Checking for settings.png on screen...")
    coords = Autoclash.find_template("settings.png")
    if coords:
        log(f"settings.png found at {coords} — good")
    else:
        log("WARNING: settings.png NOT found — are you on the home village screen?")

    log(f"Clicking settings icon at {SETTINGS_MENU_COORD}...")
    Autoclash.click_with_jitter(*SETTINGS_MENU_COORD)
    time.sleep(3)
    log(f"Clicking account switch button at {ACCOUNT_SWITCH_MENU_COORD}...")
    Autoclash.click_with_jitter(*ACCOUNT_SWITCH_MENU_COORD)
    time.sleep(3)
    log("Account switch menu should now be open")

    found_accounts = {}
    MAX_SCANS = 50
    remaining = dict(INGAME_TO_SWITCH_NAME)

    for scan_idx in range(MAX_SCANS + 1):
        if not remaining:
            log("All accounts found — stopping early")
            break

        visible = diagnostic_scan(scan_idx, remaining)

        for name, data in visible.items():
            found_accounts[name] = data
            del remaining[name]
            log(f"  [FOUND] Removing '{name}' from search — {len(remaining)} left")

        if remaining and scan_idx < MAX_SCANS:
            log(f"  Scrolling down... ({len(remaining)} accounts still not found)")
            _scroll_switch_box_once("down")

    log("\nClosing switch menu (Escape)...")
    pyautogui.press('escape')
    time.sleep(0.5)

    log("\n" + "=" * 60)
    log("SUMMARY")
    log("=" * 60)
    log(f"Found {len(found_accounts)}/{len(INGAME_TO_SWITCH_NAME)} accounts:")
    for name, data in found_accounts.items():
        log(f"  OK  '{name}' — OCR='{data['ocr_text']}' conf={data['ocr_conf']:.2f} center={data['center']}")

    not_found = [n for n in INGAME_TO_SWITCH_NAME if n not in found_accounts]
    if not_found:
        log(f"NOT FOUND ({len(not_found)}):")
        for name in not_found:
            log(f"  MISS '{name}' ({INGAME_TO_SWITCH_NAME[name]})")
    else:
        log("All accounts found successfully!")

    log(f"\nLog saved to: {_log_path}")
    log(f"Screenshots saved to: {LOG_DIR}")
    _log_file.close()


if __name__ == "__main__":
    try:
        run_diagnostic()
    except KeyboardInterrupt:
        log("\nInterrupted by user")
        _log_file.close()
    except Exception as e:
        log(f"\nFATAL ERROR: {e}")
        import traceback
        log(traceback.format_exc())
        _log_file.close()
