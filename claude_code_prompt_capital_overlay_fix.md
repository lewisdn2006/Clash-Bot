# Claude Code Prompt — Fix Capital Lobby Overlay in dump_loot_into_home_capital

## Context

`capitalraider.py` contains a function `dump_loot_into_home_capital` which navigates to the
home clan capital and spends Capital Gold across available districts.

After `navigate_to_capital()` clicks the capital ship, `_exit_to_capital_overview()` is called.
This helper clicks `BOTTOM_LEFT_EXIT` until `capital_returnhome.png` is visible. This works
correctly — `capital_returnhome.png` IS visible even when the "Go" or "Next Raid" lobby
overlay is on screen.

However, when the "Go" (`capital_go.png`) or "Next Raid" (`capital_nextraid.png`) overlay is
present, the bot cannot enter any district. Every district click appears to do nothing because
the overlay intercepts input, so the district loop cycles through all 9 without entering any.

## What needs to change

Find `dump_loot_into_home_capital` in `capitalraider.py`. Locate the block immediately after
`_exit_to_capital_overview` returns `True` and before the `HOME_DISTRICTS` iteration loop
begins. It currently looks like this:

```python
_status(status_fn, "LootDump", "Exiting to capital overview…")
if not _exit_to_capital_overview(stop_fn, status_fn):
    _status(status_fn, "LootDump", "Could not reach capital overview — aborting loot dump")
    return

# <-- insert the new block here, before the district loop starts -->

for district, coord in HOME_DISTRICTS:
```

Insert the following block at that location:

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
```

## Important constraints

- Only modify `dump_loot_into_home_capital`. Do not change `_exit_to_capital_overview`,
  `handle_capital_lobby`, `navigate_to_capital`, or any other function.
- `TPL_CAPITAL_GO` and `TPL_CAPITAL_NEXTRAID` are already defined as module-level constants
  in `capitalraider.py` — do not redefine them.
- Do not add any retry loop around the overlay check — a single `find_template` call per
  button is sufficient. The overlay is either clearly visible or absent.
- The `_overlay_dismissed` flag is only used for the status log; the district loop that
  follows should be unchanged and runs regardless.
