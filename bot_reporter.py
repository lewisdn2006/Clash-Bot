"""
bot_reporter.py — Autoclash Monitor Status Reporter
====================================================
Drop this file into your Clash Bot folder.
Import it in AutomationWorker.py and call the functions below
to send live status updates to your dashboard at lewisdn.com.

Setup:
  1. Set WORKER_URL to your Cloudflare Worker URL
  2. Set BOT_SECRET to match the secret in your worker.js
  3. Import and call the functions from AutomationWorker.py
"""

import threading
import queue
import time
import requests
from datetime import datetime

# ── CONFIG ────────────────────────────────────────────────────────────────────
WORKER_URL = "https://autoclash-monitor.lewisdn2006.workers.dev/update"
BOT_SECRET = "clash-monitor-lewis123"   # must match worker.js
VERSION = "1.0"

# How often to flush the queue and send updates (seconds)
FLUSH_INTERVAL = 8
# ─────────────────────────────────────────────────────────────────────────────

_queue = queue.Queue()
_lock = threading.Lock()
_session_data = {
    "phase": "—",
    "message": "—",
    "current_account": None,
    "account_attacks": 0,
    "account_gold": 0,
    "account_elixir": 0,
    "account_dark": 0,
    "account_upgrades": 0,
    "log_message": None,
    "version": VERSION,
}

_running = False
_thread = None


def _send(payload: dict):
    """Send a single payload to the Cloudflare Worker."""
    try:
        resp = requests.post(
            WORKER_URL,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "X-Bot-Secret": BOT_SECRET,
            },
            timeout=8,
        )
        if resp.status_code != 200:
            print(f"[Reporter] Worker returned {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        print(f"[Reporter] Failed to send update: {e}")


def _flush_worker():
    """Background thread — flushes status every FLUSH_INTERVAL seconds."""
    global _running
    last_flush = 0
    pending_log = None

    while _running:
        # Drain the queue
        try:
            while True:
                item = _queue.get_nowait()
                if item.get("log_message"):
                    pending_log = item["log_message"]
                with _lock:
                    _session_data.update({k: v for k, v in item.items() if v is not None})
        except queue.Empty:
            pass

        now = time.time()
        if now - last_flush >= FLUSH_INTERVAL:
            with _lock:
                payload = dict(_session_data)
            if pending_log:
                payload["log_message"] = pending_log
                pending_log = None
            _send(payload)
            last_flush = now

        time.sleep(1)


def start():
    """Start the background reporter thread. Call once when bot starts."""
    global _running, _thread
    if _running:
        return
    _running = True
    # Signal a session reset to clear old data on the dashboard
    _send({"reset_session": True, "version": VERSION})
    _thread = threading.Thread(target=_flush_worker, daemon=True)
    _thread.start()
    print("[Reporter] Status reporter started.")


def stop():
    """Stop the reporter thread. Call when bot stops."""
    global _running
    _running = False
    print("[Reporter] Status reporter stopped.")


def update_phase(phase: str, message: str = ""):
    """Call whenever the bot changes phase."""
    _queue.put({"phase": phase, "message": message})


def update_account(account_name: str):
    """Call whenever the active account changes."""
    _queue.put({"current_account": account_name})


def update_account_stats(
    account_name: str,
    attacks: int = None,
    gold: int = None,
    elixir: int = None,
    dark: int = None,
    upgrades: int = None,
):
    """Call after each battle or upgrade with the account's running totals."""
    payload = {"current_account": account_name}
    if attacks is not None:
        payload["account_attacks"] = attacks
    if gold is not None:
        payload["account_gold"] = gold
    if elixir is not None:
        payload["account_elixir"] = elixir
    if dark is not None:
        payload["account_dark"] = dark
    if upgrades is not None:
        payload["account_upgrades"] = upgrades
    _queue.put(payload)


def log(message: str):
    """
    Mirror important log messages to the dashboard.
    Don't call this for every single log line — just key events.
    The bot's existing log() function is separate; call this selectively.
    """
    _queue.put({"log_message": message})


def report_battle_complete(account_name: str, gold: int, elixir: int, dark: int, total_attacks: int):
    """Convenience function — call at the end of each battle."""
    update_account_stats(
        account_name=account_name,
        attacks=total_attacks,
        gold=gold,
        elixir=elixir,
        dark=dark,
    )
    log(f"Battle complete — {account_name} | G:{gold:,} E:{elixir:,} D:{dark}")


def report_upgrade(account_name: str, upgrade_type: str, total_upgrades: int):
    """Convenience function — call after each upgrade."""
    update_account_stats(account_name=account_name, upgrades=total_upgrades)
    log(f"Upgrade: {upgrade_type} — {account_name} (total: {total_upgrades})")


def report_error(message: str):
    """Call when an error occurs so it shows in red on the dashboard."""
    update_phase("ERROR", message)
    log(f"ERROR: {message}")
