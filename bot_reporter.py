"""
bot_reporter.py — Autoclash Monitor Status Reporter (D1 edition)
================================================================
Updated to work with the D1-backed Cloudflare Worker.
Key changes from KV edition:
  - FLUSH_INTERVAL reduced to 10 seconds (D1 handles the load)
  - session_id added so the worker can track separate sessions
  - report_battle_complete() now sends a 'battle' object for history storage
  - KV write-limit guard retained (as a safety net, though D1 won't hit it)
"""

import threading
import queue
import time
import uuid
import requests

# ── CONFIG ────────────────────────────────────────────────────────────────────
WORKER_URL  = "https://bot.lewisdn.com/update"
BOT_SECRET  = "clash-monitor-lewis123"
VERSION     = "2.0"
FLUSH_INTERVAL = 10   # seconds — safe with D1 (100k writes/day free)
# ─────────────────────────────────────────────────────────────────────────────

# Unique ID for this bot session (reset each time start() is called)
_session_id: str = ""

_queue: queue.Queue = queue.Queue()
_lock  = threading.Lock()

_session_data: dict = {
    "phase":           "—",
    "message":         "—",
    "current_account": None,
    "account_attacks":  0,
    "account_gold":     0,
    "account_elixir":   0,
    "account_dark":     0,
    "account_upgrades": 0,
    "log_message":     None,
    "version":         VERSION,
}

_running:       bool = False
_thread:        threading.Thread | None = None
_kv_limit_hit:  bool = False   # safety net — shouldn't fire with D1
_account_totals: dict = {}  # {account_name: {gold, elixir, dark, attacks}}

# Callbacks registered by the bot for each command type.
# Keys: 'hard_reset' | 'pause' | 'resume' | 'stop'
# Values: callable with no arguments
_command_callbacks: dict = {}


def _send(payload: dict) -> None:
    """POST a single payload to the Cloudflare Worker."""
    global _kv_limit_hit
    if _kv_limit_hit:
        return
    try:
        payload["session_id"] = _session_id
        resp = requests.post(
            WORKER_URL,
            json=payload,
            headers={
                "Content-Type":  "application/json",
                "X-Bot-Secret":  BOT_SECRET,
            },
            timeout=8,
        )
        if resp.status_code == 400 and "KV put() limit exceeded" in resp.text:
            _kv_limit_hit = True
            print(
                "[Reporter] ⚠ Daily write limit reached — "
                "dashboard reporting disabled until midnight. Bot continues normally."
            )
            return
        if resp.status_code != 200:
            print(f"[Reporter] Worker returned {resp.status_code}: {resp.text[:120]}")
    except Exception as exc:
        print(f"[Reporter] Failed to send update: {exc}")


def _poll_commands() -> None:
    """Poll the worker for any pending dashboard commands and execute them."""
    global _kv_limit_hit
    if _kv_limit_hit:
        return
    try:
        resp = requests.post(
            WORKER_URL.replace('/update', '/api/poll-command'),
            json={},
            headers={
                'Content-Type': 'application/json',
                'X-Bot-Secret': BOT_SECRET,
            },
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            command = data.get('command')
            if command:
                print(f'[Reporter] Dashboard command received: {command}')
                cb = _command_callbacks.get(command)
                if cb:
                    try:
                        cb()
                    except Exception as exc:
                        print(f'[Reporter] Command callback error for {command!r}: {exc}')
                else:
                    print(f'[Reporter] No callback registered for command: {command!r}')
    except Exception as exc:
        print(f'[Reporter] Poll command failed: {exc}')


def _flush_worker() -> None:
    """Background thread — flushes the queue every FLUSH_INTERVAL seconds."""
    global _running
    last_flush: float = 0.0
    last_poll: float = 0.0
    pending_log: str | None = None
    pending_battle: dict | None = None

    while _running:
        # Drain the queue
        try:
            while True:
                item = _queue.get_nowait()
                if item.get("log_message"):
                    pending_log = item["log_message"]
                if item.get("battle"):
                    pending_battle = item["battle"]
                with _lock:
                    _session_data.update(
                        {k: v for k, v in item.items()
                         if v is not None and k not in ("log_message", "battle")}
                    )
        except queue.Empty:
            pass

        now = time.time()
        if now - last_flush >= FLUSH_INTERVAL and not _kv_limit_hit:
            with _lock:
                payload = dict(_session_data)
            if pending_log:
                payload["log_message"] = pending_log
                pending_log = None
            if pending_battle:
                payload["battle"] = pending_battle
                pending_battle = None
            _send(payload)
            last_flush = now

        if now - last_poll >= 10:
            _poll_commands()
            last_poll = now

        time.sleep(1)


# ── Public API ────────────────────────────────────────────────────────────────

def start() -> None:
    """Start the reporter. Call once when the bot starts."""
    global _running, _thread, _kv_limit_hit, _session_id, _account_totals
    if _running:
        return
    _kv_limit_hit   = False
    _session_id     = str(uuid.uuid4())[:16]   # short unique session ID
    _account_totals = {}
    _command_callbacks.clear()
    _running        = True

    # Signal session reset to the worker
    _send({"reset_session": True, "version": VERSION})

    _thread = threading.Thread(target=_flush_worker, daemon=True)
    _thread.start()
    print(f"[Reporter] Started — session {_session_id}")


def stop() -> None:
    """Stop the reporter. Call when the bot stops."""
    global _running
    _running = False
    print("[Reporter] Stopped.")


def register_command_callback(command: str, fn) -> None:
    """Register a callback to be called when a dashboard command is received.

    Example:
        bot_reporter.register_command_callback('hard_reset', my_reset_fn)
        bot_reporter.register_command_callback('pause', my_pause_fn)
    """
    _command_callbacks[command] = fn


def update_phase(phase: str, message: str = "") -> None:
    """Call whenever the bot changes phase."""
    _queue.put({"phase": phase, "message": message})


def update_account(account_name: str) -> None:
    """Call whenever the active account changes."""
    _queue.put({"current_account": account_name})


def update_account_stats(
    account_name: str,
    attacks:  int | None = None,
    gold:     int | None = None,
    elixir:   int | None = None,
    dark:     int | None = None,
    upgrades: int | None = None,
) -> None:
    """Call after each battle or upgrade with the account's running totals."""
    payload: dict = {"current_account": account_name}
    if attacks  is not None: payload["account_attacks"]  = attacks
    if gold     is not None: payload["account_gold"]     = gold
    if elixir   is not None: payload["account_elixir"]   = elixir
    if dark     is not None: payload["account_dark"]     = dark
    if upgrades is not None: payload["account_upgrades"] = upgrades
    _queue.put(payload)


def log(message: str) -> None:
    """Send a key log message to the dashboard (don't call for every line)."""
    _queue.put({"log_message": message})


def report_battle_complete(
    account_name: str,
    gold:         int,
    elixir:       int,
    dark:         int,
    total_attacks: int,
    walls:        int = 0,
    stars:        int = 0,
) -> None:
    """
    Call at the end of each battle.
    Sends both the running account totals (for the live table)
    AND a 'battle' object (for D1 history storage).
    """
    acc = _account_totals.setdefault(account_name, {'gold': 0, 'elixir': 0, 'dark': 0, 'attacks': 0})
    acc['gold']    += gold
    acc['elixir']  += elixir
    acc['dark']    += dark
    acc['attacks']  = total_attacks  # total_attacks is already cumulative from the caller
    update_account_stats(
        account_name=account_name,
        attacks=acc['attacks'],
        gold=acc['gold'],
        elixir=acc['elixir'],
        dark=acc['dark'],
    )
    # Queue individual battle record for D1 history
    _queue.put({
        "battle": {
            "account":     account_name,
            "gold":        gold,
            "elixir":      elixir,
            "dark_elixir": dark,
            "walls":       walls,
            "stars":       stars,
        }
    })
    log(f"Battle — {account_name} | G:{gold:,} E:{elixir:,} D:{dark} {stars}★")


def report_upgrade(
    account_name:   str,
    upgrade_type:   str,
    total_upgrades: int,
) -> None:
    """Call after each upgrade."""
    update_account_stats(account_name=account_name, upgrades=total_upgrades)
    log(f"Upgrade: {upgrade_type} — {account_name} (total: {total_upgrades})")


def report_error(message: str) -> None:
    """Call when an error occurs — shows in red on the dashboard."""
    update_phase("ERROR", message)
    log(f"ERROR: {message}")
