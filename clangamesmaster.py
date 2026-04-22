#!/usr/bin/env python3
"""
Clan Games Master Bot
=====================
Combines challenge selection, full attacks, and challenge cycling into one bot.

Attack accounts: williamleeming, lewis3–lewis8

Flow:
  For each non-completed account (in order):
    1. Attack loop:
         - Scroll down 5×, drag map, open clan games stand.
         - Check yellow pixel at (513,978) → if yellow (~7000 pts), mark account
           completed and move to the next one.
         - If active challenge or trash cooldown already active → exit stand and
           do a full attack (phases 1-3).
         - If valid challenge found → click it, start it, exit stand, do full attack.
         - If only invalid challenges on both pages → exit stand, go to cycling.
    2. Cycling phase:
         - Cycle through all 7 accounts trashing one invalid challenge per visit,
           respecting the 10m 30s cooldown logic.
         - Stop cycling when a full pass finds no invalid challenges on any account.
         - Switch back to the attacking account and resume the attack loop.
    When all accounts are completed:
         - One final cycling pass to clear any remaining bad challenges, then stop.
"""

from __future__ import annotations

import random
import time
from typing import Callable, Dict, List, Optional, Set, Tuple

import pyautogui

import Autoclash as AC
import vision as _vision
import clangamescycler as CGC

# ---------------------------------------------------------------------------
# Account list
# ---------------------------------------------------------------------------

ATTACK_ACCOUNTS: List[str] = [
    "williamleeming",
    "lewis3",
    "lewis4",
    "lewis5",
    "lewis6",
    "lewis7",
    "lewis8",
]

CG_MASTER_SWITCH_NAMES: Dict[str, str] = {
    "williamleeming": "HomelessLewis2",
    "lewis3":         "TrustworthyLewis3",
    "lewis4":         "IconLewis4",
    "lewis5":         "SincereLewis5",
    "lewis6":         "WelcomedLewis6",
    "lewis7":         "CurlyLewis7",
    "lewis8":         "FreshLewis8",
}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Yellow pixel at (513, 978) — visible only after the clan games stand is open.
# When yellow it means the account has ~7000 pts (enough for all rewards).
COMPLETION_PIXEL: Tuple[int, int] = (513, 978)
COMPLETION_YELLOW: Tuple[int, int, int] = (245, 215, 80)
COMPLETION_TOLERANCE: float = 90.0

# Result codes returned by open_stand_and_select_challenge
RESULT_COMPLETED = "completed"   # yellow completion pixel → mark account done
RESULT_HAS_VALID = "has_valid"   # challenge selected (or already active) → attack
RESULT_NO_VALID  = "no_valid"    # only invalid challenges → go to cycling
RESULT_FAILED    = "failed"      # stand not found or templates missing
RESULT_STOPPED   = "stopped"     # stop requested by user


# ---------------------------------------------------------------------------
# Completion pixel check
# ---------------------------------------------------------------------------

def _is_completion_pixel_yellow() -> bool:
    """Return True if pixel (513, 978) is close to yellow (~7000 pts)."""
    x, y = COMPLETION_PIXEL
    try:
        shot = _vision.safe_screenshot(region=(x, y, 1, 1))
        rgb = shot.getpixel((0, 0))
        if isinstance(rgb, tuple) and len(rgb) >= 3:
            r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
            tr, tg, tb = COMPLETION_YELLOW
            dist = ((r - tr) ** 2 + (g - tg) ** 2 + (b - tb) ** 2) ** 0.5
            AC.log(f"CG Master: completion pixel ({x},{y}) RGB=({r},{g},{b}) dist={dist:.1f}")
            return dist <= COMPLETION_TOLERANCE
    except Exception as exc:
        AC.log(f"CG Master: completion pixel check failed: {exc}")
    return False


# ---------------------------------------------------------------------------
# Stand navigation + challenge selection
# ---------------------------------------------------------------------------

def open_stand_and_select_challenge(stop_fn: Callable[[], bool]) -> str:
    """
    Scroll down 5×, drag map 2×, find and open the clan games stand, then:

      RESULT_COMPLETED  — yellow pixel at (513,978): ~7000 pts, account done
      RESULT_HAS_VALID  — challenge selected or already active → do attack
      RESULT_NO_VALID   — no valid challenges on either page → need cycling
      RESULT_FAILED     — stand not found or no templates configured
      RESULT_STOPPED    — stop requested
    """
    if stop_fn():
        return RESULT_STOPPED

    AC.log("CG Master: Scrolling down 5 times")
    AC.scroll_down_5_times(AC.WHEEL_DELTA * 3)

    if stop_fn():
        return RESULT_STOPPED

    for drag_num in range(1, 3):
        if stop_fn():
            return RESULT_STOPPED
        AC.log(f"CG Master: Dragging map ({drag_num}/2)")
        pyautogui.moveTo(733, 291, duration=0.1)
        pyautogui.dragTo(1177, 958, duration=0.4, button="left")
        time.sleep(0.2)

    if stop_fn():
        return RESULT_STOPPED

    # Find and click the clan games stand
    stand_template   = AC.CONFIG.get("clan_games_stand_template", "clan_games_stand.png")
    stand_confidence = float(AC.CONFIG.get("clan_games_stand_confidence", AC.CONFIG["confidence_threshold"]))
    stand_retries    = int(AC.CONFIG.get("clan_games_stand_retry_attempts", 10))
    stand_delay      = float(AC.CONFIG.get("clan_games_stand_retry_delay", 1.0))

    stand_coords = None
    for attempt in range(1, stand_retries + 1):
        if stop_fn():
            return RESULT_STOPPED
        AC.log(f"CG Master: Searching for stand (attempt {attempt}/{stand_retries})")
        stand_coords = AC.find_template(stand_template, confidence=stand_confidence)
        if stand_coords:
            AC.log(f"CG Master: Found stand at {stand_coords}")
            CGC.click_and_wait(*stand_coords, action_desc="stand click")
            AC.log("CG Master: Waiting 5s for challenges screen")
            time.sleep(5.0)
            break
        if attempt < stand_retries:
            time.sleep(stand_delay)

    if not stand_coords:
        AC.log("CG Master: Stand not found after retries")
        return RESULT_FAILED

    if stop_fn():
        return RESULT_STOPPED

    # Check completion pixel — only visible after the stand is open
    if _is_completion_pixel_yellow():
        AC.log("CG Master: Account completed (~7000 pts) — exiting stand")
        CGC.click_and_wait(1704, 79, action_desc="menu exit (account complete)")
        return RESULT_COMPLETED

    # Active challenge already running (yellow at 890,459) → just exit and attack
    if CGC.is_active_challenge_pixel_yellow((890, 459)):
        AC.log("CG Master: Active challenge detected at (890,459) — exiting and attacking")
        CGC.click_and_wait(1704, 79, action_desc="menu exit (active challenge)")
        return RESULT_HAS_VALID

    # Trash cooldown active → a challenge was recently started → exit and attack
    cooldown_tpl = AC.CONFIG.get("clan_games_cooldown_template", "clan_games_cooldown.png")
    if AC.find_template(cooldown_tpl):
        AC.log("CG Master: Trash cooldown active — exiting stand and attacking")
        CGC.click_and_wait(1704, 79, action_desc="menu exit (trash cooldown)")
        return RESULT_HAS_VALID

    if stop_fn():
        return RESULT_STOPPED

    # Scan for valid challenges
    challenge_templates = CGC._discover_challenge_templates()
    challenge_region    = AC.CONFIG.get("clan_games_challenge_region", (700, 200, 1700, 800))
    challenge_conf      = float(AC.CONFIG.get("clan_games_challenge_confidence", AC.CONFIG["confidence_threshold"]))
    start_template      = AC.CONFIG.get("clan_games_start_template", "clan_games_start.png")

    if not challenge_templates:
        AC.log("CG Master: No challenge templates found")
        CGC.click_and_wait(1704, 79, action_desc="menu exit (no templates)")
        return RESULT_FAILED

    detections = CGC.detect_valid_challenges(challenge_templates, challenge_conf, challenge_region)

    if not detections:
        AC.log("CG Master: No valid challenges on page 1 — checking page 2")
        CGC.scroll_challenge_list_once_down(challenge_region)
        if stop_fn():
            return RESULT_STOPPED
        detections = CGC.detect_valid_challenges(challenge_templates, challenge_conf, challenge_region)

    if not detections:
        AC.log("CG Master: No valid challenges on either page — need cycling")
        CGC.click_and_wait(1704, 79, action_desc="menu exit (no valid challenges)")
        return RESULT_NO_VALID

    # Click a random valid challenge
    chosen = random.choice(detections)
    cx = int((chosen["bbox"][0] + chosen["bbox"][2]) // 2)
    cy = int((chosen["bbox"][1] + chosen["bbox"][3]) // 2)
    AC.log(f"CG Master: Clicking challenge '{chosen.get('label', '')}' at ({cx},{cy})")
    CGC.click_and_wait(cx, cy, action_desc="challenge click")

    if stop_fn():
        return RESULT_STOPPED

    # Click start button
    start_coords = AC.find_template(start_template)
    if not start_coords:
        AC.log("CG Master: Start button not found — challenge may already be active")
        CGC.click_and_wait(1704, 79, action_desc="menu exit (no start)")
        return RESULT_HAS_VALID

    AC.log(f"CG Master: Clicking start at {start_coords}")
    CGC.click_and_wait(*start_coords, action_desc="start button")
    CGC.click_and_wait(1704, 79, action_desc="challenges screen exit")
    return RESULT_HAS_VALID


# ---------------------------------------------------------------------------
# Per-account cycling (trash one invalid challenge)
# ---------------------------------------------------------------------------

def _cycle_one_account(
    challenge_region: Tuple[int, int, int, int],
    challenge_conf: float,
    challenge_templates: List[str],
    start_template: str,
) -> Tuple[bool, bool]:
    """
    Open the stand on the current account, find an invalid slot, and trash it.
    Checks both challenge pages.
    Returns (trashed_any, cooldown_detected).
    """
    stand_opened, cooldown_detected = CGC.open_clan_games_stand()
    if not stand_opened:
        return False, cooldown_detected

    def scan_invalids() -> List:
        dets = CGC.detect_valid_challenges(challenge_templates, challenge_conf, challenge_region)
        bb_protected, _ = CGC.detect_builder_side_protected_slots()
        invalids = CGC.pick_invalid_slots(dets, CGC.GRID_COORDS)
        if bb_protected:
            invalids = [c for c in invalids if c not in set(bb_protected)]
        return invalids

    invalid_slots = scan_invalids()

    if not invalid_slots:
        CGC.scroll_challenge_list_once_down(challenge_region)
        invalid_slots = scan_invalids()

    if not invalid_slots:
        CGC.click_and_wait(1704, 79, action_desc="menu exit (no invalids)")
        return False, False

    target = random.choice(invalid_slots)
    trashed = CGC.trash_challenge_at_slot(target, start_template, overlay=None)
    CGC.click_and_wait(1704, 79, action_desc="menu exit (after trash)")
    return trashed, False


# ---------------------------------------------------------------------------
# Account switching
# ---------------------------------------------------------------------------

def _switch_to_specific_account(
    account_name: str,
    stop_fn: Callable[[], bool],
    overlay_fn: Optional[Callable[[list, str], None]] = None,
) -> bool:
    """
    Switch to one specific account via the in-game switch menu.
    Draws the OCR match on the overlay so you can see exactly what was found.
    Returns True on success.
    """
    if account_name not in CG_MASTER_SWITCH_NAMES:
        AC.log(f"CG Master: '{account_name}' not in switch name map")
        return False

    candidate_map = {account_name: CG_MASTER_SWITCH_NAMES[account_name]}
    CGC._open_account_switch_menu()

    def find_with_scroll(direction: str) -> dict:
        for scan_idx in range(51):
            if stop_fn():
                return {}
            visible = CGC._match_visible_switch_accounts(candidate_map)
            if visible:
                # Draw what OCR found on the overlay before clicking
                if overlay_fn is not None:
                    dets = [
                        {
                            "bbox": d["bbox"],
                            "label": f"{name} → '{d['ocr_text']}' ({d['ocr_conf']:.0%})",
                            "score": float(d["ocr_conf"]),
                        }
                        for name, d in visible.items()
                    ]
                    overlay_fn(dets, f"Switch: found {account_name}")
                return visible
            if scan_idx < 50:
                if direction == "down":
                    CGC._scroll_switch_box_once_down()
                else:
                    CGC._scroll_switch_box_once_up()
        return {}

    visible = find_with_scroll("down")
    if not visible:
        AC.log("CG Master: Not found scrolling down — resetting and retrying")
        for _ in range(50):
            CGC._scroll_switch_box_once_up()
        visible = find_with_scroll("down")

    if not visible:
        AC.log(f"CG Master: Could not find '{account_name}' in switch menu")
        return False

    _, data = next(iter(visible.items()))
    AC.log(
        f"CG Master: Switching to '{account_name}' — "
        f"OCR text='{data['ocr_text']}' conf={data['ocr_conf']:.0%} "
        f"center={data['center']}"
    )
    AC.click_with_jitter(*data["center"])
    AC.random_delay()
    time.sleep(3.0)

    # Click OK on load dialog if present
    for _ in range(5):
        ok_coords = AC.find_template("account_load_okay.png")
        if ok_coords:
            AC.click_with_jitter(*ok_coords)
            AC.random_delay()
            break
        time.sleep(1.0)

    return True


# ---------------------------------------------------------------------------
# Cycling phase
# ---------------------------------------------------------------------------

def run_cycling_phase(
    last_trash_by_ingame: Dict[str, float],
    stop_fn: Callable[[], bool],
    status_fn: Callable[[str, str], None],
    overlay_fn: Optional[Callable[[list, str], None]] = None,
    hard_reset_fn: Optional[Callable[[], None]] = None,
    attack_accounts: Optional[List[str]] = None,
) -> str:
    """
    Cycle through all 7 accounts trashing one invalid challenge per visit.
    Accounts are visited in order of cooldown expiry (off-cooldown first).
    Stops when a full pass visits all accounts and finds nothing to trash.
    Returns 'clean' or RESULT_STOPPED.
    """
    challenge_region    = AC.CONFIG.get("clan_games_challenge_region", (700, 200, 1700, 800))
    challenge_conf      = float(AC.CONFIG.get("clan_games_challenge_confidence", AC.CONFIG["confidence_threshold"]))
    start_template      = AC.CONFIG.get("clan_games_start_template", "clan_games_start.png")
    challenge_templates = CGC._discover_challenge_templates()

    if not challenge_templates:
        AC.log("CG Master: No challenge templates — skipping cycling phase")
        return "clean"

    AC.log("CG Master: Entering cycling phase")
    _switch_fail_count = 0
    _accounts = attack_accounts if attack_accounts is not None else ATTACK_ACCOUNTS

    while not stop_fn():
        now = time.time()
        ordered = sorted(
            _accounts,
            key=lambda n: CGC._time_remaining(last_trash_by_ingame.get(n), now),
        )
        found_any_invalid = False

        for account in ordered:
            if stop_fn():
                return RESULT_STOPPED

            # Wait for this account's cooldown to expire
            rem = CGC._time_remaining(last_trash_by_ingame.get(account), time.time())
            if rem > 0:
                status_fn("Cycling", f"Waiting {CGC._format_remaining(rem)} for {account}…")
                AC.log(f"CG Master: Waiting {CGC._format_remaining(rem)} cooldown on {account}")
                while rem > 0 and not stop_fn():
                    time.sleep(min(rem, 2.0))
                    rem = CGC._time_remaining(last_trash_by_ingame.get(account), time.time())
                if stop_fn():
                    return RESULT_STOPPED

            status_fn("Cycling", f"Cycling {account}…")
            AC.log(f"CG Master: Cycling account '{account}'")

            if not _switch_to_specific_account(account, stop_fn, overlay_fn):
                _switch_fail_count += 1
                AC.log(f"CG Master: Could not switch to '{account}' — skipping (fail #{_switch_fail_count})")
                if _switch_fail_count >= 5:
                    _switch_fail_count = 0
                    if hard_reset_fn:
                        AC.log("CG Master: 5 consecutive switch failures in cycling — performing hard reset")
                        status_fn("Recovery", "Switch failed 5 times — performing hard reset…")
                        hard_reset_fn()
                continue
            _switch_fail_count = 0

            if stop_fn():
                return RESULT_STOPPED

            trashed, cooldown_detected = _cycle_one_account(
                challenge_region, challenge_conf, challenge_templates, start_template
            )

            if trashed:
                found_any_invalid = True
                last_trash_by_ingame[account] = time.time()
                AC.log(f"CG Master: Trashed a challenge on '{account}'")
                status_fn("Cycling", f"Trashed challenge on {account}")

            if cooldown_detected:
                CGC._set_min_remaining_cooldown(
                    last_trash_by_ingame, account, CGC.COOLDOWN_DETECTED_PENALTY_SECONDS
                )

            if stop_fn():
                return RESULT_STOPPED

        if not found_any_invalid:
            AC.log("CG Master: Cycling complete — no invalid challenges remain")
            status_fn("Cycling", "No invalid challenges remain")
            return "clean"

    return RESULT_STOPPED


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def run_master_bot(
    stop_fn: Callable[[], bool],
    status_fn: Callable[[str, str], None],
    account_completed_fn: Optional[Callable[[str], None]] = None,
    apply_settings_fn: Optional[Callable[[str], None]] = None,
    overlay_fn: Optional[Callable[[list, str], None]] = None,
    hard_reset_fn: Optional[Callable[[], None]] = None,
    attack_accounts: Optional[List[str]] = None,
) -> None:
    """
    Main entry point for the Clan Games Master Bot.

    stop_fn             — returns True when the user requests a stop
    status_fn           — (phase, message) callback for GUI updates
    account_completed_fn— called with account name when it reaches ~7000 pts
    apply_settings_fn   — called with account name to apply per-account config
    """
    from Autoclash import (
        phase1_enter_battle, phase2_prepare, phase2_execute,
        phase3_wait_for_return, phase4_upgrade, upgrade_account, CONFIG,
    )

    completed:          Set[str]            = set()
    last_trash_by_ingame: Dict[str, float]  = {}
    attack_idx = 0
    _switch_fail_count = 0
    _accounts = attack_accounts if attack_accounts is not None else ATTACK_ACCOUNTS

    # Disable the built-in per-attack clan games flow — we handle it ourselves
    _orig_cg_enabled = AC.CONFIG.get("clan_games_enabled", False)
    AC.CONFIG["clan_games_enabled"] = False

    AC.log("CG Master: === CLAN GAMES MASTER BOT START ===")
    status_fn("Starting", "Clan Games Master Bot starting…")

    try:
        while not stop_fn():
            # Advance past completed accounts
            while (
                attack_idx < len(_accounts)
                and _accounts[attack_idx] in completed
            ):
                attack_idx += 1

            if attack_idx >= len(_accounts):
                # All accounts completed — final cycling pass then stop
                AC.log("CG Master: All accounts completed — running final cycling pass")
                status_fn("Final Cycling", "All accounts done — clearing remaining bad challenges…")
                run_cycling_phase(last_trash_by_ingame, stop_fn, status_fn, overlay_fn, attack_accounts=_accounts)
                AC.log("CG Master: Final cycling done — stopping")
                status_fn("Done", "All accounts completed and all challenges cleared!")
                break

            current_account = _accounts[attack_idx]

            # Switch to this account
            status_fn("Switching", f"Switching to {current_account}…")
            if not _switch_to_specific_account(current_account, stop_fn, overlay_fn):
                _switch_fail_count += 1
                AC.log(f"CG Master: Failed to switch to '{current_account}' — retrying in 5s (fail #{_switch_fail_count})")
                status_fn("Switching", f"Switch to {current_account} failed — retrying…")
                if _switch_fail_count >= 5:
                    _switch_fail_count = 0
                    if hard_reset_fn:
                        AC.log("CG Master: 5 consecutive switch failures — performing hard reset")
                        status_fn("Recovery", "Switch failed 5 times — performing hard reset…")
                        hard_reset_fn()
                time.sleep(5.0)
                continue
            _switch_fail_count = 0

            if stop_fn():
                break

            if apply_settings_fn:
                apply_settings_fn(current_account)

            AC.log(f"CG Master: Starting attack loop on '{current_account}'")
            status_fn("Attacking", f"Attacking on {current_account}…")

            # -------------------------------------------------------------------
            # Attack loop for this account
            # -------------------------------------------------------------------
            while not stop_fn():

                result = open_stand_and_select_challenge(stop_fn)

                if result == RESULT_STOPPED:
                    break

                elif result == RESULT_COMPLETED:
                    AC.log(f"CG Master: '{current_account}' reached ~7000 pts — marking completed")
                    status_fn("Completed", f"{current_account} completed — moving to next account")
                    completed.add(current_account)
                    if account_completed_fn:
                        account_completed_fn(current_account)
                    break  # exit attack loop → outer loop picks next account

                elif result == RESULT_FAILED:
                    AC.log("CG Master: Stand not found — retrying in 3s")
                    status_fn("Retrying", "Stand not found — retrying…")
                    time.sleep(3.0)

                elif result == RESULT_NO_VALID:
                    AC.log(f"CG Master: No valid challenges on '{current_account}' — cycling")
                    status_fn("Cycling", "No valid challenges — entering cycling phase…")

                    cycle_result = run_cycling_phase(last_trash_by_ingame, stop_fn, status_fn, overlay_fn, hard_reset_fn)
                    if cycle_result == RESULT_STOPPED or stop_fn():
                        break

                    # Cycling done — switch back to the attacking account
                    status_fn("Switching", f"Cycling done — switching back to {current_account}…")
                    if not _switch_to_specific_account(current_account, stop_fn, overlay_fn):
                        _switch_fail_count += 1
                        AC.log(f"CG Master: Could not switch back to '{current_account}' — breaking to retry (fail #{_switch_fail_count})")
                        if _switch_fail_count >= 5:
                            _switch_fail_count = 0
                            if hard_reset_fn:
                                AC.log("CG Master: 5 consecutive switch failures — performing hard reset")
                                status_fn("Recovery", "Switch failed 5 times — performing hard reset…")
                                hard_reset_fn()
                        time.sleep(5.0)
                        break  # exit attack loop; outer loop will re-switch to current_account
                    else:
                        _switch_fail_count = 0
                        if apply_settings_fn:
                            apply_settings_fn(current_account)

                elif result == RESULT_HAS_VALID:
                    # Full attack sequence
                    if stop_fn():
                        break

                    status_fn("Phase 1", f"Entering battle on {current_account}…")
                    if not phase1_enter_battle(skip_account_check=False):
                        AC.log("CG Master: Phase 1 failed — retrying")
                        status_fn("Retrying", "Phase 1 failed — retrying…")
                        time.sleep(3.0)
                        continue

                    if stop_fn():
                        break

                    status_fn("Phase 2A", "Preparing battle…")
                    if not phase2_prepare():
                        AC.log("CG Master: Phase 2A failed — retrying")
                        time.sleep(3.0)
                        continue

                    if stop_fn():
                        break

                    status_fn("Phase 2B", "Deploying troops…")
                    if not phase2_execute():
                        AC.log("CG Master: Phase 2B failed — retrying")
                        time.sleep(3.0)
                        continue

                    if stop_fn():
                        break

                    status_fn("Phase 3", "Waiting for battle to end…")
                    if not phase3_wait_for_return():
                        AC.log("CG Master: Phase 3 failed — retrying")
                        time.sleep(3.0)
                        continue

                    # Optional upgrades (respects per-account config)
                    time.sleep(5.0)
                    if CONFIG.get("auto_upgrade_walls", True):
                        status_fn("Phase 4", "Upgrading walls…")
                        phase4_upgrade()
                    if CONFIG.get("auto_upgrade_storages", True):
                        status_fn("Phase 5", "Upgrading account…")
                        upgrade_account()

                    AC.log("CG Master: Attack complete — looping back to challenge check")
                    status_fn("Attacking", f"Attack done — checking next challenge on {current_account}…")

    finally:
        AC.CONFIG["clan_games_enabled"] = _orig_cg_enabled
        AC.log("CG Master: === CLAN GAMES MASTER BOT END ===")
