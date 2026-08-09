# Claude Code prompt — Multi-select Event Troops with dynamic per-troop count boxes

Goal: Replace the single "Event Troop" dropdown on the account-config page with a **multi-select checkable list**. When N troops are ticked, show N count boxes, each with a **title above it naming the troop that count is for**. Wire the selection through to the running bot so it actually deploys all selected event troops with their own amounts.

This supersedes "Feature 2" of the earlier prompt (`card_event_and_dual_event_troops_prompt.md`). The card-event work (Feature 1) in that file still stands and is unrelated.

Files: `AutoclashGUI.py` (GUI + wiring) and `Autoclash.py` (deployment + army-bar slot math). Keep the existing logging style. Do not break unrelated behaviour.

---

## PART A — `AutoclashGUI.py`

### A1. Add the two new troop icons to the options list
Find `_EVENT_TROOP_OPTIONS = [ ... ]` (around line 996) and add the two event troops for this month so they appear as choices:

```python
    "elephant_rider.PNG",
    "super_valk.PNG",
```

### A2. Add a module-level helper to prettify template names
Add near the other module-level helpers (e.g. just above `_EVENT_TROOP_OPTIONS`):

```python
def _pretty_troop_name(template: str) -> str:
    """Turn a template filename into a readable label, e.g. 'elephant_rider.PNG' -> 'Elephant Rider'."""
    name = template.rsplit(".", 1)[0]
    if name.endswith("_button"):
        name = name[: -len("_button")]
    return name.replace("_", " ").title()
```

### A3. Replace the single-troop combos with a multi-select list + dynamic count container
In class `AccountConfigPage` (starts around line 799), in `__init__`, find the block that builds the two combos:

```python
        form.addWidget(QLabel("Event Troop:"), r, 0)
        self.event_troop_combo = QComboBox()
        self.event_troop_combo.addItems(_EVENT_TROOP_OPTIONS)
        form.addWidget(self.event_troop_combo, r, 1); r += 1

        form.addWidget(QLabel("Event Troop Count:"), r, 0)
        self.event_count_combo = QComboBox()
        self.event_count_combo.addItems([str(i) for i in range(1, 61)])
        form.addWidget(self.event_count_combo, r, 1); r += 1
```

Replace that entire block with:

```python
        # ── Event troops: multi-select list + dynamic per-troop count boxes ──
        form.addWidget(QLabel("Event Troops (tick all that apply):"), r, 0, 1, 2); r += 1
        self.event_troop_list = QListWidget()
        self.event_troop_list.setFixedHeight(150)
        for _tmpl in _EVENT_TROOP_OPTIONS:
            _item = QListWidgetItem(_pretty_troop_name(_tmpl))
            _item.setData(Qt.ItemDataRole.UserRole, _tmpl)
            _item.setFlags(_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            _item.setCheckState(Qt.CheckState.Unchecked)
            self.event_troop_list.addItem(_item)
        self.event_troop_list.itemChanged.connect(self._rebuild_event_count_boxes)
        form.addWidget(self.event_troop_list, r, 0, 1, 2); r += 1

        form.addWidget(QLabel("Troop counts:"), r, 0, 1, 2); r += 1
        self._event_counts = {}          # template -> last known count (persists across rebuilds)
        self._event_count_spins = {}     # template -> live QSpinBox
        self.event_counts_container = QWidget()
        self.event_counts_layout = QVBoxLayout(self.event_counts_container)
        self.event_counts_layout.setContentsMargins(0, 0, 0, 0)
        form.addWidget(self.event_counts_container, r, 0, 1, 2); r += 1
```

### A4. Add the rebuild method to `AccountConfigPage`
Add this method to the class (e.g. just above `populate`):

```python
    def _rebuild_event_count_boxes(self, *args):
        """Show one count box per ticked troop, with the troop's name as a title above it."""
        # Remember whatever is currently typed before wiping the boxes
        for _tmpl, _spin in self._event_count_spins.items():
            self._event_counts[_tmpl] = _spin.value()

        # Clear existing boxes
        while self.event_counts_layout.count():
            _child = self.event_counts_layout.takeAt(0)
            _w = _child.widget()
            if _w is not None:
                _w.deleteLater()
        self._event_count_spins = {}

        # Rebuild in list order, one titled box per checked troop
        for i in range(self.event_troop_list.count()):
            item = self.event_troop_list.item(i)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            tmpl = item.data(Qt.ItemDataRole.UserRole)

            box = QWidget()
            box_l = QVBoxLayout(box)
            box_l.setContentsMargins(0, 4, 0, 4)
            box_l.setSpacing(2)

            title = QLabel(_pretty_troop_name(tmpl))      # title ABOVE the count box
            title.setStyleSheet("font-weight: bold;")

            spin = QSpinBox()
            spin.setRange(1, 60)
            spin.setValue(int(self._event_counts.get(tmpl, 50)))
            spin.setFixedWidth(120)

            box_l.addWidget(title)
            box_l.addWidget(spin)
            self.event_counts_layout.addWidget(box)
            self._event_count_spins[tmpl] = spin
```

### A5. Update `populate()`
In `AccountConfigPage.populate`, remove the two old lines:

```python
        _set_combo(self.event_troop_combo, str(settings.get("event_troop_button", _EVENT_TROOP_OPTIONS[0])))
        _set_combo(self.event_count_combo, str(int(settings.get("event_troop_count", 50))))
```

and replace them with:

```python
        # Event troops (multi-select). Falls back to the legacy single-troop keys if present.
        saved = settings.get("event_troops", None)
        if saved is None:
            legacy_tmpl = settings.get("event_troop_button")
            legacy_cnt = int(settings.get("event_troop_count", 50))
            saved = [{"template": legacy_tmpl, "count": legacy_cnt}] if legacy_tmpl else []
        saved_map = {t.get("template"): int(t.get("count", 50)) for t in saved if t.get("template")}
        self._event_counts = dict(saved_map)
        self.event_troop_list.blockSignals(True)
        for i in range(self.event_troop_list.count()):
            item = self.event_troop_list.item(i)
            tmpl = item.data(Qt.ItemDataRole.UserRole)
            item.setCheckState(Qt.CheckState.Checked if tmpl in saved_map else Qt.CheckState.Unchecked)
        self.event_troop_list.blockSignals(False)
        self._rebuild_event_count_boxes()
```

### A6. Update `collect()`
In `AccountConfigPage.collect`, remove the two old return entries:

```python
            "event_troop_button": self.event_troop_combo.currentText(),
            "event_troop_count": int(self.event_count_combo.currentText()),
```

and replace them with:

```python
            "event_troops": self._collect_event_troops(),
```

Then add this helper method to the class:

```python
    def _collect_event_troops(self) -> list:
        troops = []
        for i in range(self.event_troop_list.count()):
            item = self.event_troop_list.item(i)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            tmpl = item.data(Qt.ItemDataRole.UserRole)
            spin = self._event_count_spins.get(tmpl)
            count = int(spin.value()) if spin is not None else int(self._event_counts.get(tmpl, 50))
            troops.append({"template": tmpl, "count": count})
        return troops
```

### A7. Make the selection reach the running bot
Find `HOME_SETTING_KEYS = ( ... )` (around line 354) and add `"event_troops",` to the tuple (this is the list of keys copied into the live `CONFIG` per account; without it the selection is saved but never applied — the same reason the old single dropdown never actually took effect at runtime).

### A8. Remove the now-dead Mass Configure rows
Find `_MASS_SETTINGS = [ ... ]` (around line 1012) and delete these two rows, since the widgets they referenced no longer exist:

```python
    ("Event Troop",            "event_troop_button",   "combo", _EVENT_TROOP_OPTIONS),
    ("Event Troop Count",      "event_troop_count",    "combo", [str(i) for i in range(1, 61)]),
```

(Mass-configuring the multi-troop list is out of scope; per-account editing on the account-config page is the supported path.)

---

## PART B — `Autoclash.py`

### B1. Add the runtime default
In the `CONFIG` dict, next to `"event_active"` / `"event_troop_count"` (around line 258), add:

```python
    "event_troops": [],   # list of {"template": str, "count": int}; when non-empty it overrides the single event_troop_button/count
```

### B2. Deploy the list in `phase2_execute`
In `phase2_execute`, inside the existing `if event_active:` block that searches for `event_troop_button` and places `event_troop_count` troops, wrap it so the list path takes precedence and the old single-troop code is the fallback:

```python
        if event_active:
            event_troops = CONFIG.get("event_troops")
            if event_troops:
                log(f"Event active — placing {len(event_troops)} event troop type(s)...")
                for troop in event_troops:
                    tmpl = troop.get("template")
                    cnt = int(troop.get("count", 0))
                    if not tmpl or cnt <= 0:
                        continue
                    log(f"Searching for event troop '{tmpl}' to activate...")
                    found = False
                    for attempt in range(1, CONFIG["max_search_attempts"] + 1):
                        coords = find_template(tmpl, confidence=CONFIG.get("confidence_threshold", 0.75))
                        if coords:
                            log(f"Found '{tmpl}' at ({coords[0]}, {coords[1]}), clicking...")
                            click_smooth(*coords)
                            found = True
                            break
                        if attempt < CONFIG["max_search_attempts"]:
                            time.sleep(CONFIG["wait_between_attempts"])
                    if not found:
                        log(f"WARNING: event troop '{tmpl}' not found, skipping it...")
                        continue
                    fast_event = cnt > 16
                    if fast_event:
                        log(f"Event troop count > 16 ({cnt}) - using fast deployment clicks")
                    log(f"Placing {cnt} of '{tmpl}' across battle points...")
                    for i in range(cnt):
                        x, y = all_battle_points[i % len(all_battle_points)]
                        if fast_event:
                            click_deploy(x, y)
                        else:
                            click_with_jitter(x, y)
                            random_delay()
                    log(f"Finished placing '{tmpl}'.")
                log("All event troops placed!")
            else:
                # ── existing single-event-troop logic, UNCHANGED ──
                # (keep the current code exactly: search for CONFIG["event_troop_button"],
                #  then place CONFIG["event_troop_count"] troops across all_battle_points)
                ...
        else:
            # keep the existing "Event NOT active for this battle" log line unchanged
            ...
```

Keep the current single-troop code verbatim inside the `else:` — do not delete it.

### B3. Fix the army-bar slot-shift math (heroes + siege)
Still in `phase2_execute`, the hero/siege placement assumes at most ONE extra event slot (`event_adds_slot` → `+111`). With multiple event troops there are multiple extra slots. Find the block that computes `_main_tpl`, `event_adds_slot`, `hero_x_shift`, `hero_coords`, and `siege_placement_x` (starts near the comment `# Determine whether the event troop occupies a separate slot from the main troop`). Keep the line `base_hero_coords = [511, 622, 733, 844]` above it and the `num_heroes` / `selected_hero_coords` lines below it, and replace the block with:

```python
        # How many army-bar slots do the event troops occupy?
        # Each event troop whose icon differs from the main troop = one extra leading slot.
        _troop_type = CONFIG.get("troop_type", "edrag")
        if _troop_type == "drag":
            _main_tpl = CONFIG["drag_button"]
        elif _troop_type == "azdrag":
            _main_tpl = CONFIG["azdrag_button"]
        elif _troop_type == "barbarian":
            _main_tpl = CONFIG["barb_button"]
        else:
            _main_tpl = CONFIG["edrag_button"]

        num_event_slots = 0
        if event_active:
            _event_troops = CONFIG.get("event_troops")
            if _event_troops:
                num_event_slots = sum(
                    1 for t in _event_troops
                    if t.get("template") and t.get("template") != _main_tpl and int(t.get("count", 0)) > 0
                )
            else:
                _event_tpl = CONFIG.get("event_troop_button", "")
                num_event_slots = 1 if (_event_tpl and _event_tpl != _main_tpl) else 0

        # Each event slot shifts heroes right by one army-bar slot (111px); siege adds one more.
        hero_x_shift = 111 * num_event_slots
        if siege_machine_active:
            hero_x_shift += 111

        hero_coords = [x + hero_x_shift for x in base_hero_coords]

        siege_placement_x = None
        if siege_machine_active:
            siege_placement_x = 511 + 111 * num_event_slots
            log(f"Siege machine will be placed at x={siege_placement_x}")
```

---

## Verification checklist (confirm after editing)
1. Account-config page: ticking troops in the new list instantly adds/removes a count box below, each titled with the troop's name; unticking removes its box; counts you typed survive re-ticking.
2. Save then reopen the account: the same troops stay ticked with the same counts (round-trips through `event_troops` in `account_configs.json`).
3. With no troops ticked (`event_troops == []`), the bot behaves exactly as before via the single-troop fallback.
4. `event_troops` is in `HOME_SETTING_KEYS`, so the selection reaches `CONFIG` at battle time.
5. In `phase2_execute`, hero/siege x-coords are correct for 0, 1, and 2 distinct event troops (heroes at base, +111, +222; siege at 511, 622, 733).
6. App still launches with no import errors (all widgets used — QListWidget, QListWidgetItem, QSpinBox, QVBoxLayout, QLabel, QWidget — are already imported in AutoclashGUI.py).
