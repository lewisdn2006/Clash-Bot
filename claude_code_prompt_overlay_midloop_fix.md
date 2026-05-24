# Claude Code Prompt — Fix Capital Overlay Reappearing Mid-Loop in dump_loot_into_home_capital

## Context

`capitalraider.py` contains `dump_loot_into_home_capital`, which iterates over
`HOME_DISTRICTS` and spends Capital Gold in each one.

Before the loop starts, there is already a block that dismisses a "Go" or
"Next Raid" overlay if it is present on the capital overview screen. This works
for the initial entry into the overview.

However, the overlay can also reappear **between districts** — after the bot
exits a completed district (clicking `BOTTOM_LEFT_EXIT`) and returns to the
overview, the Go/Next Raid button may be present again. Currently there is no
check inside the loop, so every remaining district click hits the invisible
overlay and silently fails.

## What needs to change

Make exactly two changes to `capitalraider.py`:

---

### Change 1 — Add a module-level helper `_dismiss_capital_lobby_overlay`

Add the following function **immediately after** `_exit_to_capital_overview`.
The `_exit_to_capital_overview` function ends at line 707 with:

```python
    _log("_exit_to_capital_overview: timed out")
    return False
```

Insert the new function after that closing line:

```python
def _dismiss_capital_lobby_overlay(stop_fn, status_fn) -> bool:
    """
    If a 'Go' or 'Next Raid' lobby overlay is visible on the capital overview,
    click it and back out to a clean overlay-free overview via
    _exit_to_capital_overview.

    Returns True when the overview is clean (either the overlay was dismissed
    successfully, or no overlay was present at all).
    Returns False only if the overlay was found but _exit_to_capital_overview
    subsequently timed out.
    """
    for _tpl, _label in ((TPL_CAPITAL_GO, "Go"), (TPL_CAPITAL_NEXTRAID, "Next Raid")):
        if _stopped(stop_fn):
            return False
        _coords = Autoclash.find_template(_tpl)
        if _coords:
            _status(status_fn, "LootDump", f"{_label} overlay found — clicking to dismiss…")
            Autoclash.click_with_jitter(*_coords)
            time.sleep(2.0)
            _status(status_fn, "LootDump", "Backing out to clean capital overview…")
            if not _exit_to_capital_overview(stop_fn, status_fn):
                _status(status_fn, "LootDump",
                        f"Could not return to overview after clicking {_label} — cannot continue")
                return False
            _status(status_fn, "LootDump", "Overlay dismissed — capital overview is clean")
            return True
    # No overlay found — overview already clean
    return True
```

---

### Change 2 — Replace the inline overlay block in `dump_loot_into_home_capital`
and add an overlay check inside the district loop

#### 2a — Replace the existing inline overlay block (before the loop)

Find this block in `dump_loot_into_home_capital` (currently before the
`for district_name, district_coord in HOME_DISTRICTS:` loop):

```python
    # Dismiss any active "Go" or "Next Raid" lobby overlay.
    # These buttons are visible alongside capital_returnhome.png but block district entry.
    # Clicking either navigates deeper into the capital; then we back out with
    # _exit_to_capital_overview to reach a clean overlay-free overview.
    _overlay_dismissed = False
    for _tpl, _label in ((TPL_CAPITAL_GO, "Go"), (TPL_CAPITAL_NEXTRAID, "Next Raid")):
        if _stopped(stop_fn):
            return
        _coords = Autoclash.find_template(_tpl)
        if _coords:
            _status(status_fn, "LootDump", f"{_label} overlay found — clicking to dismiss…")
            Autoclash.click_with_jitter(*_coords)
            time.sleep(2.0)
            _status(status_fn, "LootDump", "Backing out to clean capital overview…")
            if not _exit_to_capital_overview(stop_fn, status_fn):
                _status(status_fn, "LootDump", f"Could not return to overview after clicking {_label} — aborting loot dump")
                return
            _overlay_dismissed = True
            break

    if _overlay_dismissed:
        _status(status_fn, "LootDump", "Overlay dismissed — capital overview is clean")

    for district_name, district_coord in HOME_DISTRICTS:
```

Replace it with:

```python
    # Dismiss any active "Go" or "Next Raid" lobby overlay before entering the loop.
    if not _dismiss_capital_lobby_overlay(stop_fn, status_fn):
        _status(status_fn, "LootDump", "Could not dismiss initial overlay — aborting loot dump")
        return

    for district_name, district_coord in HOME_DISTRICTS:
```

#### 2b — Add an overlay check at the top of the district loop body

The first line inside the `for district_name, district_coord in HOME_DISTRICTS:` loop body is:

```python
        if _stopped(stop_fn):
            return

        _status(status_fn, "LootDump", f"Selecting district: {district_name}…")
        Autoclash.click_with_jitter(*district_coord)
```

Replace it with:

```python
        if _stopped(stop_fn):
            return

        # Re-check for Go/Next Raid overlay before each district — it can
        # reappear after exiting a completed district back to the overview.
        if not _dismiss_capital_lobby_overlay(stop_fn, status_fn):
            _status(status_fn, "LootDump", "Could not dismiss overlay mid-loop — aborting loot dump")
            return

        if _stopped(stop_fn):
            return

        _status(status_fn, "LootDump", f"Selecting district: {district_name}…")
        Autoclash.click_with_jitter(*district_coord)
```

---

## Important constraints

- Only modify `capitalraider.py`.
- Do not change `_exit_to_capital_overview`, `handle_capital_lobby`,
  `navigate_to_capital`, or any other function.
- `TPL_CAPITAL_GO` and `TPL_CAPITAL_NEXTRAID` are already defined as
  module-level constants — do not redefine them.
- The `_dismiss_capital_lobby_overlay` helper must be placed **after**
  `_exit_to_capital_overview` (which it calls) and **before**
  `dump_loot_into_home_capital` (which calls it).
- The district loop's gold-spending inner `while True:` block and everything
  else in `dump_loot_into_home_capital` must remain unchanged.
- After making the changes, verify that:
  - `_dismiss_capital_lobby_overlay` exists as a module-level function
  - It is called exactly twice in `dump_loot_into_home_capital`: once before
    the loop and once at the top of each loop iteration
  - The old inline overlay block (with `_overlay_dismissed`) is fully removed
