# Claude Code prompt — Card Event (temporary) + Two Event Troops

Make the following two changes to the Autoclash Clash of Clans bot. All edits are in `Autoclash.py` unless stated otherwise. Do NOT change unrelated behaviour. Keep the existing logging style (`log(...)`).

---

## FEATURE 1 — Temporary Card Collection Event (must be trivially deletable)

Context: A month-long in-game event lets each account collect cards from battles. On a battle where a card was won, the loot screen shows a `claim_card` button **instead of** the normal return-home button. When that happens the bot must: click the claim button, wait, click through the reveal, then hit the Continue button on the card-collect screen, then carry on exactly as normal.

This is temporary — I will delete it when the event ends — so wrap EVERY addition in clearly marked banner comments so I can find and remove them in one pass:

```
# ═══ TEMP CARD EVENT — REMOVE AFTER EVENT ENDS ═══
... code ...
# ═══ END TEMP CARD EVENT ═══
```

### 1a. Add a module-level toggle
Near the top of the module (just above the `CONFIG = { ... }` definition), add, inside the TEMP banner:

```python
# ═══ TEMP CARD EVENT — REMOVE AFTER EVENT ENDS ═══
CARD_EVENT_ACTIVE = True   # set False (or delete this block) when the card event ends
# ═══ END TEMP CARD EVENT ═══
```

### 1b. Register the template
In the `CONFIG` dict, immediately after the line `"claim_reward_button": "claim_reward_button.png",`, add inside the TEMP banner:

```python
    # ═══ TEMP CARD EVENT — REMOVE AFTER EVENT ENDS ═══
    "claim_card_button": "claim_card.PNG",
    # ═══ END TEMP CARD EVENT ═══
```

### 1c. Handle the card in `phase3_wait_for_return`
Inside `phase3_wait_for_return`, within the `while True:` poll loop, AFTER the screenshot is taken and the error-button check runs, but BEFORE the existing `if return_coords:` block, insert the following. (The card button replaces the return button, so it must be checked first.)

```python
            # ═══ TEMP CARD EVENT — REMOVE AFTER EVENT ENDS ═══
            if CARD_EVENT_ACTIVE:
                claim_card_coords = find_template(CONFIG["claim_card_button"], screenshot=screenshot)
                if claim_card_coords:
                    log(f"Card found! Claim card button at ({claim_card_coords[0]}, {claim_card_coords[1]})")

                    # Capture loot before claiming, same as the normal return/claim branches
                    log("Waiting 2.5s to capture loot before claiming card...")
                    _pauseable_sleep(self, 2.5)
                    try:
                        snapshot = self.loot_tracker.extract_and_record()
                        log(f"✓ Loot captured successfully: {snapshot}")
                    except Exception as e:
                        log(f"✗ WARNING: Failed to record loot automatically: {e}")
                        import traceback
                        traceback.print_exc()

                    # Click the claim_card button
                    ccx, ccy = add_jitter(*claim_card_coords)
                    log(f"Clicking claim card button at ({ccx}, {ccy})")
                    pyautogui.click(ccx, ccy)

                    # Wait 5 seconds for the reveal to load
                    log("Waiting 5 seconds after claiming card...")
                    _pauseable_sleep(self, 5)

                    # Click centre of the screen 3 times, 1 second apart
                    screen_w, screen_h = pyautogui.size()
                    center_x, center_y = screen_w // 2, screen_h // 2
                    for i in range(1, 4):
                        log(f"Card centre click {i}/3 at ({center_x}, {center_y})")
                        pyautogui.click(center_x, center_y)
                        if i < 3:  # no wait after the last click
                            _pauseable_sleep(self, 1)

                    # Click the Continue button on the card-collect screen.
                    # Coordinate measured from card_collect.PNG (1920x1080): centre of the green
                    # "Continue" button = (997, 940). NOTE: this is deliberately different from the
                    # treasure/claim_reward final click at (955, 902).
                    log("Clicking Continue button at (997, 940)")
                    click_with_jitter(997, 940)
                    random_delay()

                    self.dismiss_star_bonus_popup_after_return()
                    return True
            # ═══ END TEMP CARD EVENT ═══
```

Notes:
- Use the existing helpers already in scope in that method: `find_template`, `add_jitter`, `click_with_jitter`, `random_delay`, `_pauseable_sleep`, `self.loot_tracker.extract_and_record()`, `self.dismiss_star_bonus_popup_after_return()`. Do not invent new helpers.
- When `CARD_EVENT_ACTIVE` is `False`, behaviour must be byte-for-byte identical to today (the whole block is skipped).
- Do not touch the existing `return_coords` / `claim_reward_coords` branches.

---

## FEATURE 2 — Support two (or more) different event troops with different amounts

Context: There is also an event-troops event running. Currently `phase2_execute` only deploys ONE event troop (`CONFIG["event_troop_button"]` × `CONFIG["event_troop_count"]`). This month there are TWO event troops — `elephant_rider.PNG` and `super_valk.PNG` — each needing a different amount. Both templates already exist in the bot folder.

Make this a clean, backward-compatible change: add a new optional `CONFIG["event_troops"]` list. When it is a non-empty list it drives deployment; when it is absent/empty the old single-troop code path runs unchanged. Clearing the list therefore fully restores the current behaviour.

### 2a. Add the config list
In `CONFIG`, next to the existing `"event_active"` / `"event_troop_count"` entries, add:

```python
    # Multiple event troops. When this list is non-empty it OVERRIDES the single
    # event_troop_button/event_troop_count settings for every account while event_active is on.
    # Leave empty ([]) to fall back to the single-troop behaviour.
    "event_troops": [
        {"template": "elephant_rider.PNG", "count": 20},   # TODO: set real amount
        {"template": "super_valk.PNG",     "count": 20},   # TODO: set real amount
    ],
```

### 2b. Deploy the list in `phase2_execute`
In `phase2_execute`, inside the `if event_active:` block that currently searches for `event_troop_button` and places `event_troop_count` troops, wrap it so the new list path takes precedence:

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

Keep the existing single-troop code verbatim inside the `else:` branch — do not delete it.

### 2c. Fix the army-bar slot-shift math (heroes + siege)
Still in `phase2_execute`, the hero/siege placement currently assumes at most ONE extra event slot (`event_adds_slot` → `+111`). With two event troops there are two extra slots, so heroes/siege must shift by `111 × (number of distinct event slots)`.

Find the block that starts around the comment `# Determine whether the event troop occupies a separate slot from the main troop` and computes `_main_tpl`, `event_adds_slot`, `hero_x_shift`, `hero_coords`, and `siege_placement_x`. Replace that block (but KEEP the line `base_hero_coords = [511, 622, 733, 844]` above it, and KEEP the `num_heroes` / `selected_hero_coords` lines below it) with:

```python
        # Determine how many army-bar slots the event troops occupy.
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

        # Siege sits in the first hero slot position before the siege shift is applied.
        siege_placement_x = None
        if siege_machine_active:
            siege_placement_x = 511 + 111 * num_event_slots
            log(f"Siege machine will be placed at x={siege_placement_x}")
```

Verify this stays backward compatible: with one distinct event troop and no siege, `num_event_slots == 1`, heroes shift `+111`, and `siege_placement_x` resolves to 511 (no siege) or 622 (with siege) — identical to the old logic. With two event troops, heroes shift `+222` and siege sits at 733.

---

## Verification checklist (please confirm after editing)
1. With `CARD_EVENT_ACTIVE = False` and `CONFIG["event_troops"] = []`, the bot behaves exactly as before (diff the two branches to confirm the fallback code is untouched).
2. `phase3_wait_for_return` still returns `True` on normal battles and on treasure/claim_reward battles; the card branch only triggers when `claim_card.PNG` is on screen.
3. The card Continue click is `(997, 940)`, NOT the treasure `(955, 902)`.
4. In `phase2_execute`, hero and siege x-coordinates are correct for 0, 1, and 2 distinct event troops (heroes at base, +111, +222; siege at 511, 622, 733).
5. All TEMP CARD EVENT additions are inside the banner comments so they can be deleted in one pass.
6. No new imports or helpers introduced beyond what already exists in those methods.
