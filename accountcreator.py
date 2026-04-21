#!/usr/bin/env python3
"""
Clash of Clans — Automated Account Creator
===========================================
Automates the full new-account creation flow in Clash of Clans, assigns a
Supercell ID (Gmail), and records the new account in created_accounts.json
and APPROVED_ACCOUNTS in Autoclash.py.

Required packages (install with pip):
    pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib pyperclip

Usage:
    Instantiate AccountCreator() and call .run().
    The Gmail API must be authorised first — run gmail_auth_setup.py once.

Controls:
    Press SPACE at any time to pause/resume the bot.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
import random
from pathlib import Path
from typing import Optional

import pyautogui

# ---------------------------------------------------------------------------
# Path setup — allows this module to be imported from any working directory
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPT_DIR))

# ---------------------------------------------------------------------------
# Import shared helpers from Autoclash
# ---------------------------------------------------------------------------
from Autoclash import (
    CONFIG,
    log,
    click_with_jitter,
    random_delay,
    add_jitter,
    find_template,
    scroll_down_5_times,
    get_screen_center,
    WHEEL_DELTA,
    _send_wheel,
)

# ---------------------------------------------------------------------------
# Optional keyboard module for space-key pause
# ---------------------------------------------------------------------------
try:
    import keyboard as _keyboard
    _HAS_KEYBOARD = True
except ImportError:
    _HAS_KEYBOARD = False

# Optional pynput keyboard controller for reliable code entry in Step 14
try:
    from pynput.keyboard import Controller as _PynputController
    _HAS_PYNPUT = True
except ImportError:
    _HAS_PYNPUT = False

# ---------------------------------------------------------------------------
# Gmail API imports (optional — deferred so the module still loads without them)
# ---------------------------------------------------------------------------
try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as GoogleRequest
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build as google_build
    HAS_GMAIL = True
except ImportError:
    HAS_GMAIL = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ACCOUNTS_JSON = _SCRIPT_DIR / "created_accounts.json"
CREDENTIALS_JSON = _SCRIPT_DIR / "credentials.json"
TOKEN_JSON = _SCRIPT_DIR / "token.json"

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# Region used for the account-switch / Supercell-ID panel (same as AutomationWorker)
_REGISTER_SCROLL_BOX = (1321, 496, 1917, 1080)

# Build-confirm template search parameters
_BUILD_CONFIRM_TEMPLATE = "build_confirm.png"
_BUILD_CONFIRM_THRESHOLD = 0.75
_BUILD_CONFIRM_MAX_ATTEMPTS = 30
_BUILD_CONFIRM_POLL = 0.5

# Shop icon template — polled before every shop click
_SHOP_ICON_TEMPLATE = "shop_icon.png"
_SHOP_ICON_THRESHOLD = 0.75
_SHOP_ICON_MAX_WAIT = 30   # seconds

# Name prefix
_NAME_PREFIX = "DJBillGates"
_EMAIL_PREFIX = "lewis"
_EMAIL_DOMAIN = "@lewisdn.com"
_NUMBER_START = 38

# Dialogue verification template — checked before every skip/continue click
_DIALOGUE_TEMPLATE = "dialogue.png"
_DIALOGUE_TIMEOUT = 30  # seconds to wait for dialogue to appear

# Town Hall template used in Step 10 upgrade flow
_TH1_TEMPLATE = "th1.png"


# ============================================================================
# Step verification error
# ============================================================================

class StepVerificationError(Exception):
    """Raised when a pre-click template check times out, indicating the
    expected screen state was not reached within the allowed window."""


# ============================================================================
# Space-key pause/resume
# ============================================================================

_paused: bool = False
_pause_handler = None
_skip_step_requested: bool = False
_skip_handler = None


def _on_space_pressed(_event=None) -> None:
    """Toggle the global pause flag when Space is pressed."""
    global _paused
    _paused = not _paused
    if _paused:
        log("AccountCreator: *** PAUSED — press SPACE to resume ***")
    else:
        log("AccountCreator: *** RESUMED ***")


def _on_right_pressed(_event=None) -> None:
    """Request skipping the current step when Right Arrow is pressed."""
    global _skip_step_requested
    _skip_step_requested = True
    log("AccountCreator: >>> SKIP REQUESTED — advancing to next step <<<")


def start_pause_listener() -> None:
    """Register the Space key listener.  Safe to call multiple times."""
    global _pause_handler, _skip_handler
    if not _HAS_KEYBOARD:
        log("AccountCreator: 'keyboard' module not installed — space pause disabled")
        log("AccountCreator: Install with: pip install keyboard")
        return
    if _pause_handler is None:
        _pause_handler = _keyboard.on_press_key("space", _on_space_pressed, suppress=False)
    if _skip_handler is None:
        _skip_handler = _keyboard.on_press_key("right", _on_right_pressed, suppress=False)
    log("AccountCreator: Keyboard controls active (SPACE pause/resume, RIGHT ARROW skip step)")


def stop_pause_listener() -> None:
    """Unregister the Space key listener."""
    global _pause_handler, _skip_handler
    if _HAS_KEYBOARD:
        if _pause_handler is not None:
            try:
                _keyboard.unhook(_pause_handler)
            except Exception:
                pass
            _pause_handler = None
        if _skip_handler is not None:
            try:
                _keyboard.unhook(_skip_handler)
            except Exception:
                pass
            _skip_handler = None


class StepSkipRequested(Exception):
    """Raised when the user requests skipping the current step."""


def _check_skip_request() -> None:
    """Raise StepSkipRequested if a skip has been requested via keyboard."""
    global _skip_step_requested
    if _skip_step_requested:
        _skip_step_requested = False
        raise StepSkipRequested("Skip requested by user via Right Arrow")


def _check_pause() -> None:
    """Block here while the bot is paused.  Called before every action."""
    while _paused:
        time.sleep(0.1)
    _check_skip_request()


# ============================================================================
# Gmail helpers
# ============================================================================

def get_gmail_service():
    """
    Return an authorised Gmail API service object.

    On the first run this opens a browser for OAuth2 consent and saves
    token.json.  Subsequent calls load token.json directly.

    Raises RuntimeError if google-auth packages are not installed.
    """
    if not HAS_GMAIL:
        raise RuntimeError(
            "Google API packages are not installed.  Run:\n"
            "  pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
        )

    creds: Optional[Credentials] = None

    if TOKEN_JSON.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_JSON), GMAIL_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GoogleRequest())
        else:
            if not CREDENTIALS_JSON.exists():
                raise FileNotFoundError(
                    f"credentials.json not found at {CREDENTIALS_JSON}.\n"
                    "Download it from Google Cloud Console → APIs & Services → Credentials."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_JSON), GMAIL_SCOPES
            )
            creds = flow.run_local_server(port=0)

        TOKEN_JSON.write_text(creds.to_json(), encoding="utf-8")
        log(f"Gmail: token saved to {TOKEN_JSON}")

    service = google_build("gmail", "v1", credentials=creds)
    log("Gmail: service created successfully")
    return service


def wait_for_verification_code(
    service,
    timeout: int = 120,
    poll_interval: int = 5,
    after_epoch: Optional[int] = None,
) -> Optional[str]:
    """
    Wait for a Supercell verification email and extract the 6-digit code.

    Polls for Supercell emails containing a 6-digit code.

    If *after_epoch* is provided, only messages received after that UNIX
    timestamp are considered.

    Checks the subject first (code appears as [123456]) then falls back to
    the full decoded body.

    Returns the code string, or None on timeout.
    """
    query = "from:supercell"
    if after_epoch is not None:
        query = f"from:supercell after:{int(after_epoch)}"
        log(f"Gmail: Polling with time filter after UNIX {int(after_epoch)}")
    else:
        log("Gmail: Polling without time filter (after_epoch not set)")

    deadline = time.time() + timeout
    elapsed = 0
    while time.time() < deadline:
        time.sleep(poll_interval)
        elapsed += poll_interval
        remaining = int(deadline - time.time())
        log(f"Gmail: Polling for verification email... ({elapsed}s elapsed, ~{remaining}s remaining)")
        log(f"Gmail: Query filter in use: {query!r}")
        try:
            result = service.users().messages().list(
                userId="me", q=query, maxResults=10
            ).execute()
            messages = result.get("messages", [])
            log(f"Gmail: {len(messages)} Supercell message(s) visible in inbox")
            for msg in messages:
                log(f"Gmail: New message found (id={msg['id']}) — fetching full content")
                full_msg = service.users().messages().get(
                    userId="me", id=msg["id"], format="full"
                ).execute()

                if after_epoch is not None:
                    internal_ms = int(full_msg.get("internalDate", "0") or 0)
                    msg_epoch = internal_ms // 1000
                    if msg_epoch <= int(after_epoch):
                        log(
                            f"Gmail: Skipping message id={msg['id']} (received at {msg_epoch}, "
                            f"not after {int(after_epoch)})"
                        )
                        continue

                code = _extract_code_from_message(full_msg)
                if code:
                    log(f"Gmail: Verification code found: {code}")
                    return code
                else:
                    log("Gmail: New message did not contain a 6-digit code, continuing to poll")
        except Exception as exc:
            log(f"Gmail: Error while polling: {exc}")

    log("Gmail: Timeout — no verification code found within the deadline")
    return None


def _extract_code_from_message(full_msg: dict) -> Optional[str]:
    """Try subject first, then full body, to find a 6-digit code."""
    payload = full_msg.get("payload", {})
    headers = {h["name"]: h["value"] for h in payload.get("headers", [])}
    subject = headers.get("Subject", "")
    sender = headers.get("From", "")

    log(f"Gmail: Checking message — From: {sender!r}  Subject: {subject!r}")

    # Check subject first — Supercell puts the code in [123456] brackets
    code = _find_code_in_text(subject)
    if code:
        log(f"Gmail: Code found in subject: {subject!r}")
        return code

    # Fall back to body
    body_text = _decode_body(payload)
    if body_text:
        code = _find_code_in_text(body_text)
        if code:
            log("Gmail: Code found in email body (not in subject)")
            return code
        else:
            log("Gmail: No 6-digit code found in subject or body of this message")

    return None


def _find_code_in_text(text: str) -> Optional[str]:
    """Return a 6-digit code from text, supporting both 123456 and 123 456 forms."""
    # Prefer bracketed formats used in Supercell subjects, including spaced form [123 456].
    m = re.search(r"\[(\d{3})\s*(?:[-\s])?\s*(\d{3})\]", text)
    if m:
        code = m.group(1) + m.group(2)
        if code != "000000":
            return code

    # Plain compact 6-digit code.
    m = re.search(r"\b(\d{6})\b", text)
    if m:
        code = m.group(1)
        if code != "000000":
            return code

    # Spaced/hyphenated code in body text (e.g. "647 815" or "647-815").
    m = re.search(r"\b(\d{3})\s*[-\s]\s*(\d{3})\b", text)
    if m:
        code = m.group(1) + m.group(2)
        if code != "000000":
            return code

    return None


def _decode_body(payload: dict) -> str:
    """Recursively decode the email body from a Gmail API message payload."""
    parts = payload.get("parts", [])
    if parts:
        texts = []
        for part in parts:
            texts.append(_decode_body(part))
        return "\n".join(texts)
    data = payload.get("body", {}).get("data", "")
    if data:
        try:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
        except Exception:
            pass
    return ""


# ============================================================================
# Account JSON helpers
# ============================================================================

def _load_accounts() -> list:
    if ACCOUNTS_JSON.exists():
        try:
            return json.loads(ACCOUNTS_JSON.read_text(encoding="utf-8"))
        except Exception as exc:
            log(f"AccountCreator: Warning — could not parse {ACCOUNTS_JSON}: {exc}")
    return []


def _save_accounts(accounts: list) -> None:
    ACCOUNTS_JSON.write_text(json.dumps(accounts, indent=2), encoding="utf-8")
    log(f"AccountCreator: Saved {len(accounts)} account(s) to {ACCOUNTS_JSON}")


def _next_account_number(accounts: list) -> int:
    """Return the lowest integer >= _NUMBER_START not already in accounts."""
    used = {a.get("number") for a in accounts if isinstance(a.get("number"), int)}
    n = _NUMBER_START
    while n in used:
        n += 1
    return n


def _add_to_approved_accounts(name: str) -> None:
    """
    Insert *name* (lowercase) into the APPROVED_ACCOUNTS set literal in
    Autoclash.py.  Reads the file, finds the set definition by regex, adds
    the new entry, and rewrites the file.
    """
    autoclash_path = _SCRIPT_DIR / "Autoclash.py"
    if not autoclash_path.exists():
        log(f"AccountCreator: WARNING — Autoclash.py not found at {autoclash_path}")
        return

    source = autoclash_path.read_text(encoding="utf-8")
    name_lower = name.lower()

    # Match: APPROVED_ACCOUNTS = {"...", "...", ...}
    pattern = r"(APPROVED_ACCOUNTS\s*=\s*\{)([^}]*?)(\})"
    match = re.search(pattern, source, re.DOTALL)
    if not match:
        log("AccountCreator: WARNING — Could not find APPROVED_ACCOUNTS set in Autoclash.py")
        return

    set_contents = match.group(2)
    if f'"{name_lower}"' in set_contents or f"'{name_lower}'" in set_contents:
        log(f"AccountCreator: '{name_lower}' already in APPROVED_ACCOUNTS, skipping")
        return

    stripped = set_contents.rstrip().rstrip(",")
    new_contents = stripped + f', "{name_lower}"'
    new_source = source[:match.start()] + match.group(1) + new_contents + match.group(3) + source[match.end():]
    autoclash_path.write_text(new_source, encoding="utf-8")
    log(f"AccountCreator: Added '{name_lower}' to APPROVED_ACCOUNTS in Autoclash.py")


# ============================================================================
# Low-level click/input helpers
# ============================================================================

def _click(x: int, y: int, label: str = "") -> None:
    """Click with jitter, checking for pause first and logging the action."""
    _check_pause()
    desc = f" ({label})" if label else ""
    log(f"AccountCreator: Clicking ({x}, {y}){desc}")
    click_with_jitter(x, y)


def _wait(seconds: float, reason: str = "") -> None:
    """Sleep in small intervals so pause checks happen during long waits."""
    desc = f" — {reason}" if reason else ""
    log(f"AccountCreator: Waiting {seconds}s{desc}")
    end = time.time() + seconds
    while time.time() < end:
        _check_pause()
        remaining = end - time.time()
        if remaining <= 0:
            break
        time.sleep(min(0.1, remaining))


def _scroll_down_once_in_register_box() -> None:
    """Scroll down one tick inside the Supercell-ID panel."""
    _check_pause()
    x1, y1, x2, y2 = _REGISTER_SCROLL_BOX
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2
    pyautogui.moveTo(cx, cy, duration=0.1)
    delta = abs(int(WHEEL_DELTA))
    try:
        _send_wheel(-delta)
    except Exception:
        pyautogui.scroll(-1)
    time.sleep(0.5)


def _wait_for_shop_icon(timeout: int = _SHOP_ICON_MAX_WAIT) -> bool:
    """
    Poll until shop_icon.png is visible on screen before opening the shop.
    Returns True if found, False on timeout.
    """
    log(f"AccountCreator: Waiting for shop_icon.png to appear (max {timeout}s)...")
    deadline = time.time() + timeout
    attempt = 0
    while time.time() < deadline:
        _check_pause()
        attempt += 1
        coords = find_template(_SHOP_ICON_TEMPLATE, confidence=_SHOP_ICON_THRESHOLD)
        if coords:
            log(f"AccountCreator: shop_icon.png visible at {coords} (attempt {attempt})")
            return True
        time.sleep(1.0)
    log(f"AccountCreator: WARNING — shop_icon.png not found after {timeout}s — proceeding anyway")
    return False


def _search_and_click_build_confirm() -> bool:
    """
    Poll repeatedly for build_confirm.png and click it when found.
    Returns True if clicked, False after max attempts.
    """
    log(f"AccountCreator: Polling for {_BUILD_CONFIRM_TEMPLATE} (max {_BUILD_CONFIRM_MAX_ATTEMPTS} attempts)...")
    for attempt in range(1, _BUILD_CONFIRM_MAX_ATTEMPTS + 1):
        _check_pause()
        coords = find_template(_BUILD_CONFIRM_TEMPLATE, confidence=_BUILD_CONFIRM_THRESHOLD)
        if coords:
            log(f"AccountCreator: build_confirm found at {coords} (attempt {attempt}/{_BUILD_CONFIRM_MAX_ATTEMPTS})")
            _click(*coords, label="build_confirm")
            random_delay()
            return True
        log(f"AccountCreator: build_confirm not found (attempt {attempt}/{_BUILD_CONFIRM_MAX_ATTEMPTS}), retrying...")
        time.sleep(_BUILD_CONFIRM_POLL)
    log(f"AccountCreator: WARNING — {_BUILD_CONFIRM_TEMPLATE} not found after {_BUILD_CONFIRM_MAX_ATTEMPTS} attempts")
    return False


def _wait_and_click_return_button(zoom_out_after: bool = False) -> None:
    """
    Block until return_button.png is visible and click it.
    If zoom_out_after=True, scrolls down 5 times after clicking to zoom the view out.
    """
    log("AccountCreator: Waiting for return_button.png (no timeout)...")
    attempt = 0
    while True:
        _check_pause()
        attempt += 1
        coords = find_template(CONFIG.get("return_button", "return_button.png"), confidence=0.75)
        if coords:
            log(f"AccountCreator: return_button found at {coords} (attempt {attempt})")
            _click(*coords, label="return_button")
            random_delay()
            if zoom_out_after:
                log("AccountCreator: Zooming out after battle return...")
                _wait(1.5, "settling before zoom")
                scroll_down_5_times()
                log("AccountCreator: Zoom out complete")
            return
        if attempt % 10 == 0:
            log(f"AccountCreator: Still waiting for return_button ({attempt} checks so far)...")
        time.sleep(1.0)


def _wait_for_template(template: str, timeout: int = 30, label: str = "") -> tuple:
    """
    Poll until *template* is visible on screen, then return its (x, y) centre.
    Raises StepVerificationError if not found within *timeout* seconds.
    The wait happens on top of whatever delay the caller already uses — the
    existing timing is preserved because this only adds extra time when the
    screen hasn't loaded yet.
    """
    desc = label or template
    log(f"AccountCreator: Verifying {desc} is on screen (max {timeout}s)...")
    deadline = time.time() + timeout
    attempt = 0
    while time.time() < deadline:
        _check_pause()
        attempt += 1
        coords = find_template(template, confidence=0.75)
        if coords:
            log(f"AccountCreator: {desc} confirmed at {coords} (attempt {attempt})")
            return coords
        time.sleep(1.0)
    msg = f"{desc} not visible after {timeout}s — step verification failed"
    log(f"AccountCreator: ERROR — {msg}")
    raise StepVerificationError(msg)


def _wait_for_template_in_box(
    template: str,
    search_box: tuple,
    timeout: int = 30,
    label: str = "",
) -> tuple:
    """Poll until *template* is visible inside *search_box* (x1, y1, x2, y2)."""
    desc = label or template
    log(f"AccountCreator: Verifying {desc} in box {search_box} (max {timeout}s)...")
    deadline = time.time() + timeout
    attempt = 0
    while time.time() < deadline:
        _check_pause()
        attempt += 1
        coords = find_template(template, confidence=0.75, search_box=search_box)
        if coords:
            log(f"AccountCreator: {desc} confirmed at {coords} in region (attempt {attempt})")
            return coords
        time.sleep(1.0)
    msg = f"{desc} not visible in region after {timeout}s — step verification failed"
    log(f"AccountCreator: ERROR — {msg}")
    raise StepVerificationError(msg)


def _skip_dialogue(x: int = 945, y: int = 321, label: str = "skip/continue dialogue") -> None:
    """Click the standard skip/continue dialogue coordinate once.
    Waits for dialogue.png to be visible first so the click only fires when
    the dialogue has actually loaded."""
    _wait_for_template(_DIALOGUE_TEMPLATE, timeout=_DIALOGUE_TIMEOUT, label="dialogue box")
    _click(x, y, label=label)
    random_delay()


def _open_shop(label: str = "shop button") -> None:
    """Wait for the shop icon to be visible, then click to open the shop."""
    log(f"AccountCreator: Opening shop — {label}")
    _wait_for_shop_icon()
    _click(1810, 965, label="shop button")
    _wait(2, "shop opening")


def _hold_click(x: int, y: int, duration: float, label: str = "") -> None:
    """Press and hold the mouse button at (x, y) for *duration* seconds."""
    _check_pause()
    desc = f" ({label})" if label else ""
    log(f"AccountCreator: Holding click at ({x}, {y}){desc} for {duration}s")
    jx, jy = add_jitter(x, y)
    pyautogui.moveTo(jx, jy, duration=0.1)
    pyautogui.mouseDown()
    time.sleep(duration)
    pyautogui.mouseUp()
    log(f"AccountCreator: Hold-click at ({x}, {y}) released")


def _find_login_register_with_scroll() -> Optional[tuple]:
    """
    Search for login_register.png inside the Supercell-ID scroll panel.
    Scrolls down if not found, keeps retrying until found.
    Returns (x, y) centre coordinates.
    """
    log("AccountCreator: Searching for login_register.png (with scroll if needed)...")
    max_scrolls = 100
    for i in range(max_scrolls):
        _check_pause()
        coords = find_template("login_register.png", confidence=0.95)
        if coords:
            log(f"AccountCreator: login_register.png found at {coords} (scroll #{i})")
            return coords
        log(f"AccountCreator: login_register.png not visible — scrolling down (scroll {i+1}/{max_scrolls})")
        _scroll_down_once_in_register_box()
    # One final attempt after scrolling
    coords = find_template("login_register.png", confidence=0.95)
    if coords:
        log(f"AccountCreator: login_register.png found at {coords} (final attempt after {max_scrolls} scrolls)")
    else:
        log(f"AccountCreator: WARNING — login_register.png not found after {max_scrolls} scroll attempts")
    return coords


# ============================================================================
# AccountCreator
# ============================================================================

class AccountCreator:
    """
    Automates the full Clash of Clans new-account creation + Supercell ID flow.

    Usage:
        service = get_gmail_service()
        creator = AccountCreator(service)
        creator.run()
    """

    def __init__(self, gmail_service):
        self._service = gmail_service
        self._verification_search_after: Optional[int] = None

        accounts = _load_accounts()
        self._number = _next_account_number(accounts)
        self._name = f"{_NAME_PREFIX}{self._number:02d}"
        self._email = f"{_EMAIL_PREFIX}{self._number}{_EMAIL_DOMAIN}"
        log(
            f"AccountCreator: Prepared account #{self._number} — "
            f"name='{self._name}', email='{self._email}'"
        )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Execute all 16 steps of the account creation flow.

        Retry logic on StepVerificationError:
          - If step N fails, re-run step N-1 (to re-establish the expected
            screen state), then retry step N.
          - If step N-1 also fails, log the failure and advance to step N+1
            (skipping the stuck step) so the bot keeps going rather than
            hanging forever.
          - Any non-verification exception (real crash) propagates immediately.
        """
        log("AccountCreator: ===== Starting account creation flow =====")
        log("AccountCreator: Press SPACE to pause/resume; press RIGHT ARROW to skip current step")
        start_pause_listener()

        _steps = [
            self._step1_logout,
            self._step2_guest_session,
            self._step3_dialogue_and_zoom,
            self._step4_place_cannon,
            self._step5_goblin_attack,
            self._step6_resource_buildings,
            self._step7_train_army,
            self._step8_tutorial_battle,
            self._step9_enter_name,
            self._step10_upgrade_town_hall,
            self._step11_build_menu_intro,
            self._step12_assign_supercell_id,
            self._step13_enter_email,
            self._step14_verification_code,
            self._step15_finish_registration,
            self._step16_save_account,
        ]

        try:
            i = 0
            while i < len(_steps):
                step_num = i + 1
                log(f"AccountCreator: ===== Executing step {step_num}/16 =====")
                try:
                    _steps[i]()
                    i += 1  # step succeeded — move forward
                except StepSkipRequested as exc:
                    log(f"AccountCreator: Step {step_num} skipped by user ({exc})")
                    i += 1
                except StepVerificationError as exc:
                    log(f"AccountCreator: Step {step_num} verification failed: {exc}")
                    if i > 0:
                        back_num = step_num - 1
                        log(
                            f"AccountCreator: --- Retry: going back to step {back_num} "
                            f"to re-establish expected state ---"
                        )
                        try:
                            _steps[i - 1]()
                            log(
                                f"AccountCreator: Back-step {back_num} succeeded "
                                f"— re-attempting step {step_num}"
                            )
                            # i is unchanged — the while loop will retry step N
                        except StepVerificationError as back_exc:
                            log(
                                f"AccountCreator: Back-step {back_num} also failed "
                                f"({back_exc}) — advancing past step {step_num}"
                            )
                            i += 1  # skip the stuck step and keep going
                    else:
                        log(
                            f"AccountCreator: Step 1 failed with no previous step "
                            f"to retry — advancing to step 2"
                        )
                        i += 1
        finally:
            stop_pause_listener()

        log(f"AccountCreator: ===== Account '{self._name}' created successfully =====")

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------

    def _step1_logout(self) -> None:
        log("AccountCreator: ---- Step 1: Log out of current account ----")
        _click(1858, 852, label="open settings menu"); _wait(2, "settings menu opening")
        _click(1423, 231, label="account switch button"); _wait(2, "account menu opening")
        _click(1372, 55, label="logout option"); _wait(2, "logout option appearing")
        _click(1492, 797, label="confirm logout"); _wait(2, "logout confirming")
        _click(1093, 664, label="confirm logout dialog"); _wait(4, "logging out / game restarting")
        log("AccountCreator: Step 1 complete — logged out")

    def _step2_guest_session(self) -> None:
        log("AccountCreator: ---- Step 2: Start guest session ----")
        log("AccountCreator: Verifying login start screen (login_startnewacc.png) before clicking Play as Guest...")
        _wait_for_template("login_startnewacc.png", timeout=30, label="login start-new-acc screen")
        _click(1238, 992, label="play as guest"); _wait(4, "guest session loading")
        log("AccountCreator: Verifying TOS screen (login_TOSagree.png) before clicking Accept TOS...")
        _wait_for_template("login_TOSagree.png", timeout=30, label="TOS agree screen")
        _click(623, 639, label="accept TOS"); _wait(3, "TOS accepted")

        log("AccountCreator: Checking for login_cancel prompt...")
        coords = find_template("login_cancel.png", confidence=0.75)
        if coords:
            log(f"AccountCreator: login_cancel.png found at {coords} — clicking to dismiss")
            _click(*coords, label="login_cancel")
            _wait(2, "dismiss prompt")
        else:
            log("AccountCreator: No login_cancel prompt detected — continuing")
        log("AccountCreator: Step 2 complete — guest session started")

    def _step3_dialogue_and_zoom(self) -> None:
        log("AccountCreator: ---- Step 3: Initial dialogue and zoom ----")
        cx, cy = get_screen_center()
        log(f"AccountCreator: Screen centre is ({cx}, {cy})")
        pyautogui.moveTo(cx, cy, duration=0.2)
        log("AccountCreator: Scrolling down 5 times to zoom out...")
        scroll_down_5_times()
        _wait(1, "after scroll")
        _click(cx, cy, label="screen centre (dismiss any overlay)")
        _wait(1)

        log("AccountCreator: Age confirmation sequence")
        _click(951, 415, label="age dropdown"); _wait(2, "age dropdown")
        _click(951, 783, label="select age"); _wait(2, "age selected")
        _click(1130, 791, label="confirm age"); _wait(3, "age confirmed")

        log("AccountCreator: Skipping tutorial dialogue x3")
        for i in range(1, 4):
            log(f"AccountCreator: Skip dialogue {i}/3")
            _skip_dialogue(label=f"tutorial skip {i}/3")
            _wait(3, "after skip")

        log("AccountCreator: Step 3 complete")

    def _step4_place_cannon(self) -> None:
        log("AccountCreator: ---- Step 4: Place cannon ----")
        _open_shop(label="for cannon")
        _click(931, 484, label="cannon in shop"); _wait(2, "cannon selected")

        log("AccountCreator: Searching for build_confirm to place cannon...")
        result = _search_and_click_build_confirm()
        log(f"AccountCreator: build_confirm clicked: {result}")

        _wait(10, "cannon placement animation")
        _click(1219, 913, label="close placement / next prompt")
        _wait(2)
        log("AccountCreator: Step 4 complete — cannon placed")

    def _step5_goblin_attack(self) -> None:
        log("AccountCreator: ---- Step 5: Goblin attack demo ----")
        _wait(10, "game catching up before dialogue")

        log("AccountCreator: Skipping pre-attack dialogue x2")
        for i in range(1, 3):
            log(f"AccountCreator: Skip dialogue {i}/2")
            _skip_dialogue(label=f"pre-attack skip {i}/2")
            _wait(3)

        log("AccountCreator: Clicking attack training map button")
        _click(578, 754, label="attack training map"); _wait(3, "loading training map")

        log("AccountCreator: Placing troops x3")
        for i in range(1, 4):
            log(f"AccountCreator: Place troop {i}/3")
            _click(576, 411, label=f"troop placement {i}/3")
            _wait(1)

        log("AccountCreator: Waiting for return button after goblin attack...")
        _wait_and_click_return_button(zoom_out_after=True)
        _wait(3, "post-battle return settling")
        log("AccountCreator: Step 5 complete — goblin attack done")

    def _step6_resource_buildings(self) -> None:
        log("AccountCreator: ---- Step 6: Place resource buildings ----")

        log("AccountCreator: Skipping post-attack dialogue")
        _skip_dialogue(label="post-attack skip")
        _wait(2)

        # Builder hut
        log("AccountCreator: Placing Builder Hut")
        _open_shop(label="for builder hut")
        _click(931, 484, label="builder hut in shop"); _wait(2)
        _search_and_click_build_confirm()
        _wait(2, "builder hut placed")
        _skip_dialogue(label="builder hut dialogue")
        _wait(2)

        # Elixir collector
        log("AccountCreator: Placing Elixir Collector")
        _open_shop(label="for elixir collector")
        _click(931, 484, label="elixir collector in shop"); _wait(2)
        _search_and_click_build_confirm()
        _wait(10, "elixir collector placement animation")
        _skip_dialogue(label="elixir collector dialogue")
        _wait(2)

        # Elixir storage
        log("AccountCreator: Placing Elixir Storage")
        _open_shop(label="for elixir storage")
        _click(931, 484, label="elixir storage in shop"); _wait(2)
        _search_and_click_build_confirm()
        _wait(15, "elixir storage placement animation")
        _skip_dialogue(label="elixir storage dialogue")
        _wait(2)

        # Gold storage
        log("AccountCreator: Placing Gold Storage")
        _open_shop(label="for gold storage")
        _click(931, 484, label="gold storage in shop"); _wait(2)
        _search_and_click_build_confirm()
        _wait(15, "gold storage placement animation")
        _skip_dialogue(label="gold storage dialogue")
        _wait(2)

        # Barracks (far left)
        log("AccountCreator: Placing Barracks (far-left shop position)")
        _open_shop(label="for barracks")
        _click(158, 484, label="barracks in shop (far left)"); _wait(2)
        _search_and_click_build_confirm()
        _wait(15, "barracks building")

        log("AccountCreator: Step 6 complete — all resource buildings placed")

    def _step7_train_army(self) -> None:
        log("AccountCreator: ---- Step 7: Train army ----")
        _click(1035, 860, label="army tab"); _wait(2)
        _click(1297, 384, label="train troops button"); _wait(2)

        log("AccountCreator: Holding click to queue troops (5 seconds)...")
        _hold_click(250, 772, 5.0, label="troop queue button")
        _wait(2, "troop queued")

        _skip_dialogue(label="army training dialogue")
        _wait(2)
        log("AccountCreator: Step 7 complete — army training started")

    def _step8_tutorial_battle(self) -> None:
        log("AccountCreator: ---- Step 8: Final tutorial battle ----")
        _click(109, 979, label="attack button"); _wait(2, "attack menu loading")
        _click(546, 706, label="enter battle"); _wait(3, "battle loading")

        log("AccountCreator: Deploying barbarians — holding click 5 seconds...")
        _hold_click(824, 591, 5.0, label="barbarian deploy area")
        _wait(2, "troops deployed")

        log("AccountCreator: Waiting for return button after tutorial battle...")
        _wait_and_click_return_button(zoom_out_after=True)
        _wait(3, "post-battle return settling")

        _skip_dialogue(label="post-battle dialogue")
        _wait(2)
        log("AccountCreator: Step 8 complete — tutorial battle done")

    def _step9_enter_name(self) -> None:
        log(f"AccountCreator: ---- Step 9: Enter in-game name: '{self._name}' ----")
        log(f"AccountCreator: Typing name with typewrite: '{self._name}'")
        pyautogui.typewrite(self._name, interval=0.05)
        _wait(1, "name typed")
        _click(951, 566, label="confirm name button"); _wait(3, "name confirmed")
        log(f"AccountCreator: Step 9 complete — name set to '{self._name}'")

    def _step10_upgrade_town_hall(self) -> None:
        log("AccountCreator: ---- Step 10: Upgrade Town Hall ----")
        log("AccountCreator: Scrolling down to zoom out before Town Hall click...")
        scroll_down_5_times()
        _wait(2, "zoom settled")
        log(f"AccountCreator: Searching for Town Hall template ({_TH1_TEMPLATE})...")

        screen_w, screen_h = pyautogui.size()
        box_w = int(screen_w * 0.5)
        box_h = int(screen_h * 0.5)
        x1 = (screen_w - box_w) // 2
        y1 = (screen_h - box_h) // 2
        center_box = (x1, y1, x1 + box_w, y1 + box_h)
        log(f"AccountCreator: Restricting TH1 search to center region {center_box}")

        th_coords = _wait_for_template_in_box(
            _TH1_TEMPLATE,
            search_box=center_box,
            timeout=30,
            label="Town Hall (TH1, center region)",
        )
        _click(*th_coords, label="town hall (template match)"); _wait(2, "town hall selected")
        _click(1033, 873, label="upgrade button"); _wait(2, "upgrade menu open")
        _click(1348, 943, label="confirm upgrade"); _wait(15, "town hall upgrading")
        _skip_dialogue(label="upgrade complete dialogue")
        _wait(2)
        log("AccountCreator: Step 10 complete — Town Hall upgraded")

    def _step11_build_menu_intro(self) -> None:
        log("AccountCreator: ---- Step 11: Clear build menu intro ----")
        _click(906, 47, label="open build menu"); _wait(3, "build menu opening")

        log("AccountCreator: Build menu skip 1/2 (wait for dialogue before click)")
        _skip_dialogue(587, 519, label="build menu skip 1/2")
        _wait(2)

        log("AccountCreator: Build menu skip 2/2 (exit build menu; no dialogue check)")
        _click(587, 519, label="build menu exit 2/2")
        _wait(2)
        log("AccountCreator: Step 11 complete")

    def _step12_assign_supercell_id(self) -> None:
        log("AccountCreator: ---- Step 12: Assign Supercell ID ----")
        log("AccountCreator: Opening settings menu")
        _click(1858, 852, label="settings button"); _wait(2, "settings menu")
        _click(1423, 231, label="account menu"); _wait(2, "account menu open")

        log("AccountCreator: Searching for Register button (login_register.png)...")
        coords = _find_login_register_with_scroll()
        if not coords:
            raise RuntimeError("AccountCreator: login_register.png not found — cannot assign Supercell ID")
        log(f"AccountCreator: Clicking Register at {coords}")
        _click(*coords, label="register button")

        # Disabled per request: do not auto-click the 5 "next" buttons here.
        # log("AccountCreator: Skipping info screens x5 after Register click")
        # _wait(2, "register transition")
        # for i in range(1, 6):
        #     log(f"AccountCreator: Info screen skip {i}/5")
        #     _click(1621, 977, label=f"info screen next {i}/5")
        #     _wait(2)
        log("AccountCreator: Post-register 5x next-click sequence is disabled")

        _wait(1, "ready for email entry")
        log("AccountCreator: Step 12 complete — register form open")

    def _step13_enter_email(self) -> None:
        log(f"AccountCreator: ---- Step 13: Enter email: '{self._email}' ----")
        _click(1452, 686, label="email input field"); _wait(1, "field focused")
        self._verification_search_after = int(time.time())
        log(
            f"AccountCreator: Verification email time marker set to "
            f"{self._verification_search_after} (UNIX)"
        )
        log(f"AccountCreator: Typing email: '{self._email}'")
        pyautogui.typewrite(self._email, interval=0.05)
        _wait(1, "email typed")
        _click(1743, 867, label="send verification code button"); _wait(4, "code sending / email dispatching")
        log("AccountCreator: Step 13 complete — verification email sent")

    def _step14_verification_code(self) -> None:
        log("AccountCreator: ---- Step 14: Retrieve and enter verification code ----")
        log("AccountCreator: Polling Gmail for verification code...")
        code = wait_for_verification_code(
            self._service,
            after_epoch=self._verification_search_after,
        )
        if code is None:
            log("AccountCreator: ERROR — No verification code received from Gmail within timeout")
            raise RuntimeError("Verification code not received — check Gmail and retry")

        log(f"AccountCreator: Code retrieved: {code} — entering it now")
        _click(1394, 771, label="code input field"); _wait(1, "field focused")
        if not _HAS_PYNPUT:
            raise RuntimeError("pynput is required for verification code entry. Install with: pip install pynput")
        log(f"AccountCreator: Typing code with pynput: {code}")
        _PynputController().type(code)
        _wait(1, "code typed")
        _click(1742, 867, label="submit code button"); _wait(3, "code verifying")
        _click(1742, 867, label="create account button"); _wait(3, "account creating")
        log("AccountCreator: Step 14 complete — code submitted")

    def _step15_finish_registration(self) -> None:
        log("AccountCreator: ---- Step 15: Finish registration ----")
        _click(1605, 918, label="continue 1"); _wait(2)
        _click(1605, 1002, label="continue 2"); _wait(2)

        log("AccountCreator: Exiting account menu x2")
        for i in range(1, 3):
            log(f"AccountCreator: Exit account menu {i}/2")
            _click(190, 506, label=f"exit account menu {i}/2")
            _wait(2)
        log("AccountCreator: Step 15 complete — registration finished")

    def _step16_save_account(self) -> None:
        log("AccountCreator: ---- Step 16: Save account data ----")
        accounts = _load_accounts()
        entry = {
            "name": self._name,
            "email": self._email,
            "number": self._number,
        }
        accounts.append(entry)
        _save_accounts(accounts)
        log(f"AccountCreator: Appended entry to {ACCOUNTS_JSON}: {entry}")

        _add_to_approved_accounts(self._name)

        log(
            f"AccountCreator: SUCCESS — account saved — "
            f"name='{self._name}', email='{self._email}', number={self._number}"
        )
