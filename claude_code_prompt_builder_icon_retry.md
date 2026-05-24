# Claude Code Prompt — Increase Builder Icon Retry Attempts and Delay

## Context

In `capitalraider.py`, inside `dump_loot_into_home_capital`, the builder icon
search uses 5 attempts with a 0.5 second delay. Increase this to 10 attempts
with a 1.0 second delay to give the builder menu more time to appear after
entering a district.

## Change to make

Find:

```python
            builder_coords = _find_template_retry(TPL_BUILDER_ICON, attempts=5, delay=0.5)
```

Replace with:

```python
            builder_coords = _find_template_retry(TPL_BUILDER_ICON, attempts=10, delay=1.0)
```

## Important constraints

- This is the only call to `_find_template_retry(TPL_BUILDER_ICON` in the
  file — change only this one line.
- Do not change any other `_find_template_retry` calls or any other logic.
