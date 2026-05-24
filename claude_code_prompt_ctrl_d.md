# Claude Code Prompt — Add Ctrl+D Disconnect to All Remaining Workers

## Context

`AutomationWorker.py` contains all QThread worker classes for the Autoclash bot.
Three workers already have Ctrl+D Remote Desktop disconnect support:
`ClanGamesWorker`, `ClanScouterWorker`, and `ClanCapitalWorker`.

The remaining workers do **not** have it. They use `home_space_listener.start()` or
`Autoclash_BB.space_listener.start()` for their space-stop mechanism, and never import
the `keyboard` module at all.

The task is to add Ctrl+D disconnect to the 7 remaining workers. Do not touch the 3 that
already have it. Do not change any automation logic whatsoever — only add keyboard hotkey
registration and cleanup.

---

## Workers to update

The following 7 workers need Ctrl+D added:

1. `HomeVillageWorker`
2. `FillAccountsWorker`
3. `CycleAccountsWorker`
4. `BuilderBaseWorker`
5. `BBFillAccountsWorker`
6. `ClanGamesMasterWorker`
7. `UpgradeAccountsWorker`

---

## Pattern to apply to each worker

For each worker, make exactly two changes to its `run()` method:

### Change 1 — Register Ctrl+D after the space listener starts

For `HomeVillageWorker`, `FillAccountsWorker`, `CycleAccountsWorker`,
`ClanGamesMasterWorker`, and `UpgradeAccountsWorker`, find the line:

```python
home_space_listener.start()
```

For `BuilderBaseWorker` and `BBFillAccountsWorker`, find the line:

```python
Autoclash_BB.space_listener.start()
```

Immediately **after** that line, insert the following block. Replace `WorkerName` with
the actual class name (e.g. `HomeVillageWorker`, `BuilderBaseWorker`, etc.):

```python
_ctrl_d_registered = False
try:
    import keyboard as _kb_disconnect
    def _on_disconnect():
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
    _kb_disconnect.add_hotkey("ctrl+d", _on_disconnect)
    _ctrl_d_registered = True
    log("WorkerName: Ctrl+D disconnect enabled")
except Exception:
    log("WorkerName: keyboard module unavailable; Ctrl+D disabled")
```

### Change 2 — Unregister Ctrl+D in the finally block

Each worker already has a `finally:` block. Find that block and add the following
**before** `bot_reporter.stop()` (or, if that call isn't present, before `self.finished.emit()`):

```python
if _ctrl_d_registered:
    try:
        import keyboard as _kb_disconnect
        _kb_disconnect.remove_hotkey("ctrl+d")
    except Exception:
        pass
```

---

## Important constraints

- **Do not** change anything in `ClanGamesWorker`, `ClanScouterWorker`, or
  `ClanCapitalWorker` — they already have Ctrl+D working correctly.
- **Do not** change any automation logic, signal connections, or worker behaviour.
- Each worker has exactly one `home_space_listener.start()` (or
  `Autoclash_BB.space_listener.start()`) call — insert immediately after that one call.
- Each worker has exactly one `finally:` block — add the cleanup there.
- Use `_kb_disconnect` as the import alias (not `_kb`) to avoid any name collision with
  existing `keyboard` imports in the same scope.
- `_ctrl_d_registered` must be initialised to `False` before the try block so the
  `finally` clause can safely reference it even if an exception occurs before
  `_ctrl_d_registered = True` is reached. In `HomeVillageWorker` and the other workers
  that have no existing `_keyboard_registered` variable, this is a brand new local variable
  — that is fine.
- After making all changes, do a quick scan to confirm each of the 7 workers has exactly
  one `Ctrl+D` registration and one cleanup, and that none of the original 3 workers were
  modified.
