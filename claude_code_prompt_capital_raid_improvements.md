# Claude Code Prompt — Clan Capital Raid Improvements

## Context

This is the Autoclash bot — a Clash of Clans automation bot running on Google Play Games for PC
at 1920×1080. The relevant files are:

- `capitalraider.py` — Clan Capital automation engine
- `AutomationWorker.py` — QThread workers (contains `ClanCapitalWorker`)
- `AutoclashGUI.py` — PySide6 GUI frontend

All template images (`.png` files) referenced below already exist in the project folder.
Do not create any new image files. Do not use BlueStacks or ADB — the bot uses Google Play Games for PC.

Read all three files in full before making any changes. There are strict architectural rules:
- `AutoclashGUI.py` is UI only — no automation logic
- `capitalraider.py` is the automation engine — stateless functions called by the worker
- `AutomationWorker.py` contains the `ClanCapitalWorker` QThread which orchestrates everything

---

## Overview of Changes Required

There are three areas of work:

1. **`capitalraider.py`** — add two new functions: `dump_loot_into_home_capital` and `leave_clan`,
   plus new constants they need
2. **`AutomationWorker.py`** — refactor `ClanCapitalWorker` to always call the new loot-dump
   function after rejoining the main clan, and to support a per-account "stay/leave" option
3. **`AutoclashGUI.py`** — replace `ClanCapitalConfigPage` with a scrollable per-account config
   screen (like the existing `ClanGamesAccountSelectPage`) and update the wiring in
   `_start_capital_raid`

---

## PART 1 — `capitalraider.py`

### 1a. New constants

Add the following constants near the top of the file, in the constants section alongside the
existing ones.

```python
# Home clan district coordinates (used when donating loot after rejoining main clan).
# Different from DISTRICTS which are used during enemy capital raids.
HOME_DISTRICTS = [
    ("Goblin Mines",       (1222, 1016)),
    ("Skeleton Park",      ( 871, 1019)),
    ("Golem Quarry",       ( 542,  965)),
    ("Dragon Cliffs",      (1302,  770)),
    ("Builder's Workshop", (1072,  849)),
    ("Balloon Lagoon",     ( 739,  825)),
    ("Wizard Valley",      ( 919,  674)),
    ("Barbarian Camp",     (1135,  572)),
    ("Capital Peak",       ( 912,  378)),
]

# Builder menu / gold spending templates
TPL_BUILDER_ICON        = "capital_builder_icon.png"
TPL_GOLD_SYMBOL         = "capital_gold_symbol.png"
TPL_CONTRIBUTE_GOLD     = "clan_capital_contribute_gold.png"
TPL_UPGRADE_WALLS       = "clan_capital_upgrade_walls.png"
TPL_UPGRADE_BUILDING    = "clan_capital_upgrade_building.png"
TPL_REBUILD_BUILDING    = "clan_capital_rebuild_building.png"
TPL_LEAVE_CLAN          = "leave_clan.png"

# Search region for capital_gold_symbol inside the builder menu
GOLD_SEARCH_BOX: Tuple[int, int, int, int] = (950, 124, 1191, 472)

# Bottom-left exit/back button used throughout the capital screens
BOTTOM_LEFT_EXIT: Tuple[int, int] = (50, 1030)

# "My Clan" tab coordinate (used in the leave-clan flow)
MY_CLAN_TAB_COORD: Tuple[int, int] = (810, 100)

# Confirm button coordinate for the leave-clan confirmation dialog
LEAVE_CLAN_OK_COORD: Tuple[int, int] = (1100, 680)
```

---

### 1b. New function: `leave_clan`

Add this function after the existing `return_to_main_clan` function (around line 595).

```python
def leave_clan(
    stop_fn: Optional[Callable],
    status_fn: Optional[Callable],
) -> bool:
    """
    Leave the clan the current account is in.

    Flow:
      1. Open the profile panel (top-left tab)
      2. Click the 'My Clan' tab at (810, 100)
      3. Find and click leave_clan.png
      4. Confirm by clicking OK at (1100, 680)

    Returns True on success, False if stopped or a step fails.
    """
    _status(status_fn, "LeaveClan", "Opening profile panel…")
    Autoclash.click_with_jitter(*PROFILE_TAB_COORD)
    time.sleep(1.0)
    if _stopped(stop_fn):
        return False

    _status(status_fn, "LeaveClan", "Clicking My Clan tab…")
    Autoclash.click_with_jitter(*MY_CLAN_TAB_COORD)
    time.sleep(1.0)
    if _stopped(stop_fn):
        return False

    leave_coords = _find_template_retry(TPL_LEAVE_CLAN, attempts=5, delay=0.5)
    if leave_coords is None:
        _status(status_fn, "LeaveClan", "Could not find leave_clan button — aborting leave")
        return False

    _status(status_fn, "LeaveClan", "Clicking leave clan button…")
    Autoclash.click_with_jitter(*leave_coords)
    time.sleep(1.0)
    if _stopped(stop_fn):
        return False

    _status(status_fn, "LeaveClan", "Confirming leave…")
    Autoclash.click_with_jitter(*LEAVE_CLAN_OK_COORD)
    time.sleep(2.0)

    _status(status_fn, "LeaveClan", "Left clan successfully")
    return True
```

---

### 1c. New function: `dump_loot_into_home_capital`

Add this function after `leave_clan`. This is the largest new function. Read the logic
description carefully before implementing.

```python
def dump_loot_into_home_capital(
    stop_fn: Optional[Callable],
    status_fn: Optional[Callable],
) -> None:
    """
    After rejoining the main clan, navigate to the Clan Capital overview and
    spend all accumulated Capital Gold across available home districts.

    High-level flow:
      1. Navigate to the Clan Capital ship (reuses navigate_to_capital).
      2. Click BOTTOM_LEFT_EXIT repeatedly (1-second pauses, up to 20 attempts)
         until capital_returnhome.png is visible — this gets us to the main
         clan capital overview showing all home districts.
      3. Iterate HOME_DISTRICTS in order. For each district:
           a. Click the district coordinate.
           b. Wait 5 seconds for the screen to load.
           c. Check whether capital_returnhome.png is still visible.
              - VISIBLE  → district is locked/unavailable. Do NOT click anything
                           to deselect — the district click did nothing. Simply
                           skip to the next district.
              - NOT visible → we are inside the district. Run the gold-spending
                              inner loop (see below).
      4. Gold-spending inner loop (runs while inside a district):
           a. Click capital_builder_icon.png to open the builder menu.
              Wait 1 second.
           b. Search GOLD_SEARCH_BOX for capital_gold_symbol.png.
              Retry up to 3 times with 0.5-second pauses between attempts.
              - Not found after all retries → district is fully upgraded.
                Click BOTTOM_LEFT_EXIT to exit the district back to the overview.
                Break out of the inner loop and move to the next district.
              - Found → click it. Wait 1 second.
           c. Find which upgrade/rebuild confirmation button is on screen.
              Check for these three templates in order:
                clan_capital_upgrade_walls.png
                clan_capital_upgrade_building.png
                clan_capital_rebuild_building.png
              Click whichever is found. If none found after up to 3 attempts
              (0.5s apart), log a warning and break to the next district.
              Wait 1 second.
           d. Find and click clan_capital_contribute_gold.png.
              If not found after 3 attempts (0.5s apart), log a warning and
              break to the next district.
              Wait 5 seconds.
           e. Check for clan_capital_contribute_gold.png again:
              - STILL VISIBLE → could not contribute (not enough gold).
                Account's gold is exhausted. Click BOTTOM_LEFT_EXIT until
                capital_returnhome.png is visible (up to 20 attempts, 1s apart),
                then click capital_returnhome.png to return to the home village.
                Return from dump_loot_into_home_capital entirely.
              - NOT visible → gold was contributed successfully.
                Loop back to step (a) — click builder icon again to spend more
                gold on the same or next available upgrade in this district.
      5. After iterating all 9 districts without exhausting gold (all districts
         either skipped as locked or exited as fully upgraded), find and click
         capital_returnhome.png to return to the home village.
    """
```

Implement the function body faithfully to the docstring above. Use `_stopped(stop_fn)` checks
between major steps. Use `_status(status_fn, "LootDump", "...")` for all log messages.
Use `Autoclash.find_template(tpl, search_box=...)` where a search box is specified, and
`Autoclash.find_template(tpl)` otherwise. Use `Autoclash.click_with_jitter(x, y)` for all
clicks. Use `time.sleep(n)` for waits.

For the "click BOTTOM_LEFT_EXIT until capital_returnhome.png visible" pattern (used in two
places), extract it into a small helper inside the function or a module-level helper named
`_exit_to_capital_overview` to avoid duplication:

```python
def _exit_to_capital_overview(stop_fn, status_fn, max_attempts=20):
    """Click BOTTOM_LEFT_EXIT until capital_returnhome.png is visible."""
    for attempt in range(1, max_attempts + 1):
        if _stopped(stop_fn):
            return False
        rh = Autoclash.find_template("capital_returnhome.png")
        if rh:
            _log(f"capital_returnhome visible after {attempt} attempt(s)")
            return True
        _log(f"capital_returnhome not visible — clicking bottom-left (attempt {attempt})")
        Autoclash.click_with_jitter(*BOTTOM_LEFT_EXIT)
        time.sleep(1.0)
    _log("_exit_to_capital_overview: timed out")
    return False
```

Place this helper just above `dump_loot_into_home_capital`.

---

## PART 2 — `AutomationWorker.py` — `ClanCapitalWorker`

### 2a. Change the constructor signature

Currently `ClanCapitalWorker.__init__` accepts:
```python
selected_accounts: List[str],
...
return_to_main_clan: bool = False,
```

Change it to accept a dict of per-account options instead:
```python
account_clan_options: Dict[str, str],   # {account_name: "stay" | "leave"}
```

Remove the `selected_accounts` and `return_to_main_clan` parameters entirely.
Store as `self.account_clan_options = dict(account_clan_options)`.

The iteration order of `account_clan_options` defines the account processing order — do not
sort it.

The `selected_accounts` list used inside `run()` should be derived from the dict keys:
```python
for account, clan_option in self.account_clan_options.items():
```

### 2b. Update the `stop` method

The `stop` method currently reads:
```python
def stop(self):
    self._stop_requested = True
    Autoclash._default_session.stop_requested = True
```

This is correct and does not need changing.

### 2c. Update `run()` — account loop

The main account loop in `run()` currently ends with:
```python
if not self._stop_requested and self._return_to_main_clan:
    capitalraider.return_to_main_clan(
        stop_fn=lambda: self._stop_requested,
        status_fn=_status,
    )
```

Replace this entire block with the following logic (always runs, no flag check):

```python
if not self._stop_requested:
    # Always rejoin the main clan
    _status("MainClan", f"Rejoining main clan for '{account}'…")
    capitalraider.return_to_main_clan(
        stop_fn=lambda: self._stop_requested,
        status_fn=_status,
    )

if not self._stop_requested:
    # Always dump accumulated Capital Gold into the home clan capital
    _status("LootDump", f"Dumping loot into home capital for '{account}'…")
    capitalraider.dump_loot_into_home_capital(
        stop_fn=lambda: self._stop_requested,
        status_fn=_status,
    )

if not self._stop_requested and clan_option == "leave":
    # Leave the main clan if the per-account option says so
    _status("LeaveClan", f"Leaving clan for '{account}'…")
    capitalraider.leave_clan(
        stop_fn=lambda: self._stop_requested,
        status_fn=_status,
    )
```

Note: `clan_option` comes from iterating `self.account_clan_options.items()` — see 2a above.

Also remove the `_EXCLUDED_ACCOUNTS = {"lewis", "williamleeming"}` constant and the skip block
that uses it, since the GUI config page now handles exclusion by only passing in ticked accounts.

---

## PART 3 — `AutoclashGUI.py`

### 3a. Replace `ClanCapitalConfigPage` (currently Page 12)

The current `ClanCapitalConfigPage` is a simple grid of checkboxes plus a single global
"Return to main clan after raids" checkbox. Replace it entirely with a new scrollable per-account
list, modelled closely on the existing `ClanGamesAccountSelectPage` (Page 16, around line 1611).

The new page should have:
- A title label: `"Capital Raid"`
- A subtitle:
  ```
  Tick accounts to include. Choose a clan option per account:
  Stay in Clan — account stays in the main clan after raids.
  Leave Clan — account leaves the main clan after raids.
  ```
- A `QScrollArea` containing one row per account (excluding `"lewis"` and `"williamleeming"`).
  Each row has:
  - `QCheckBox()` (no label, fixed width 20) — include/exclude toggle
  - `QLabel(name)` (minimum width 150) — account name
  - `QComboBox` with items `["Stay in Clan", "Leave Clan"]`, default index 0, fixed width 160
  - `QPushButton("↑")` (fixed 28×24) — move account up in order
  - `QPushButton("↓")` (fixed 28×24) — move account down in order
- A `QPushButton("Start Capital Raid")` with objectName `"primary_btn"`, fixed width 240
- A `QPushButton("Back")`, fixed width 240
- A small page label `"Page 12"` in the bottom-left corner (matching the existing style)

State must persist across restarts. Save/load to `capital_raid_state.json` in the same folder,
using the same structure as `clan_games_state.json`:
```json
{
  "order": ["account1", "account2", ...],
  "accounts": {
    "account1": {"checked": true, "combo_index": 0},
    ...
  }
}
```

The page must expose a method:
```python
def selected_account_options(self) -> Dict[str, str]:
    """Return {account_name: 'stay'|'leave'} for every ticked account, in display order."""
```

Where combo index 0 → `"stay"` and combo index 1 → `"leave"`.

Remove the old `return_to_main_clan_enabled` method entirely.

### 3b. Update `_start_capital_raid` in `MainWindow`

Currently (around line 3031):
```python
def _start_capital_raid(self):
    selected = [
        normalize_account_name(n) for n in self.pg_capital_config.selected_accounts()
        if normalize_account_name(n) in APPROVED_ACCOUNTS
    ]
    if not selected:
        ...
    self.worker = ClanCapitalWorker(
        selected_accounts=sorted(set(selected)),
        account_settings_getter=...,
        apply_settings_fn=...,
        return_to_main_clan=self.pg_capital_config.return_to_main_clan_enabled(),
    )
```

Replace with:
```python
def _start_capital_raid(self):
    raw_options = self.pg_capital_config.selected_account_options()
    account_options = {
        normalize_account_name(n): opt
        for n, opt in raw_options.items()
        if normalize_account_name(n) in APPROVED_ACCOUNTS
    }
    if not account_options:
        QMessageBox.warning(self, "No accounts", "Please select at least one account.")
        return
    self.worker = ClanCapitalWorker(
        account_clan_options=account_options,
        account_settings_getter=self._get_account_settings,
        apply_settings_fn=self._apply_settings_to_runtime,
    )
```

(Keep all the signal connections and `_navigate(self.PAGE_CAPITAL_PROGRESS)` call that follow —
do not change those.)

### 3c. Save config page state on Start

In `_start_capital_raid`, before creating the worker, add:
```python
self.pg_capital_config.save_state()
```

This mirrors the pattern used in the Clan Games flow.

---

## Important implementation notes

1. **Two stop flags** — any worker `run()` method must reset both at the top:
   ```python
   self._stop_requested = False
   Autoclash._default_session.stop_requested = False
   ```
   The existing `ClanCapitalWorker.run()` already does this — do not remove it.

2. **Template coordinates are 1920×1080** — do not adjust for DPI scaling.

3. **`_find_template_retry`** already exists in `capitalraider.py` — use it for retry logic
   rather than writing inline retry loops.

4. **`Autoclash.find_template`** signature: `find_template(template_name, confidence=None,
   search_box=None)`. Pass `search_box=GOLD_SEARCH_BOX` when searching for `capital_gold_symbol`.

5. **Do not modify** `run_capital_raid_for_account`, `navigate_to_capital`,
   `handle_capital_lobby`, `attack_next_district`, `run_battle`, `return_to_main_clan`,
   `ensure_correct_clan`, or `find_and_join_clan`. Only add the new functions and update the
   worker/GUI wiring.

6. **`_exit_to_capital_overview`** should be a module-level function in `capitalraider.py`,
   not a nested function, so it is testable and reusable.

7. In `dump_loot_into_home_capital`, after `navigate_to_capital` returns, call
   `_exit_to_capital_overview` immediately (before touching any district). If it returns False
   (timed out or stopped), log a warning and return early.

8. The `dump_loot_into_home_capital` function's outer district loop should check `_stopped(stop_fn)`
   at the top of each iteration. If stopped mid-loop, return immediately.

9. In the GUI, `"lewis"` and `"williamleeming"` should be excluded from the account list in
   `ClanCapitalConfigPage.__init__` (same as the old page did).

10. `Dict` is already imported in all three files — no new imports needed beyond what is used.
