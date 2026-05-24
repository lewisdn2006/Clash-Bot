# Claude Code Prompt — Capital Raid Tweaks (5 changes)

## Context

Two files need editing: `capitalraider.py` and `AutomationWorker.py`.
Read both files in full before making any changes.

---

## Change 1 — Fix Ctrl+D in ClanCapitalWorker (`AutomationWorker.py`)

**Root cause:** In `ClanCapitalWorker.run()`, the space hotkey and Ctrl+D hotkey are in
the same `try` block. If `add_hotkey("space")` fails (e.g. "space" was already registered
from a previous session that didn't clean up), the entire block is swallowed and Ctrl+D
is never registered. Every other worker in the file separates them.

**Fix:** Split the Ctrl+D registration out of the shared keyboard block into its own
independent try block, using the `_ctrl_d_registered` / `_kb_disconnect` pattern that all
other workers now use.

Find the keyboard registration block in `ClanCapitalWorker.run()`. It currently looks like:

```python
_keyboard_registered = False
try:
    import keyboard as _kb
    _kb.add_hotkey("space", self.stop)
    def _on_cap_disconnect():
        log("Ctrl+D pressed — disconnecting Remote Desktop...")
        try:
            import subprocess
            subprocess.Popen(
                [r'C:\Users\fghgh\Desktop\disconnect.bat'],
                shell=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception as e:
            log(f"WARNING: Failed to launch disconnect.bat: {e}")
    _kb.add_hotkey("ctrl+d", _on_cap_disconnect)
    _keyboard_registered = True
    log("ClanCapitalWorker: space-stop and Ctrl+D disconnect enabled")
except Exception:
    log("ClanCapitalWorker: keyboard module unavailable; space-stop disabled")
```

Replace it with:

```python
_keyboard_registered = False
try:
    import keyboard as _kb
    _kb.add_hotkey("space", self.stop)
    _keyboard_registered = True
    log("ClanCapitalWorker: space-stop enabled")
except Exception:
    log("ClanCapitalWorker: keyboard module unavailable; space-stop disabled")

_ctrl_d_registered = False
try:
    import keyboard as _kb_disconnect
    def _on_cap_disconnect():
        log("Ctrl+D pressed — disconnecting Remote Desktop...")
        try:
            import subprocess
            subprocess.Popen(
                [r'C:\Users\fghgh\Desktop\disconnect.bat'],
                shell=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception as _e:
            log(f"WARNING: Failed to launch disconnect.bat: {_e}")
    _kb_disconnect.add_hotkey("ctrl+d", _on_cap_disconnect)
    _ctrl_d_registered = True
    log("ClanCapitalWorker: Ctrl+D disconnect enabled")
except Exception:
    log("ClanCapitalWorker: keyboard module unavailable; Ctrl+D disabled")
```

Then find the `finally` block of `ClanCapitalWorker.run()`. It currently looks like:

```python
finally:
    _set_overlay_callback(None)
    self.overlay_clear.emit()
    if _keyboard_registered:
        try:
            import keyboard as _kb
            _kb.remove_hotkey("space")
        except Exception:
            pass
    bot_reporter.stop()
    self.finished.emit()
```

Replace it with:

```python
finally:
    _set_overlay_callback(None)
    self.overlay_clear.emit()
    if _keyboard_registered:
        try:
            import keyboard as _kb
            _kb.remove_hotkey("space")
        except Exception:
            pass
    if _ctrl_d_registered:
        try:
            import keyboard as _kb_disconnect
            _kb_disconnect.remove_hotkey("ctrl+d")
        except Exception:
            pass
    bot_reporter.stop()
    self.finished.emit()
```

Do not change anything else in `AutomationWorker.py`.

---

## Change 2 — Move DISTRICTS attack coordinates 20 pixels higher (`capitalraider.py`)

Find the `DISTRICTS` list near the top of `capitalraider.py`. It currently reads:

```python
DISTRICTS = [
    ("Goblin Mines",       (1217, 1012)),
    ("Skeleton Park",      ( 870, 1029)),
    ("Golem Quarry",       ( 552,  983)),
    ("Dragon Cliffs",      (1286,  791)),
    ("Builder's Workshop", (1068,  869)),
    ("Balloon Lagoon",     ( 742,  833)),
    ("Wizard Valley",      ( 932,  658)),
    ("Barbarian Camp",     (1146,  586)),
    ("Capital Peak",       ( 917,  380)),
]
```

Replace it with (Y coordinate reduced by 20 on every entry, X unchanged):

```python
DISTRICTS = [
    ("Goblin Mines",       (1217,  992)),
    ("Skeleton Park",      ( 870, 1009)),
    ("Golem Quarry",       ( 552,  963)),
    ("Dragon Cliffs",      (1286,  771)),
    ("Builder's Workshop", (1068,  849)),
    ("Balloon Lagoon",     ( 742,  813)),
    ("Wizard Valley",      ( 932,  638)),
    ("Barbarian Camp",     (1146,  566)),
    ("Capital Peak",       ( 917,  360)),
]
```

Do not change `HOME_DISTRICTS`. Only `DISTRICTS` is affected.

---

## Change 3 — Slow down zoom-out in `run_battle` (`capitalraider.py`)

Find `run_battle`. The zoom-out loop currently reads:

```python
_status(status_fn, "Battle", "Zooming out…")
for i in range(5):
    if _stopped(stop_fn):
        return
    _drag_once(duration=0.35)
    try:
        Autoclash.scroll_down_api(Autoclash.WHEEL_DELTA * 2)
    except Exception:
        pyautogui.scroll(-abs(int(Autoclash.WHEEL_DELTA * 2)))
    time.sleep(0.3)
```

Replace it with (duration doubled, gap between iterations doubled):

```python
_status(status_fn, "Battle", "Zooming out…")
for i in range(5):
    if _stopped(stop_fn):
        return
    _drag_once(duration=0.7)
    try:
        Autoclash.scroll_down_api(Autoclash.WHEEL_DELTA * 2)
    except Exception:
        pyautogui.scroll(-abs(int(Autoclash.WHEEL_DELTA * 2)))
    time.sleep(0.6)
```

Do not change `_drag_once` itself, and do not change the zoom-out in any other function.

---

## Change 4 — Re-select spell button after 20 failed placement clicks (`capitalraider.py`)

Find `place_unit`. The placement loop currently reads:

```python
click_count = 0
while not _stopped(stop_fn):
    x, y = random_point_in_diamond()
    Autoclash.click_with_jitter(x, y)
    click_count += 1
    time.sleep(random.uniform(0.03, 0.07))

    # Check depletion every 3 clicks to avoid hammering screenshots
    if click_count % 3 == 0:
        if is_button_depleted(button_xy):
            _status(status_fn, "Battle", f"Unit at {button_xy} depleted after {click_count} clicks")
            break

time.sleep(0.2)
```

Replace it with:

```python
click_count = 0
while not _stopped(stop_fn):
    x, y = random_point_in_diamond()
    Autoclash.click_with_jitter(x, y)
    click_count += 1
    time.sleep(random.uniform(0.03, 0.07))

    # Check depletion every 3 clicks to avoid hammering screenshots
    if click_count % 3 == 0:
        if is_button_depleted(button_xy):
            _status(status_fn, "Battle", f"Unit at {button_xy} depleted after {click_count} clicks")
            break

    # Re-select the button every 20 clicks if still not depleted —
    # the game sometimes fails to register the initial selection click
    if click_count % 20 == 0:
        _status(status_fn, "Battle", f"Re-selecting unit at {button_xy} after {click_count} clicks")
        Autoclash.click_with_jitter(*button_xy)
        time.sleep(0.3)

time.sleep(0.2)
```

---

## Change 5 — Press keyboard '1' before troop deployment in `run_battle` (`capitalraider.py`)

Find `run_battle`. The troop deployment section currently reads:

```python
# Deploy troops
_status(status_fn, "Battle", "Placing troops…")
place_unit(TROOP_BUTTON, stop_fn, status_fn)
```

Replace it with:

```python
# Press '1' to ensure the first unit slot is selected before clicking the button
try:
    pyautogui.press('1')
    time.sleep(0.2)
except Exception:
    _log("run_battle: pyautogui.press('1') failed — continuing without keypress")

# Deploy troops
_status(status_fn, "Battle", "Placing troops…")
place_unit(TROOP_BUTTON, stop_fn, status_fn)
```

`pyautogui` is already imported in `capitalraider.py` — no new import needed.

---

## Summary of files changed

- `AutomationWorker.py`: Change 1 only (ClanCapitalWorker keyboard fix)
- `capitalraider.py`: Changes 2, 3, 4, 5

Make all 5 changes and nothing else.
