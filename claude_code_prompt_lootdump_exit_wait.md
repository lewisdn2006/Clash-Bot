# Claude Code Prompt — Increase District Exit Wait in dump_loot_into_home_capital

## Context

`capitalraider.py` contains `dump_loot_into_home_capital`. Inside the district
iteration loop, when the bot decides to leave a district (either because the
builder icon was not found, or because no gold symbol was found in the builder
menu), it clicks `BOTTOM_LEFT_EXIT` and then waits `time.sleep(1.0)` before
breaking to the next district. This 1-second wait is too short — the capital
overview screen may not have fully settled before the next iteration runs its
overlay check. Increase both waits to 5 seconds.

## Changes to make

There are exactly two places inside `dump_loot_into_home_capital` where
`BOTTOM_LEFT_EXIT` is clicked before a `break`. Change both.

---

### Change 1 — Builder icon not found path

Find:

```python
            builder_coords = _find_template_retry(TPL_BUILDER_ICON, attempts=5, delay=0.5)
            if builder_coords is None:
                _status(status_fn, "LootDump", f"{district_name}: builder icon not found — moving to next district")
                Autoclash.click_with_jitter(*BOTTOM_LEFT_EXIT)
                time.sleep(1.0)
                break
```

Replace with:

```python
            builder_coords = _find_template_retry(TPL_BUILDER_ICON, attempts=5, delay=0.5)
            if builder_coords is None:
                _status(status_fn, "LootDump", f"{district_name}: builder icon not found — moving to next district")
                Autoclash.click_with_jitter(*BOTTOM_LEFT_EXIT)
                time.sleep(5.0)
                break
```

---

### Change 2 — Gold symbol not found (fully upgraded) path

Find:

```python
            if gold_coords is None:
                _status(status_fn, "LootDump", f"{district_name}: fully upgraded — exiting district")
                Autoclash.click_with_jitter(*BOTTOM_LEFT_EXIT)
                time.sleep(1.0)
                break
```

Replace with:

```python
            if gold_coords is None:
                _status(status_fn, "LootDump", f"{district_name}: fully upgraded — exiting district")
                Autoclash.click_with_jitter(*BOTTOM_LEFT_EXIT)
                time.sleep(5.0)
                break
```

---

## Important constraints

- Only change the two `time.sleep(1.0)` values listed above. Do not change
  any other sleeps in `capitalraider.py`.
- Do not change the `time.sleep(1.0)` inside `_exit_to_capital_overview`.
- Do not change any other logic, status messages, or function structure.
