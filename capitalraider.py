"""
capitalraider.py — Clan Capital Raid Automation
================================================

Handles everything from navigating to the Clan Capital through to
deploying troops inside each district battle and waiting for the result.

Intended to be called from ClanCapitalWorker in AutomationWorker.py.
"""

import random
import time
from typing import Callable, Optional, Tuple

import pyautogui
import numpy as np

import Autoclash
import clanscouter as _CS

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

# Districts in attack priority order (easiest first, Capital Peak last).
# Each entry is (name, click_coord).  Capital Peak is checked last because
# it is only available once all other districts are completed.
DISTRICTS = [
    ("Goblin Mines",       (1217, 1012)),
    ("Skeleton Park",      ( 870, 1029)),
    ("Golem Quarry",       ( 552,  983)),
    ("Dragon Cliffs",      (1286,  791)),
    ("Builder's Workshop", (1068,  869)),
    ("Balloon Lagoon",     ( 742,  833)),
    ("Wizard Valley",      ( 932,  658)),
    ("Barbarian Camp",     (1146,  586)),
    ("Capital Peak",       ( 917,  380)),
]

# Diamond (rhombus) deployment zone
# Corners: (639,903) bottom, (−11,436) left, (639,−27) top, (1289,436) right
DIAMOND_CX: int = 639
DIAMOND_CY: int = 436
DIAMOND_HW: int = 650   # half-width  (horizontal half-diagonal)
DIAMOND_HH: int = 467   # half-height (vertical   half-diagonal)

# Troop / spell button positions (to click before placing)
TROOP_BUTTON: Tuple[int, int] = (344, 1000)
SPELL_BUTTONS = [(484, 1000), (622, 1000)]

# Tap here to deselect a district without entering it
DESELECT_COORD: Tuple[int, int] = (1621, 624)

# Drag gesture used for navigation (scroll to find capital ship) and
# for zooming out inside a battle (repeated 5 times)
DRAG_START: Tuple[int, int] = (900, 791)
DRAG_END:   Tuple[int, int] = (677, 347)

# Pixel saturation threshold for "greyed out / depleted" button detection.
# A button is considered depleted when max(R,G,B) - min(R,G,B) < this value.
GREY_SAT_THRESHOLD: int = 30

# How often (seconds) to poll for the end-of-battle template
BATTLE_POLL_SECONDS: float = 5.0

# Maximum drag iterations when navigating to the capital ship
NAVIGATE_MAX_DRAGS: int = 30

# Template image filenames (must exist in Autoclash's image folder)
TPL_CAPITAL_SHIP    = "capital_ship.png"
TPL_CAPITAL_GO      = "capital_go.png"
TPL_CAPITAL_NEXTRAID = "capital_nextraid.png"
TPL_CAPITAL_RAIDMAP = "capital_raidmap.png"
TPL_CAPITAL_ATTACK  = "capital_attack.png"
TPL_CAPITAL_ENTER   = "capital_enterbattle.png"
TPL_CAPITAL_END     = "capital_endofbattle.png"
TPL_CAPITAL_STARTRAID = "capital_startraid.png"
TPL_PROFILE_BTN     = "profile_button.png"
TPL_VIEW_CLAN       = "view_clan_button.png"
TPL_JOIN_CLAN       = "join_clan.png"
TPL_JOIN_CLAN_OKAY  = "join_clan_okay.png"
TPL_LEWIS3          = "lewis3.png"
TPL_WILLIAMLEEMING  = "williamleeming.png"

# The account whose clan every other account should be in for capital raids
CLAN_REFERENCE_ACCOUNT = "lewis3"

# Coordinates for clan-join flow
PROFILE_TAB_COORD:  Tuple[int, int] = (67,   52)
SOCIAL_TAB_COORD:   Tuple[int, int] = (1510,  91)
EXIT_PROFILE_COORD: Tuple[int, int] = (67,  358)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    Autoclash.log(f"CapitalRaider: {msg}")


def _status(status_fn: Optional[Callable], phase: str, msg: str) -> None:
    _log(f"{phase} — {msg}")
    if status_fn is not None:
        status_fn(phase, msg)


def _stopped(stop_fn: Optional[Callable]) -> bool:
    return stop_fn is not None and stop_fn()


def _drag_once(duration: float = 0.4) -> None:
    """Perform the standard navigation/zoom drag gesture once."""
    pyautogui.moveTo(*DRAG_START, duration=0.1)
    pyautogui.dragTo(*DRAG_END, duration=duration, button="left")
    time.sleep(0.2)


# ---------------------------------------------------------------------------
# Diamond random point generator
# ---------------------------------------------------------------------------

def random_point_in_diamond() -> Tuple[int, int]:
    """Return a uniformly random (x, y) inside the rhombus deployment zone."""
    while True:
        x = random.uniform(DIAMOND_CX - DIAMOND_HW, DIAMOND_CX + DIAMOND_HW)
        y = random.uniform(DIAMOND_CY - DIAMOND_HH, DIAMOND_CY + DIAMOND_HH)
        if (abs(x - DIAMOND_CX) / DIAMOND_HW) + (abs(y - DIAMOND_CY) / DIAMOND_HH) <= 1.0:
            return int(x), int(y)


# ---------------------------------------------------------------------------
# Grey / depleted button detection
# ---------------------------------------------------------------------------

def is_button_depleted(button_xy: Tuple[int, int]) -> bool:
    """
    Return True when the button at *button_xy* appears greyed out (depleted).

    Samples the pixel at the given coordinate and checks whether its RGB
    saturation (max - min channel) is below GREY_SAT_THRESHOLD.
    """
    try:
        screenshot = pyautogui.screenshot()
        px = screenshot.getpixel(button_xy)
        r, g, b = px[0], px[1], px[2]
        saturation = max(r, g, b) - min(r, g, b)
        depleted = saturation < GREY_SAT_THRESHOLD
        _log(f"Button {button_xy}: RGB({r},{g},{b}) sat={saturation} depleted={depleted}")
        return depleted
    except Exception as exc:
        _log(f"is_button_depleted error: {exc}")
        return False


# ---------------------------------------------------------------------------
# Unit / spell placement
# ---------------------------------------------------------------------------

def place_unit(
    button_xy: Tuple[int, int],
    stop_fn: Optional[Callable],
    status_fn: Optional[Callable],
) -> None:
    """
    Select the unit/spell at *button_xy* then randomly click inside the
    diamond deployment zone until the button's pixel goes grey (depleted).
    """
    _status(status_fn, "Battle", f"Selecting unit at {button_xy}")
    Autoclash.click_with_jitter(*button_xy)
    time.sleep(0.3)

    click_count = 0
    while not _stopped(stop_fn):
        x, y = random_point_in_diamond()
        Autoclash.click_with_jitter(x, y)
        click_count += 1
        time.sleep(random.uniform(0.03, 0.07))

        # Check depletion every 3 clicks to avoid hammering screenshots
        if click_count % 3 == 0:
            if is_button_depleted(button_xy):
                _status(status_fn, "Battle", f"Unit at {button_xy} depleted after {click_count} clicks")
                break

    time.sleep(0.2)


# ---------------------------------------------------------------------------
# Navigate to Clan Capital
# ---------------------------------------------------------------------------

def navigate_to_capital(
    stop_fn: Optional[Callable],
    status_fn: Optional[Callable],
) -> bool:
    """
    Scroll and drag until the Clan Capital ship icon is visible, then click it.

    Returns True on success, False on timeout or stop.
    """
    _status(status_fn, "Navigate", "Searching for Clan Capital ship…")

    for attempt in range(1, NAVIGATE_MAX_DRAGS + 1):
        if _stopped(stop_fn):
            return False

        # Try to find the ship first (before dragging)
        coords = Autoclash.find_template(TPL_CAPITAL_SHIP)
        if coords:
            _status(status_fn, "Navigate", f"Found capital ship at {coords} — clicking")
            Autoclash.click_with_jitter(*coords)
            Autoclash.random_delay()
            time.sleep(1.5)
            return True

        _status(status_fn, "Navigate", f"Dragging to find capital ship ({attempt}/{NAVIGATE_MAX_DRAGS})")
        _drag_once()

        # Scroll down a little to reveal more of the village
        try:
            Autoclash.scroll_down_api(Autoclash.WHEEL_DELTA * 2)
        except Exception:
            pyautogui.scroll(-abs(int(Autoclash.WHEEL_DELTA * 2)))
        time.sleep(0.3)

    _status(status_fn, "Navigate", "Timed out searching for capital ship")
    return False


# ---------------------------------------------------------------------------
# Handle Clan Capital lobby screen
# ---------------------------------------------------------------------------

def handle_capital_lobby(
    stop_fn: Optional[Callable],
    status_fn: Optional[Callable],
) -> str:
    """
    From the Clan Capital lobby screen:
      1. Click capital_go if present
      2. Click capital_nextraid if present
      3. Check for capital_startraid — if found the clan has no active raid; back out
      4. Click capital_raidmap (required) to enter the raid map

    Returns:
        "ok"          — successfully entered the raid
        "unsuitable"  — clan has no active raid weekend (capital_startraid found)
        "failed"      — could not reach the raid map
    """
    _status(status_fn, "Lobby", "Checking capital lobby…")
    time.sleep(1.0)

    # "Go" button — if clicked we're already heading into raids, no need for raidmap
    for _ in range(5):
        if _stopped(stop_fn):
            return "failed"
        coords = Autoclash.find_template(TPL_CAPITAL_GO)
        if coords:
            _status(status_fn, "Lobby", "Clicking capital_go — proceeding to districts")
            Autoclash.click_with_jitter(*coords)
            Autoclash.random_delay()
            time.sleep(2.0)
            return "ok"
        time.sleep(1.0)

    # "Next Raid" button — same: clicking it takes us straight into the raid
    for _ in range(5):
        if _stopped(stop_fn):
            return "failed"
        coords = Autoclash.find_template(TPL_CAPITAL_NEXTRAID)
        if coords:
            _status(status_fn, "Lobby", "Clicking capital_nextraid — proceeding to districts")
            Autoclash.click_with_jitter(*coords)
            Autoclash.random_delay()
            time.sleep(2.0)
            return "ok"
        time.sleep(1.0)

    # "Start Raid" button — clan has no active raid weekend; back out and find new clan
    coords = Autoclash.find_template(TPL_CAPITAL_STARTRAID)
    if coords:
        _status(status_fn, "Lobby", "capital_startraid found — clan has no active raid, backing out")
        Autoclash.click_with_jitter(100, 980)
        time.sleep(1.5)
        return "unsuitable"

    # Neither found — look for the raid map button to enter manually
    _status(status_fn, "Lobby", "Looking for raid map button…")
    for attempt in range(1, 11):
        if _stopped(stop_fn):
            return "failed"
        coords = Autoclash.find_template(TPL_CAPITAL_RAIDMAP)
        if coords:
            _status(status_fn, "Lobby", f"Found capital_raidmap at {coords}")
            Autoclash.click_with_jitter(*coords)
            Autoclash.random_delay()
            time.sleep(2.0)
            return "ok"
        _log(f"capital_raidmap not found (attempt {attempt}/10)")
        time.sleep(1.0)

    _status(status_fn, "Lobby", "Failed to find capital_raidmap")
    return "failed"


# ---------------------------------------------------------------------------
# District selection and attack
# ---------------------------------------------------------------------------

def attack_next_district(
    stop_fn: Optional[Callable],
    status_fn: Optional[Callable],
) -> str:
    """
    Iterate through DISTRICTS in order, find the first one that is available
    to attack, and enter its battle.

    Returns:
        "entered"        — successfully entered a battle
        "none_available" — no attackable district found
        "stop"           — stop was requested
    """
    _status(status_fn, "Districts", "Scanning for available district…")

    for district, coord in DISTRICTS:
        if _stopped(stop_fn):
            return "stop"

        # Check for Next Raid button before selecting the district
        next_raid = Autoclash.find_template(TPL_CAPITAL_NEXTRAID)
        if next_raid:
            _status(status_fn, "Districts", "Next Raid button found — clicking and restarting from Goblin Mines")
            Autoclash.click_with_jitter(*next_raid)
            Autoclash.random_delay()
            time.sleep(2.0)
            return "next_raid"

        _status(status_fn, "Districts", f"Selecting '{district}' at {coord}")
        Autoclash.click_with_jitter(*coord)
        time.sleep(0.6)

        if _stopped(stop_fn):
            return "stop"

        # Look for the attack button
        attack_coords = Autoclash.find_template(TPL_CAPITAL_ATTACK)
        if attack_coords is None:
            _log(f"'{district}': no attack button found — skipping")
            Autoclash.click_with_jitter(*DESELECT_COORD)
            time.sleep(0.4)
            continue

        # Click the attack button
        _status(status_fn, "Districts", f"Clicking attack on '{district}'")
        Autoclash.click_with_jitter(*attack_coords)
        time.sleep(0.9)

        if _stopped(stop_fn):
            return "stop"

        # Check for the Enter Battle button first (appears when district is ready)
        enter_coords = Autoclash.find_template(
            TPL_CAPITAL_ENTER, search_box=(400, 300, 1700, 750)
        )
        if enter_coords:
            _status(status_fn, "Districts", f"'{district}' available — entering battle")
            Autoclash.click_with_jitter(*enter_coords)
            Autoclash.random_delay()
            time.sleep(2.0)
            if Autoclash.find_template(TPL_CAPITAL_ATTACK):
                _status(status_fn, "Districts", "Attack button reappeared after Enter Battle — clan attacks exhausted")
                return "clan_exhausted"
            return "entered"

        # Enter Battle not found — check if attack button is still visible (district already completed)
        still_visible = Autoclash.find_template(TPL_CAPITAL_ATTACK)
        if still_visible:
            _status(status_fn, "Districts", f"'{district}' already completed — deselecting")
            Autoclash.click_with_jitter(*DESELECT_COORD)
            time.sleep(0.4)
            continue

        # Attack button gone but no Enter Battle either — retry Enter Battle a few times
        _status(status_fn, "Districts", f"'{district}' — waiting for Enter Battle…")
        for _ in range(4):
            time.sleep(0.5)
            enter_coords = Autoclash.find_template(
                TPL_CAPITAL_ENTER, search_box=(400, 300, 1700, 750)
            )
            if enter_coords:
                Autoclash.click_with_jitter(*enter_coords)
                Autoclash.random_delay()
                time.sleep(2.0)
                if Autoclash.find_template(TPL_CAPITAL_ATTACK):
                    _status(status_fn, "Districts", "Attack button reappeared after Enter Battle — clan attacks exhausted")
                    return "clan_exhausted"
                return "entered"

        _log(f"capital_enterbattle not found after selecting '{district}' — deselecting")
        Autoclash.click_with_jitter(*DESELECT_COORD)
        time.sleep(0.4)
        continue

    return "none_available"


# ---------------------------------------------------------------------------
# Battle execution
# ---------------------------------------------------------------------------

def run_battle(
    stop_fn: Optional[Callable],
    status_fn: Optional[Callable],
) -> None:
    """
    Execute one capital district battle:
      1. Zoom out (5× drag gesture)
      2. Place troops
      3. Place spells (both spell slots)
      4. Poll for end-of-battle screen and click it
    """
    _status(status_fn, "Battle", "Zooming out…")
    for i in range(5):
        if _stopped(stop_fn):
            return
        _drag_once(duration=0.35)
        try:
            Autoclash.scroll_down_api(Autoclash.WHEEL_DELTA * 2)
        except Exception:
            pyautogui.scroll(-abs(int(Autoclash.WHEEL_DELTA * 2)))
        time.sleep(0.3)

    if _stopped(stop_fn):
        return

    # Deploy troops
    _status(status_fn, "Battle", "Placing troops…")
    place_unit(TROOP_BUTTON, stop_fn, status_fn)

    # Deploy spells
    for spell_btn in SPELL_BUTTONS:
        if _stopped(stop_fn):
            return
        _status(status_fn, "Battle", f"Placing spell at {spell_btn}…")
        place_unit(spell_btn, stop_fn, status_fn)

    # Wait for battle to end
    _status(status_fn, "Battle", "All units placed — waiting for battle to end…")
    while not _stopped(stop_fn):
        end_coords = Autoclash.find_template(TPL_CAPITAL_END)
        if end_coords:
            _status(status_fn, "Battle", "Battle ended — clicking end button")
            Autoclash.click_with_jitter(*end_coords)
            Autoclash.random_delay()
            time.sleep(2.0)
            # Check for "Next Raid" button a few times before returning
            for _ in range(4):
                if _stopped(stop_fn):
                    return
                next_coords = Autoclash.find_template(TPL_CAPITAL_NEXTRAID)
                if next_coords:
                    _status(status_fn, "Battle", "Clicking Next Raid")
                    Autoclash.click_with_jitter(*next_coords)
                    Autoclash.random_delay()
                    time.sleep(1.5)
                    break
                time.sleep(0.5)
            return
        time.sleep(BATTLE_POLL_SECONDS)

    _log("run_battle: stopped while waiting for end-of-battle")


# ---------------------------------------------------------------------------
# Clan membership check / join
# ---------------------------------------------------------------------------

def _find_template_retry(tpl: str, attempts: int = 5, delay: float = 0.5,
                         confidence: float = None):
    """Try finding a template up to *attempts* times, returning coords or None."""
    for _ in range(attempts):
        coords = Autoclash.find_template(tpl, confidence=confidence)
        if coords:
            return coords
        time.sleep(delay)
    return None


def _join_clan_of(
    account_tpl: str,
    account_label: str,
    stop_fn: Optional[Callable],
    status_fn: Optional[Callable],
) -> bool:
    """
    Shared helper: open social tab, find *account_label* using *account_tpl*,
    open their profile, and join their clan if not already in it.
    """
    _status(status_fn, "Clan", "Opening profile tab…")
    Autoclash.click_with_jitter(*PROFILE_TAB_COORD)
    time.sleep(1.0)
    if _stopped(stop_fn):
        return False

    Autoclash.click_with_jitter(*SOCIAL_TAB_COORD)
    time.sleep(1.0)
    if _stopped(stop_fn):
        return False

    # Search for the reference account; scroll down between attempts
    _status(status_fn, "Clan", f"Looking for {account_label} in social tab…")
    ref_coords = None
    for attempt in range(1, 6):
        ref_coords = Autoclash.find_template(account_tpl, confidence=0.75)
        if ref_coords:
            break
        _log(f"{account_tpl} not found (attempt {attempt}/5) — scrolling down")
        pyautogui.moveTo(874, 593, duration=0.1)
        pyautogui.scroll(-3)
        time.sleep(3.0)

    if ref_coords is None:
        _status(status_fn, "Clan", f"Could not find {account_label} in social tab")
        return False

    _status(status_fn, "Clan", f"Found {account_label} — opening profile")
    Autoclash.click_with_jitter(*ref_coords)
    time.sleep(1.0)
    if _stopped(stop_fn):
        return False

    profile_coords = _find_template_retry(TPL_PROFILE_BTN)
    if profile_coords is None:
        _status(status_fn, "Clan", "Could not find profile button")
        return False
    Autoclash.click_with_jitter(*profile_coords)
    time.sleep(1.0)
    if _stopped(stop_fn):
        return False

    # If view_clan_button is absent we are already in this account's clan
    view_clan_coords = _find_template_retry(TPL_VIEW_CLAN, attempts=4, delay=0.5, confidence=0.9)
    if view_clan_coords is None:
        _status(status_fn, "Clan", "Already in correct clan — closing profile")
        Autoclash.click_with_jitter(*EXIT_PROFILE_COORD)
        time.sleep(1.0)
        return True

    # Need to join the clan
    _status(status_fn, "Clan", f"Not in correct clan — joining {account_label}'s clan")
    Autoclash.click_with_jitter(*view_clan_coords)
    time.sleep(1.5)
    if _stopped(stop_fn):
        return False

    join_coords = _find_template_retry(TPL_JOIN_CLAN)
    if join_coords is None:
        _status(status_fn, "Clan", "Could not find join clan button")
        return False
    Autoclash.click_with_jitter(*join_coords)
    time.sleep(1.0)
    if _stopped(stop_fn):
        return False

    okay_coords = _find_template_retry(TPL_JOIN_CLAN_OKAY)
    if okay_coords is None:
        _status(status_fn, "Clan", "Could not find join clan confirm button")
        return False
    Autoclash.click_with_jitter(*okay_coords)
    time.sleep(2.0)

    _status(status_fn, "Clan", f"Successfully joined {account_label}'s clan")
    return True


def ensure_correct_clan(
    stop_fn: Optional[Callable],
    status_fn: Optional[Callable],
) -> bool:
    """Join lewis3's clan (needed before capital raids)."""
    return _join_clan_of(TPL_LEWIS3, "lewis3", stop_fn, status_fn)


def return_to_main_clan(
    stop_fn: Optional[Callable],
    status_fn: Optional[Callable],
) -> bool:
    """Return to williamleeming's clan (main clan) after capital raids."""
    return _join_clan_of(TPL_WILLIAMLEEMING, "williamleeming", stop_fn, status_fn)


# ---------------------------------------------------------------------------
# Return to home village
# ---------------------------------------------------------------------------

def return_to_home_village(
    stop_fn: Optional[Callable],
    status_fn: Optional[Callable],
) -> None:
    """
    Click the bottom-left back button twice to return to the home village.
    After the two clicks, checks for return_home.png and clicks it if present
    to handle the rare cases where two clicks are not enough.
    """
    _status(status_fn, "Navigate", "Returning to home village…")
    Autoclash.click_with_jitter(100, 980)
    time.sleep(1.0)
    Autoclash.click_with_jitter(100, 980)
    time.sleep(1.5)
    rh = Autoclash.find_template("capital_returnhome.png")
    if rh:
        _status(status_fn, "Navigate", "Clicking capital_returnhome button…")
        Autoclash.click_with_jitter(*rh)
        time.sleep(1.5)


# ---------------------------------------------------------------------------
# Clan finder + joiner
# ---------------------------------------------------------------------------

def find_and_join_clan(
    stop_fn: Optional[Callable],
    status_fn: Optional[Callable],
) -> bool:
    """
    Open the clan search, scroll through clans and join the first one that
    has Capital Hall 10 and is open to anyone.

    Loops indefinitely (re-opening the search from scratch each time the list
    is exhausted) until a clan is successfully joined or stop_fn() returns True.

    Returns True on success, False if stopped.
    """
    _SENTINEL = object()
    reset_count = 0
    HARD_RESET_THRESHOLD = 15

    while not _stopped(stop_fn):
        _status(status_fn, "ClanSearch", "Opening clan search…")
        try:
            _CS._open_clan_search(stop_fn)
        except Exception as exc:
            _log(f"find_and_join_clan: error opening clan search: {exc} — aborting")
            return False

        if _stopped(stop_fn):
            return False

        same_count = 0
        last_pos = _SENTINEL

        while not _stopped(stop_fn):
            _status(status_fn, "ClanSearch", "Scanning for 'Anyone Can Join'…")

            try:
                found_pos = _CS._find_phrase_in_region(_CS.CLANS_BOX, "anyonecanjoin")
            except Exception as exc:
                _log(f"find_and_join_clan: OCR error: {exc} — aborting")
                return False

            # Track consecutive identical results to detect list exhaustion
            if last_pos is _SENTINEL:
                same_count = 1
                last_pos = found_pos
            elif _CS._positions_match(found_pos, last_pos):
                same_count += 1
            else:
                same_count = 1
                last_pos = found_pos

            if same_count >= 15:
                reset_count += 1
                _status(status_fn, "ClanSearch", f"List exhausted — resetting search (reset #{reset_count})…")
                if reset_count >= HARD_RESET_THRESHOLD:
                    _status(status_fn, "ClanSearch", f"Search reset {reset_count} times with no clans found — requesting hard reset")
                    return "hard_reset_needed"
                _CS._exit_clan_search()
                break  # re-enter outer loop to re-open search from scratch

            if found_pos is not None:
                _status(status_fn, "ClanSearch", f"Found 'Anyone Can Join' at {found_pos} — checking clan…")
                Autoclash.click_with_jitter(*found_pos)
                time.sleep(1.0)

                if _stopped(stop_fn):
                    return False

                Autoclash.click_with_jitter(*_CS.CLAN_STATS_COORD)
                time.sleep(1.0)

                if _stopped(stop_fn):
                    return False

                cap10 = Autoclash.find_template("capital_hall_10.png", confidence=0.99)
                if cap10:
                    _status(status_fn, "ClanSearch", "Capital Hall 10 confirmed — joining clan…")
                    join = Autoclash.find_template(TPL_JOIN_CLAN)
                    if join:
                        Autoclash.click_with_jitter(*join)
                        time.sleep(1.0)
                        okay = _find_template_retry(TPL_JOIN_CLAN_OKAY)
                        if okay:
                            Autoclash.click_with_jitter(*okay)
                            time.sleep(2.0)
                            _status(status_fn, "ClanSearch", "Joined clan — returned to home village")
                            return True
                        else:
                            _log("find_and_join_clan: could not find join_clan_okay — backing out and continuing")
                            Autoclash.click_with_jitter(*_CS.EXIT_CLAN_SCREEN_COORD)
                            time.sleep(0.5)
                    else:
                        _log("find_and_join_clan: Capital Hall 10 found but no join button visible — exiting clan screen")
                        Autoclash.click_with_jitter(*_CS.EXIT_CLAN_SCREEN_COORD)
                        time.sleep(0.5)
                else:
                    _status(status_fn, "ClanSearch", "Not Capital Hall 10 — skipping")
                    Autoclash.click_with_jitter(*_CS.EXIT_CLAN_SCREEN_COORD)
                    time.sleep(0.5)
            else:
                _status(status_fn, "ClanSearch", "No 'Anyone Can Join' visible — scrolling…")

            _CS._scroll_clans_list_down()
            time.sleep(2.0)

    return False


# ---------------------------------------------------------------------------
# Per-account entry point
# ---------------------------------------------------------------------------

def run_capital_raid_for_account(
    stop_fn: Optional[Callable],
    status_fn: Optional[Callable],
) -> str:
    """
    Run the full Capital raid sequence for the currently active account.

    Assumes the account has already been switched to and is on the
    home village screen.

    Returns:
        "done"           — all available districts attacked; home village reached
        "clan_exhausted" — clan has no attacks left; return_to_home_village
                           has already been called before returning
        "nav_failed"     — could not navigate to capital or reach raid map
        "stopped"        — stop was requested
    """
    _status(status_fn, "Capital", "Starting capital raid for this account")

    if not navigate_to_capital(stop_fn, status_fn):
        _status(status_fn, "Capital", "Could not navigate to capital — aborting account")
        return "nav_failed"

    if _stopped(stop_fn):
        return "stopped"

    lobby_result = handle_capital_lobby(stop_fn, status_fn)
    if lobby_result == "unsuitable":
        _status(status_fn, "Capital", "Clan has no active raid — finding new clan")
        return "clan_exhausted"
    if lobby_result == "failed":
        _status(status_fn, "Capital", "Could not reach raid map — aborting account")
        return "nav_failed"

    battles_done = 0
    while not _stopped(stop_fn):
        result = attack_next_district(stop_fn, status_fn)

        if result == "stop":
            return "stopped"

        if result == "next_raid":
            _status(status_fn, "Capital", "Next Raid clicked — restarting from Goblin Mines")
            continue

        if result == "clan_exhausted":
            _status(status_fn, "Capital", "Clan attacks exhausted — returning to home village")
            return_to_home_village(stop_fn, status_fn)
            return "clan_exhausted"

        if result == "none_available":
            _status(status_fn, "Capital", f"No more districts — done ({battles_done} battles)")
            return_to_home_village(stop_fn, status_fn)
            return "done"

        # result == "entered"
        battles_done += 1
        _status(status_fn, "Capital", f"Running battle {battles_done}…")
        run_battle(stop_fn, status_fn)

    return "stopped"
