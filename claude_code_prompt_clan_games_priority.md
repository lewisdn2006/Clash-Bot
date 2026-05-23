# Claude Code Prompt — Clan Games Account Priority & Per-Account Mode

## Overview

Add two features to the Clan Games mode:
1. **Priority ordering** — drag/reorder which "Get Points" account the bot completes first, second, etc.
2. **Per-account mode** — each account can be set to `"Get Points"` (bot does attacks + point accumulation) or `"Cycle Only"` (bot only uses the account for trashing invalid challenges, never farms points on it).

This requires changes to **three files**: `AutoclashGUI.py`, `AutomationWorker.py`, and `clangamesmaster.py`.

---

## FILE 1 — `AutoclashGUI.py`

### Step 1: Replace the `ClanGamesAccountSelectPage` class entirely

Find the class that begins:
```python
class ClanGamesAccountSelectPage(QWidget):
    def __init__(self, accounts: list, parent=None):
```

Replace the entire class (from `class ClanGamesAccountSelectPage` through its final method `selected_accounts`) with the following new implementation. The new class:
- Uses a scrollable list like `UpgradeAccountsPage` (one row per account)
- Each row has: checkbox | account name label | mode combo ("Get Points" / "Cycle Only") | ↑ button | ↓ button
- Persists state to `clan_games_state.json` in the same directory as the script
- Exposes `account_modes_ordered()` → `Dict[str, str]` (only checked accounts, in display order, value is `"points"` or `"cycle"`)

```python
class ClanGamesAccountSelectPage(QWidget):
    """Per-account Clan Games configuration screen.

    Each account gets a row with:
      - checkbox   (include / exclude)
      - label      (account name)
      - mode combo ("Get Points" or "Cycle Only")
      - ↑ / ↓     (reorder priority)

    State persists across restarts via clan_games_state.json.
    """

    _MODE_LABELS = [
        "Get Points",   # index 0
        "Cycle Only",   # index 1
    ]

    def __init__(self, accounts: list, parent=None):
        super().__init__(parent)
        self._accounts_source = list(accounts)   # original list for new-account fallback

        outer = QVBoxLayout(self)
        outer.setSpacing(10)

        outer.addWidget(_title("Clan Games"))
        outer.addWidget(_subtitle(
            "Tick accounts to include. Set mode per account:\n"
            "Get Points — bot attacks and accumulates clan games points.\n"
            "Cycle Only — bot only refreshes (trashes) invalid challenges; no points."
        ))

        # --- Scrollable account list ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        inner_widget = QWidget()
        inner_layout = QVBoxLayout(inner_widget)
        inner_layout.setSpacing(4)
        inner_layout.setContentsMargins(4, 4, 4, 4)

        self._checkboxes: Dict[str, QCheckBox] = {}
        self._combos: Dict[str, QComboBox] = {}
        self._row_widgets: Dict[str, QWidget] = {}
        self._order: List[str] = list(accounts)

        for name in accounts:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setSpacing(8)
            row_layout.setContentsMargins(0, 0, 0, 0)

            cb = QCheckBox()
            cb.setFixedWidth(20)
            self._checkboxes[name] = cb

            lbl = QLabel(name)
            lbl.setMinimumWidth(150)

            combo = QComboBox()
            combo.addItems(self._MODE_LABELS)
            combo.setCurrentIndex(0)   # default: Get Points
            combo.setFixedWidth(130)
            self._combos[name] = combo

            up_btn = QPushButton("↑")
            up_btn.setFixedWidth(28)
            up_btn.setFixedHeight(24)
            up_btn.clicked.connect(lambda *_, n=name: self._move_up(n))

            down_btn = QPushButton("↓")
            down_btn.setFixedWidth(28)
            down_btn.setFixedHeight(24)
            down_btn.clicked.connect(lambda *_, n=name: self._move_down(n))

            row_layout.addWidget(cb)
            row_layout.addWidget(lbl)
            row_layout.addWidget(combo)
            row_layout.addWidget(up_btn)
            row_layout.addWidget(down_btn)
            row_layout.addStretch()

            self._row_widgets[name] = row_widget

        self._inner_layout = inner_layout
        self._rebuild_list()
        scroll.setWidget(inner_widget)
        outer.addWidget(scroll, stretch=1)

        self.start_btn = QPushButton("Start Clan Games")
        self.start_btn.setObjectName("primary_btn")
        self.start_btn.setFixedWidth(240)
        outer.addWidget(self.start_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.back_btn = QPushButton("Back")
        self.back_btn.setFixedWidth(240)
        outer.addWidget(self.back_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        _page_lbl = QLabel("Page 16", self)
        _page_lbl.setStyleSheet("color: #555; font-size: 9px;")
        _page_lbl.adjustSize()
        _page_lbl.move(5, 5)
        _page_lbl.raise_()

        # Restore previous selections
        self.load_state()

    def _rebuild_list(self) -> None:
        """Repopulate inner_layout in the current self._order sequence."""
        while self._inner_layout.count():
            self._inner_layout.takeAt(0)
        for name in self._order:
            self._inner_layout.addWidget(self._row_widgets[name])
        self._inner_layout.addStretch()

    def _move_up(self, name: str) -> None:
        idx = self._order.index(name)
        if idx > 0:
            self._order[idx], self._order[idx - 1] = self._order[idx - 1], self._order[idx]
            self._rebuild_list()

    def _move_down(self, name: str) -> None:
        idx = self._order.index(name)
        if idx < len(self._order) - 1:
            self._order[idx], self._order[idx + 1] = self._order[idx + 1], self._order[idx]
            self._rebuild_list()

    def account_modes_ordered(self) -> Dict[str, str]:
        """Return {account_name: mode} for every ticked account, in display order.

        mode is "points" or "cycle".
        """
        result: Dict[str, str] = {}
        for name in self._order:
            if self._checkboxes[name].isChecked():
                mode = "cycle" if self._combos[name].currentIndex() == 1 else "points"
                result[name] = mode
        return result

    def save_state(self) -> None:
        """Persist checkbox, combo, and order state to clan_games_state.json."""
        state = {
            "order": self._order,
            "accounts": {
                name: {
                    "checked": self._checkboxes[name].isChecked(),
                    "combo_index": self._combos[name].currentIndex(),
                }
                for name in self._accounts_source
            },
        }
        try:
            path = Path(__file__).parent / "clan_games_state.json"
            path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"ClanGamesAccountSelectPage: failed to save state: {e}")

    def load_state(self) -> None:
        """Restore checkbox, combo, and order state from clan_games_state.json."""
        try:
            path = Path(__file__).parent / "clan_games_state.json"
            if not path.exists():
                return
            state = json.loads(path.read_text(encoding="utf-8"))

            # Restore order — include only accounts that still exist, append any new ones at end
            saved_order = state.get("order", [])
            known = set(self._accounts_source)
            restored = [a for a in saved_order if a in known]
            for a in self._accounts_source:
                if a not in restored:
                    restored.append(a)
            self._order = restored
            self._rebuild_list()

            # Restore checkbox and combo state
            for name, data in state.get("accounts", {}).items():
                if name in self._checkboxes:
                    self._checkboxes[name].setChecked(data.get("checked", False))
                if name in self._combos:
                    self._combos[name].setCurrentIndex(data.get("combo_index", 0))
        except Exception as e:
            print(f"ClanGamesAccountSelectPage: failed to load state: {e}")
```

### Step 2: Update `_start_clan_games` in `MainWindow`

Find the method:
```python
    def _start_clan_games(self):
        selected = self.pg_clan_games_select.selected_accounts()
        if not selected:
            QMessageBox.warning(self, "No Accounts Selected", "Please select at least one account.")
            return
        log(f"GUI: Starting Clan Games Master Bot — accounts: {', '.join(selected)}")
        self._cgm_completed: list = []
        self.pg_clan_games.mode_label.setText("—")
        self.pg_clan_games.account_label.setText("—")
        self.pg_clan_games.completed_label.setText("none")
        self.pg_clan_games.status_label.setText("Starting…")

        self.worker = ClanGamesMasterWorker(
            account_settings_getter=self._get_account_settings,
            apply_settings_fn=self._apply_settings_to_runtime,
            selected_accounts=selected,
        )
```

Replace with:
```python
    def _start_clan_games(self):
        account_modes = self.pg_clan_games_select.account_modes_ordered()
        if not account_modes:
            QMessageBox.warning(self, "No Accounts Selected", "Please select at least one account.")
            return
        self.pg_clan_games_select.save_state()
        selected = list(account_modes.keys())
        log(f"GUI: Starting Clan Games Master Bot — accounts: {', '.join(selected)}")
        self._cgm_completed: list = []
        self.pg_clan_games.mode_label.setText("—")
        self.pg_clan_games.account_label.setText("—")
        self.pg_clan_games.completed_label.setText("none")
        self.pg_clan_games.status_label.setText("Starting…")

        self.worker = ClanGamesMasterWorker(
            account_settings_getter=self._get_account_settings,
            apply_settings_fn=self._apply_settings_to_runtime,
            selected_accounts=selected,
            account_modes=account_modes,
        )
```

---

## FILE 2 — `AutomationWorker.py`

### Update `ClanGamesMasterWorker.__init__`

Find:
```python
    def __init__(self, account_settings_getter, apply_settings_fn, selected_accounts=None, parent=None):
        super().__init__(parent)
        self._stop_requested = False
        Autoclash._default_session.stop_requested = False
        self._get_account_settings = account_settings_getter
        self._apply_settings = apply_settings_fn
        self._selected_accounts = selected_accounts
```

Replace with:
```python
    def __init__(self, account_settings_getter, apply_settings_fn, selected_accounts=None, account_modes=None, parent=None):
        super().__init__(parent)
        self._stop_requested = False
        Autoclash._default_session.stop_requested = False
        self._get_account_settings = account_settings_getter
        self._apply_settings = apply_settings_fn
        self._selected_accounts = selected_accounts
        self._account_modes = account_modes or {}
```

### Update the `clangamesmaster.run_master_bot` call inside `ClanGamesMasterWorker.run`

Find:
```python
            clangamesmaster.run_master_bot(
                stop_fn=self._stopped,
                status_fn=status_fn,
                account_completed_fn=account_completed_fn,
                apply_settings_fn=apply_settings_fn,
                overlay_fn=self.overlay_draw.emit,
                hard_reset_fn=self._perform_hard_game_restart,
                attack_accounts=self._selected_accounts,
            )
```

Replace with:
```python
            clangamesmaster.run_master_bot(
                stop_fn=self._stopped,
                status_fn=status_fn,
                account_completed_fn=account_completed_fn,
                apply_settings_fn=apply_settings_fn,
                overlay_fn=self.overlay_draw.emit,
                hard_reset_fn=self._perform_hard_game_restart,
                attack_accounts=self._selected_accounts,
                account_modes=self._account_modes,
            )
```

---

## FILE 3 — `clangamesmaster.py`

### Update `run_master_bot` signature and split accounts by mode

Find the function signature:
```python
def run_master_bot(
    stop_fn: Callable[[], bool],
    status_fn: Callable[[str, str], None],
    account_completed_fn: Optional[Callable[[str], None]] = None,
    apply_settings_fn: Optional[Callable[[str], None]] = None,
    overlay_fn: Optional[Callable[[list, str], None]] = None,
    hard_reset_fn: Optional[Callable[[], None]] = None,
    attack_accounts: Optional[List[str]] = None,
) -> None:
```

Replace with:
```python
def run_master_bot(
    stop_fn: Callable[[], bool],
    status_fn: Callable[[str, str], None],
    account_completed_fn: Optional[Callable[[str], None]] = None,
    apply_settings_fn: Optional[Callable[[str], None]] = None,
    overlay_fn: Optional[Callable[[list, str], None]] = None,
    hard_reset_fn: Optional[Callable[[], None]] = None,
    attack_accounts: Optional[List[str]] = None,
    account_modes: Optional[Dict[str, str]] = None,
) -> None:
```

Then find the lines inside `run_master_bot` that read:
```python
    completed:          Set[str]            = set()
    last_trash_by_ingame: Dict[str, float]  = {}
    attack_idx = 0
    _switch_fail_count = 0
    _accounts = attack_accounts if attack_accounts is not None else ATTACK_ACCOUNTS
    account_attack_counts: Dict[str, int] = {}
    account_upgrade_counts: Dict[str, int] = {}
```

Replace with:
```python
    completed:          Set[str]            = set()
    last_trash_by_ingame: Dict[str, float]  = {}
    attack_idx = 0
    _switch_fail_count = 0
    _modes = account_modes or {}
    _all_accounts = attack_accounts if attack_accounts is not None else ATTACK_ACCOUNTS
    # "Get Points" accounts go through the attack loop; "Cycle Only" accounts only cycle.
    _attack_accounts = [a for a in _all_accounts if _modes.get(a, "points") == "points"]
    # All selected accounts (both modes) participate in challenge cycling.
    _cycle_accounts  = _all_accounts
    account_attack_counts: Dict[str, int] = {}
    account_upgrade_counts: Dict[str, int] = {}
```

Then find the lines:
```python
            if attack_idx >= len(_accounts):
                # All accounts completed — final cycling pass then stop
                AC.log("CG Master: All accounts completed — running final cycling pass")
                status_fn("Final Cycling", "All accounts done — clearing remaining bad challenges…")
                run_cycling_phase(last_trash_by_ingame, stop_fn, status_fn, overlay_fn, attack_accounts=_accounts)
```

Replace with:
```python
            if attack_idx >= len(_attack_accounts):
                # All Get Points accounts completed — final cycling pass then stop
                AC.log("CG Master: All accounts completed — running final cycling pass")
                status_fn("Final Cycling", "All accounts done — clearing remaining bad challenges…")
                run_cycling_phase(last_trash_by_ingame, stop_fn, status_fn, overlay_fn, attack_accounts=_cycle_accounts)
```

Then find:
```python
            current_account = _accounts[attack_idx]
```

Replace with:
```python
            current_account = _attack_accounts[attack_idx]
```

Then find the lines that advance `attack_idx` past completed accounts:
```python
            # Advance past completed accounts
            while (
                attack_idx < len(_accounts)
                and _accounts[attack_idx] in completed
            ):
                attack_idx += 1
```

Replace with:
```python
            # Advance past completed accounts
            while (
                attack_idx < len(_attack_accounts)
                and _attack_accounts[attack_idx] in completed
            ):
                attack_idx += 1
```

Then find the call to `run_cycling_phase` inside the `RESULT_NO_VALID` block (not the final cycling pass — the one triggered when the current account has no valid challenges):
```python
                    cycle_result = run_cycling_phase(last_trash_by_ingame, stop_fn, status_fn, overlay_fn, hard_reset_fn)
```

Replace with:
```python
                    cycle_result = run_cycling_phase(last_trash_by_ingame, stop_fn, status_fn, overlay_fn, hard_reset_fn, attack_accounts=_cycle_accounts)
```

---

## Notes

- `account_modes` is `Dict[str, str]` where the value is `"points"` or `"cycle"`. Accounts absent from the dict default to `"points"`.
- `_attack_accounts` preserves the user-specified ordering — the first account in the list is the one that gets max points first.
- `_cycle_accounts` = `_all_accounts` (all selected, regardless of mode) so that "Cycle Only" accounts help refresh the challenge pool for everyone.
- "Cycle Only" accounts never appear in the outer attack loop and so are never marked `completed`. They cycle indefinitely until the bot is stopped.
- The GUI saves state to `clan_games_state.json` on Start, and loads it automatically on launch (same pattern as `upgrade_accounts_state.json`).
- Do NOT change `HARD_RESET_RELAUNCH_COORD` — it is already correct at `(20, 20)`.
