# Claude Code Prompt — Clan Games Switch Menu Fixes

## Overview

Fix two bugs in `clangamesmaster.py` that cause `settings.png` to be stuck at ~0.430 confidence across many consecutive accounts, triggering repeated hard resets.

**Bug 1 (Cluster 2 — definite):** When `_switch_to_specific_account` fails to find an account after a full two-pass scroll, it returns `False` without closing the switch menu. The switch menu stays open on screen. Every subsequent account then tries to find `settings.png` through the open switch menu overlay — explaining the stuck 0.430 confidence.

**Bug 2 (Cluster 1 — probable):** After `open_stand_and_select_challenge` returns `RESULT_NO_VALID`, the clan games stand UI may not have fully dismissed before cycling begins. The cycling phase immediately calls `_switch_to_specific_account`, which also sees settings.png obscured.

**CRITICAL:** Do NOT press Escape anywhere in this function. If the bot is on the home village screen, pressing Escape opens an "Exit Game?" popup that the bot cannot handle.

**The correct approach** is to use `settings.png` visibility as a proxy for whether the switch menu is open:
- `settings.png` **visible** → home screen, need to open the switch menu
- `settings.png` **not visible** → switch menu is likely already open (from a previous failed switch)

After clicking settings and the switch button, check `settings.png` again — if it is **still visible**, the menu failed to open.

---

## FILE — `clangamesmaster.py`

### Replace the entire `_switch_to_specific_account` function

Find the function beginning:
```python
def _switch_to_specific_account(
    account_name: str,
    stop_fn: Callable[[], bool],
    overlay_fn: Optional[Callable[[list, str], None]] = None,
) -> bool:
    """
    Switch to one specific account via the in-game switch menu.
    Draws the OCR match on the overlay so you can see exactly what was found.
    Returns True on success.
    """
```

Replace the entire function (from `def _switch_to_specific_account` through its final `return True`) with:

```python
def _switch_to_specific_account(
    account_name: str,
    stop_fn: Callable[[], bool],
    overlay_fn: Optional[Callable[[list, str], None]] = None,
) -> bool:
    """
    Switch to one specific account via the in-game switch menu.

    Uses settings.png visibility to determine whether the switch menu is already
    open before trying to open it:
      - settings.png visible   → home screen → open switch menu, then verify it
                                 opened by checking settings.png disappears.
      - settings.png not found → switch menu is likely already open from a
                                 previous failed switch → skip open, scroll directly.

    NEVER presses Escape — on the home screen that opens "Exit Game?" dialog.
    Returns True on success, False on failure (switch menu left open on failure).
    """
    # Look up the switch menu display name — fall back to account_name itself
    switch_display_name = CG_MASTER_SWITCH_NAMES.get(account_name, account_name)
    AC.log(f"CG Master: Switching to '{account_name}' (switch name: '{switch_display_name}')")
    candidate_map = {account_name: switch_display_name}

    # ------------------------------------------------------------------
    # Step 1: Determine state and open switch menu if needed
    # ------------------------------------------------------------------
    AC.log("CG Master: Checking if switch menu needs opening (looking for settings.png)…")
    settings_coords = AC.find_template("settings.png")

    if settings_coords:
        # Home screen detected — open the switch menu.
        AC.log("CG Master: Home screen detected — opening switch menu")
        _menu_opened = False
        for _open_attempt in range(3):
            if stop_fn():
                return False
            AC.click_with_jitter(*settings_coords)
            time.sleep(1.0)
            if stop_fn():
                return False
            AC.click_with_jitter(1245, 244)   # Switch ID / Switch Account button
            time.sleep(1.5)
            if stop_fn():
                return False
            # Verify menu opened — settings.png should now be hidden by the overlay
            settings_after = AC.find_template("settings.png")
            if not settings_after:
                AC.log(f"CG Master: Switch menu open (settings.png gone, attempt {_open_attempt + 1})")
                _menu_opened = True
                break
            AC.log(f"CG Master: Switch menu did not open on attempt {_open_attempt + 1} (settings.png still visible)")
            settings_coords = settings_after   # use fresh coords for next attempt
            time.sleep(1.0)

        if not _menu_opened:
            AC.log("CG Master: Failed to open switch menu after 3 attempts — aborting")
            return False

    else:
        # settings.png not visible — could be:
        #   a) Switch menu is already open from a previous failed switch (most likely)
        #   b) Game is still loading after a hard reset (rare, but possible)
        # Wait up to 30s for settings.png to appear. If it does, open the menu
        # properly. If it never appears, assume the switch menu is already open
        # and proceed directly to scrolling.
        AC.log("CG Master: settings.png not visible — waiting up to 30s (game load or switch menu already open)…")
        appeared_coords = None
        for _wait_attempt in range(15):   # 15 × 2s = 30s
            if stop_fn():
                return False
            settings_coords = AC.find_template("settings.png")
            if settings_coords:
                appeared_coords = settings_coords
                break
            time.sleep(2.0)

        if appeared_coords:
            # Home screen appeared — open switch menu
            AC.log("CG Master: Home screen appeared — opening switch menu")
            _menu_opened = False
            for _open_attempt in range(3):
                if stop_fn():
                    return False
                AC.click_with_jitter(*appeared_coords)
                time.sleep(1.0)
                if stop_fn():
                    return False
                AC.click_with_jitter(1245, 244)
                time.sleep(1.5)
                if stop_fn():
                    return False
                settings_after = AC.find_template("settings.png")
                if not settings_after:
                    AC.log(f"CG Master: Switch menu open (attempt {_open_attempt + 1})")
                    _menu_opened = True
                    break
                AC.log(f"CG Master: Switch menu did not open on attempt {_open_attempt + 1} (settings.png still visible)")
                appeared_coords = settings_after
                time.sleep(1.0)

            if not _menu_opened:
                AC.log("CG Master: Failed to open switch menu after 3 attempts — aborting")
                return False
        else:
            # settings.png not found after 30s — assume switch menu is already open
            AC.log("CG Master: settings.png not found after 30s — assuming switch menu already open, proceeding to scroll")

    # ------------------------------------------------------------------
    # Step 2: Scroll and find the account
    # ------------------------------------------------------------------
    def find_with_scroll(direction: str) -> dict:
        for scan_idx in range(51):
            if stop_fn():
                return {}
            visible = CGC._match_visible_switch_accounts(candidate_map)
            if visible:
                # Draw what OCR found on the overlay before clicking
                if overlay_fn is not None:
                    dets = [
                        {
                            "bbox": d["bbox"],
                            "label": f"{name} → '{d['ocr_text']}' ({d['ocr_conf']:.0%})",
                            "score": float(d["ocr_conf"]),
                        }
                        for name, d in visible.items()
                    ]
                    overlay_fn(dets, f"Switch: found {account_name}")
                return visible
            if scan_idx < 50:
                if direction == "down":
                    CGC._scroll_switch_box_once_down()
                else:
                    CGC._scroll_switch_box_once_up()
        return {}

    visible = find_with_scroll("down")
    if not visible:
        AC.log("CG Master: Not found scrolling down — resetting and retrying")
        for _ in range(50):
            CGC._scroll_switch_box_once_up()
        visible = find_with_scroll("down")

    if not visible:
        AC.log(f"CG Master: Could not find '{account_name}' in switch menu")
        # Do NOT press Escape — pressing Escape on the home screen opens "Exit Game?"
        # The switch menu stays open. The next call to _switch_to_specific_account
        # will see settings.png is not visible and skip the open step, scrolling
        # directly. The list position is already near the top from the second-pass
        # reset scroll above.
        # Save a diagnostic screenshot for post-hoc debugging.
        try:
            import os
            import datetime
            debug_dir = os.path.join(os.path.dirname(__file__), "debug_screenshots")
            os.makedirs(debug_dir, exist_ok=True)
            ts = datetime.datetime.now().strftime("%H%M%S")
            shot = _vision.safe_screenshot()
            shot.save(os.path.join(debug_dir, f"{ts}_switch_not_found_{account_name}.png"))
            AC.log(f"CG Master: Saved diagnostic screenshot → {ts}_switch_not_found_{account_name}.png")
        except Exception as _exc:
            AC.log(f"CG Master: Failed to save diagnostic screenshot: {_exc}")
        return False

    # ------------------------------------------------------------------
    # Step 3: Click the matched account entry
    # ------------------------------------------------------------------
    _, data = next(iter(visible.items()))
    AC.log(
        f"CG Master: Switching to '{account_name}' — "
        f"OCR text='{data['ocr_text']}' conf={data['ocr_conf']:.0%} "
        f"center={data['center']}"
    )
    AC.click_with_jitter(*data["center"])
    AC.random_delay()
    time.sleep(3.0)

    # Click OK on load dialog if present
    for _ in range(5):
        ok_coords = AC.find_template("account_load_okay.png")
        if ok_coords:
            AC.click_with_jitter(*ok_coords)
            AC.random_delay()
            break
        time.sleep(1.0)

    return True
```

---

## Notes

- `pyautogui` is already imported at the top of `clangamesmaster.py` — no new import needed.
- `_vision` is already imported as `import vision as _vision` — no new import needed.
- `os` and `datetime` are imported inline inside the `try` block to avoid cluttering module-level imports.
- `1245, 244` is `ACCOUNT_SWITCH_MENU_COORD` from `AutomationWorker.py` — hardcoded here since `clangamesmaster.py` doesn't import that constant.
- The debug screenshots go to `debug_screenshots/` in the script directory (`C:\Users\fghgh\Desktop\Clash Bot\debug_screenshots\` on the bot PC), which is already synced via OneDrive.
- Do NOT change `HARD_RESET_RELAUNCH_COORD`.
- The old 60-second `for _load_attempt in range(60)` wait loop is fully replaced by this logic — do not keep it.
