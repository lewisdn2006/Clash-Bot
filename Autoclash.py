#!/usr/bin/env python3
"""
Clash of Clans Automation Script
=================================
Automates a 3-phase battle workflow using template matching and simulated input.

Required packages (install with pip):
    pip install opencv-python numpy pyautogui pillow

Usage:
    1. Set your template image folder path in CONFIG below
    2. Configure ten_battle_points and abilities_click_coord with actual coordinates
    3. Run: python Autoclash.py
    4. Press Ctrl+C to stop gracefully
"""

import cv2
import numpy as np
import pyautogui
import time
import random
import csv
import json
import re
import subprocess
import tempfile
import os
import ctypes
from ctypes import c_int, c_uint, c_ulong
from ctypes import wintypes
from collections import Counter
import sys
from pathlib import Path
from typing import Optional, Tuple, List
from PIL import Image, ImageEnhance
import vision as _vision

# Optional: keyboard module for global Space key detection
try:
    import keyboard  # type: ignore
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False

# Optional: pytesseract for OCR
try:
    import pytesseract
    import logging
    # Configure Tesseract executable path (update if installed elsewhere)
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    # Quiet pytesseract's verbose DEBUG output
    logging.getLogger('pytesseract').setLevel(logging.WARNING)
    HAS_PYTESSERACT = True
except ImportError:
    HAS_PYTESSERACT = False

# Disable PyAutoGUI failsafe (move mouse to corner to stop)
pyautogui.FAILSAFE = False

# ================================
# WINDOWS API SCROLL (Works with games)
# ================================
MOUSEEVENTF_WHEEL = 0x0800
WHEEL_DELTA = 120

# wintypes.ULONG_PTR is missing in some Python builds; define a compatible alias
try:
    ULONG_PTR = wintypes.ULONG_PTR  # type: ignore[attr-defined]
except AttributeError:
    ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == ctypes.sizeof(ctypes.c_ulonglong) else ctypes.c_ulong


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("mi", MOUSEINPUT)]


def get_screen_center() -> Tuple[int, int]:
    """Get the center coordinates of the screen dynamically."""
    screen_width, screen_height = pyautogui.size()
    return screen_width // 2, screen_height // 2


def _send_wheel(mouse_data: int) -> None:
    """Low-level SendInput wrapper for mouse wheel."""
    mouse_input = MOUSEINPUT(0, 0, mouse_data, MOUSEEVENTF_WHEEL, 0, 0)
    input_struct = INPUT(0, mouse_input)
    sent = ctypes.windll.user32.SendInput(1, ctypes.byref(input_struct), ctypes.sizeof(INPUT))
    if sent != 1:
        # Fallback to pyautogui if SendInput failed
        pyautogui.scroll(mouse_data // max(1, WHEEL_DELTA))


def scroll_api(amount: int = WHEEL_DELTA, direction: str = "down"):
    """
    Scroll using Windows API (works with games).
    
    Args:
        amount: Scroll magnitude (positive integer)
        direction: "up" or "down"
    """
    center_x, center_y = get_screen_center()
    pyautogui.moveTo(center_x, center_y, duration=0.05)

    scroll_amount = abs(int(amount))
    if direction.lower() == "down":
        scroll_amount = -scroll_amount

    _send_wheel(scroll_amount)


def scroll_down_api(amount: int = WHEEL_DELTA):
    """Scroll down using Windows API (works with games)."""
    scroll_api(amount, "down")


def scroll_random(amount: int = WHEEL_DELTA * 3):
    """Randomly scroll with 60% down / 40% up bias."""
    direction = "down" if random.random() < 0.6 else "up"
    scroll_api(amount, direction)
    log(f"Random scroll: {direction.upper()}")


def scroll_down_5_times(amount: int = WHEEL_DELTA * 3):
    """Scroll down 5 times with delays."""
    for i in range(5):
        scroll_api(amount, "down")
        time.sleep(0.2)
    log("Scrolled down 5 times")

# ================================
# CONFIGURATION
# ================================
CONFIG = {
    # Path to folder containing template images (use "." for same folder as script)
    "image_folder": ".",  # "." means same folder as this Python file
    
    # Template image filenames
    "attack_button": "attack_button.png",
    "find_button": "find_button.png",
    "enter_battle": "enter_battle.png",
    "end_button": "end_button.png",
    "surrender_button": "surrender_button.png",
    "edrag_button": "edrag_button.png",
    "drag_button": "drag_button.png",
    "azdrag_button": "Azdrag.png",
    "barb_button": "barb_button.png",
    "event_troop_button": "edrag_button.png",
    "return_button": "return_button.png",
    "claim_reward_button": "claim_reward_button.png",
    "try_again_button": "try_again_button.png",
    "reload_game_button": "reload_game.png",
    "layout_editor_text": "layout_editor_text.png",
    
    # Troop type selection ("edrag", "drag", "azdrag", or "barbarian")
    "troop_type": "edrag",  # "drag"=dragons, "edrag"=electro dragons, "azdrag"=az drags, "barbarian"=barbarians
    
    # Number of battles to run (None or <=0 = infinite loop)
    "num_runs": None,  # Set to integer like 10 for limited runs, or None for infinite
    
    # Spells and air defense targets (all 15 levels)
    "spell_icon": "spell_icon.png",
    "ad_1": "1ad.png",
    "ad_2": "2ad.png",
    "ad_3": "3ad.png",
    "ad_4": "4ad.png",
    "ad_5": "5ad.png",
    "ad_6": "6ad.png",
    "ad_7": "7ad.png",
    "ad_8": "8ad.png",
    "ad_9": "9ad.png",
    "ad_10": "10ad.png",
    "ad_11": "11ad.png",
    "ad_12": "12ad.png",
    "ad_13": "13ad.png",
    "ad_14": "14ad.png",
    "ad_15": "15ad.png",
    
    # Template matching confidence (0.0 to 1.0, higher = stricter match)
    "confidence_threshold": 0.75,       # Default for most templates
    "ad_confidence_threshold": 0.70,    # Air defenses only
    
    # Region to search for air defenses (x1, y1, x2, y2)
    "search_region": (289, 36, 1566, 902),
    
    # Phase 3: seconds between checks for return button
    "polling_interval_phase3": 5,

    # Minimum acceptable loot to proceed with a battle
    "min_loot_amount": 50000,
    
    # Random click jitter in pixels (adds randomness to click positions)
    "click_randomness_px": 5,
    
    # Random delay ranges between actions (in seconds)
    "min_delay": 0.035,
    "max_delay": 0.075,

    # Stats CSV file for per-account tracking
    "stats_csv": "account_stats.csv",
    
    # Template search parameters
    "max_search_attempts": 10,  # Max attempts to find a template
    "wait_between_attempts": 1.0,  # Seconds to wait between search attempts

    # Find button selection mode (True = rightmost for ranked, False = leftmost)
    "do_ranked": True,

    # Clan Games automation (optional, runs in Phase 1 before attack flow)
    "clan_games_enabled": False,
    "request_enabled": False,
    "clan_games_stand_template": "clan_games_stand.png",
    "clan_games_stand_confidence": 0.639,
    "clan_games_start_template": "clan_games_start.png",
    "clan_games_cooldown_template": "clan_games_cooldown.png",
    "clan_games_challenge_prefix": "clan_games_challenge_",
    "clan_games_challenge_confidence": 0.9,
    "clan_games_challenge_region": (622, 180, 1732, 847),
    "clan_games_stand_retry_attempts": 10,
    "clan_games_stand_retry_delay": 1.0,
    
    # *** FILL THESE IN WITH YOUR ACTUAL COORDINATES ***
    # 10 battle points to click in order during Phase 2
    "ten_battle_points": [
        (490, 768),   # Point 1
        (403, 694),   # Point 2
        (188, 530),   # Point 3
        (241, 442),   # Point 4
        (421, 312),   # Point 5
        (583, 188),   # Point 6
        (748, 74),    # Point 7
        (1228, 109),  # Point 8
        (1340, 193),  # Point 9
        (1477, 304),  # Point 10
    ],

    # Coordinate to click while pressing Q, W, E, R keys (abilities)
    "abilities_click_coord": (641, 144),
    
    # Number of battle points to click (e.g., 10 = all, 8 = first 8 only)
    "num_battle_points": 10,
    
    # Number of heroes/ability points to click (e.g., 4 = all, 2 = first 2 only)
    "num_heroes": 4,
    
    # Event and Siege Machine features
    "event_active": False,  # Set to True to place event dragons
    "event_troop_count": 30,
    "siege_machine_active": False,  # Set to True to place siege machine
    
    # Time to wait (in seconds) after placing all heroes before activating their abilities
    "time_before_ability": 15,
    
        # Maximum number of spells to deploy (default: 15)
        "max_spell_clicks": 15,
    
    
    # Spell deployment coordinate validation
    "rejected_region_size": 20,  # Size of rejected region square (±10 pixels by default)
    
    # Auto upgrade walls phase (True = run Phase 4, False = skip Phase 4)
    "auto_upgrade_walls": True,

    # Auto upgrade storages phase (True = run Phase 5, False = skip Phase 5)
    "auto_upgrade_storages": True,

    # Gem speed-up upgrades (True = use gems to speed up upgrades after confirming)
    "gem_upgrades": False,

    # Fill army before attacking (True = top up army if not full before entering battle)
    "fill_army": False,

    # Auto Min Loot: dynamically set min_loot_amount to 50% of the highest gold earned in a single attack
    "dynamic_loot": False,

    # ================================
    # PHASE 4: WALL UPGRADE CONFIGURATION
    # ================================
    "phase4": {
        # UI element search boxes (x1, y1, x2, y2)
        "more_box": (505, 893, 1288, 958),
        "add_box": (733, 880, 955, 936),
        "remove_box": (500, 880, 707, 930),
        "upgrade_box_gold": (977, 880, 1188, 936),
        "upgrade_box_elixir": (1133, 880, 1344, 936),
        "upgrade_box_gold_alt": (977, 891, 1188, 936),
        "upgrade_box_elixir_alt": (1133, 891, 1344, 936),
        
        # Template image filenames for Phase 4
        "confirm_singular_template": "confirm_singular_wall.png",
        "okay_upgrade_template": "okay_upgrade.png",
        "star_bonus_okay_template": "star_bonus_okay.png",
        
        # Retry and timing parameters
        "max_retry_attempts": 5,
        "pixel_tolerance": 40,           # Euclidean distance tolerance for red pixel matching
        "max_add_clicks": 250,           # safety cap for Add loop iterations
        "add_click_delay": 0.12,         # seconds between Add clicks
        "post_click_delay": 0.25,        # delay after clicking Add/Upgrade/Remove for UI update
        
        # Pixel coordinate sets (absolute screen coordinates)
        # Gold resource full indicator pixels
        "gold_pixel_set": [
            (1075, 816), (1057, 816), (1075, 821), (1154, 816), (1155, 821)
        ],
        # Elixir resource full indicator pixels
        "elixir_pixel_set": [
            (1233, 816), (1215, 816), (1233, 821), (1312, 816), (1313, 821)
        ],
        # Alternate pixel set (resource-independent trigger)
        "alternate_pixel_set": [
            (758, 900), (763, 908), (778, 907), (838, 900), (842, 909), (874, 908)
        ],
        
        # Target color for red pixel detection (RGB tuple)
        "target_red_color": (224, 120, 113),
    },
}

# Tracks the account name for which gem upgrades were just disabled (no_gems detected).
# Workers poll pop_gem_upgrades_disabled() after each battle to persist the change to JSON.
_gem_upgrades_disabled_account: str = ""


# ================================
# AUTO LOOT TRACKER
# ================================


class AutoLootTracker:
    """Track loot via OCR on the end-of-battle screen."""

    def __init__(self) -> None:
        # Regions aligned to Loottracker.py (x1, y1, x2, y2)
        self.gold_region = (754, 448, 986, 503)
        self.elixir_region = (754, 521, 986, 577)
        self.dark_elixir_region = (816, 590, 986, 646)

        # Bonus/additional loot beneath the main amounts (same as Loottracker.py)
        self.additional_gold_region = (1252, 539, 1404, 584)
        self.additional_elixir_region = (1249, 593, 1405, 644)
        self.additional_dark_elixir_region = (1283, 648, 1404, 697)

        # Star pixel coordinates and target color (no star data in Loottracker.py; kept existing)
        self.star_pixels = [(767, 247), (1002, 230), (1144, 279)]
        self.star_target_color = (215, 215, 215)
        self.star_color_tolerance = 51  # Euclidean distance tolerance

        self.total_gold = 0
        self.total_elixir = 0
        self.total_dark_elixir = 0
        self.battle_count = 0
        
        # Star tracking
        self.star_counts = {0: 0, 1: 0, 2: 0, 3: 0}  # Count of battles by stars earned
        
        self.start_time = time.time()

    def _extract_number(self, region: tuple, label: str, max_value: Optional[int] = None) -> Optional[int]:
        """Run multi-strategy OCR and return the most common parsed value.
        
        Uses the same enhanced preprocessing logic as Loottracker.py for reliability:
        - 3x upscaling for small text
        - Multiple preprocessing strategies
        - Robust Tesseract configs with character whitelists
        - Majority vote with longest-digit tie-breaker
        """
        if not HAS_PYTESSERACT:
            log(f"WARNING: pytesseract not installed, skipping {label} extraction")
            return None

        try:
            x1, y1, x2, y2 = region
            screenshot = pyautogui.screenshot(region=(x1, y1, x2 - x1, y2 - y1))
            screenshot_np = np.array(screenshot)

            # Convert to grayscale
            gray = cv2.cvtColor(screenshot_np, cv2.COLOR_RGB2GRAY)
            
            # Upscale image 3x for better OCR (helps capture small/thin digits)
            scale_factor = 3
            gray_upscaled = cv2.resize(
                gray,
                None,
                fx=scale_factor,
                fy=scale_factor,
                interpolation=cv2.INTER_CUBIC
            )

            # Try multiple preprocessing strategies and collect results
            results = []
            
            # Strategy 1: OTSU thresholding
            _, thresh1 = cv2.threshold(gray_upscaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            config1 = r'--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789,'
            text1 = pytesseract.image_to_string(thresh1, config=config1).strip()
            results.append(("OTSU", text1))
            
            # Strategy 2: Adaptive thresholding
            thresh2 = cv2.adaptiveThreshold(
                gray_upscaled, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
            )
            text2 = pytesseract.image_to_string(thresh2, config=config1).strip()
            results.append(("Adaptive", text2))
            
            # Strategy 3: Inverted OTSU (for light text on dark background)
            _, thresh3 = cv2.threshold(gray_upscaled, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            text3 = pytesseract.image_to_string(thresh3, config=config1).strip()
            results.append(("Inverted OTSU", text3))
            
            # Strategy 4: Simple binary threshold at 127
            _, thresh4 = cv2.threshold(gray_upscaled, 127, 255, cv2.THRESH_BINARY)
            text4 = pytesseract.image_to_string(thresh4, config=config1).strip()
            results.append(("Binary 127", text4))
            
            # Strategy 5: With bilateral filtering (noise reduction while preserving edges)
            bilateral = cv2.bilateralFilter(gray_upscaled, 9, 75, 75)
            _, thresh5 = cv2.threshold(bilateral, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            text5 = pytesseract.image_to_string(thresh5, config=config1).strip()
            results.append(("Bilateral+OTSU", text5))
            
            # Strategy 6: PSM 8 (single word) instead of PSM 7 (single line)
            config2 = r'--oem 3 --psm 8 -c tessedit_char_whitelist=0123456789,'
            text6 = pytesseract.image_to_string(thresh1, config=config2).strip()
            results.append(("OTSU+PSM8", text6))

            # Parse all results and tally the most common cleaned value
            valid_numbers = []  # (strategy, raw_text, cleaned_value)
            for strategy_name, text in results:
                if text:
                    # Clean text: strip separators and any non-digits (incl. stray '+')
                    cleaned = text.replace(',', '').replace(' ', '').replace('.', '').replace('+', '').replace('-', '')
                    cleaned = ''.join(c for c in cleaned if c.isdigit())
                    if cleaned:
                        value = int(cleaned)
                        valid_numbers.append((strategy_name, text, value))
                        log(f"  [{label}] Strategy '{strategy_name}': '{text}' -> {value:,}")

            if not valid_numbers:
                log(f"✗ No valid numbers for {label}")
                return None

            # Majority vote by cleaned numeric value; tie-breaker = longest digit length
            counts = Counter(val for _, _, val in valid_numbers)
            most_common_value, most_common_freq = counts.most_common(1)[0]
            # If multiple values share the top frequency, prefer the one with more digits
            tied_values = [val for val, freq in counts.items() if freq == most_common_freq]
            chosen_value = max(tied_values, key=lambda v: len(str(v)))
            best_entry = next((entry for entry in valid_numbers if entry[2] == chosen_value), valid_numbers[0])
            _, _, best_value = best_entry

            if max_value is not None and best_value > max_value:
                log(f"⚠ {label} value {best_value:,} exceeds limit {max_value:,} (ignored)")
                return None

            log(f"✓ {label.upper()} extracted: {best_value:,} (most common, {most_common_freq} vote(s))")
            if len(valid_numbers) > 1:
                log(f"  (Tried {len(valid_numbers)} successful strategies, chose most common; tie-breaker = longest)")
            return best_value

        except Exception as e:
            log(f"✗ Error extracting {label}: {e}")
            return None

    def _check_stars(self) -> int:
        """Check how many stars were earned by examining pixel colors.
        
        Returns number of stars (0-3) based on how many of the 3 star pixels
        match the target color within tolerance.
        """
        try:
            screenshot = pyautogui.screenshot()
            screenshot_np = np.array(screenshot)
            
            stars_earned = 0
            for x, y in self.star_pixels:
                pixel_color = screenshot_np[y, x]  # numpy is [row, col] = [y, x]
                distance = np.sqrt(np.sum((pixel_color.astype(int) - np.array(self.star_target_color, dtype=int)) ** 2))
                
                log(f"  Star pixel at ({x}, {y}): RGB{tuple(pixel_color)}, distance: {distance:.2f}")
                
                if distance <= self.star_color_tolerance:
                    stars_earned += 1
            
            log(f"✓ Battle earned {stars_earned} star(s)")
            return stars_earned
        
        except Exception as e:
            log(f"✗ Error checking stars: {e}")
            return 0

    def extract_and_record(self) -> dict:
        """Extract main and bonus loot, update totals, and return snapshot."""
        # Check number of stars first
        stars_earned = self._check_stars()
        
        # Extract main loot (always)
        gold = self._extract_number(self.gold_region, "gold", max_value=3_000_000) or 0
        elixir = self._extract_number(self.elixir_region, "elixir", max_value=3_000_000) or 0
        dark = self._extract_number(self.dark_elixir_region, "dark elixir", max_value=30_000) or 0

        # Extract additional loot only if stars > 0
        if stars_earned > 0:
            log("Stars earned > 0, extracting additional loot...")
            add_gold = self._extract_number(self.additional_gold_region, "additional gold", max_value=3_000_000) or 0
            add_elixir = self._extract_number(self.additional_elixir_region, "additional elixir", max_value=3_000_000) or 0
            add_dark = self._extract_number(self.additional_dark_elixir_region, "additional dark elixir", max_value=30_000) or 0
        else:
            log("No stars earned (0 stars), skipping additional loot extraction")
            add_gold = 0
            add_elixir = 0
            add_dark = 0

        self.total_gold += gold + add_gold
        self.total_elixir += elixir + add_elixir
        self.total_dark_elixir += dark + add_dark
        self.battle_count += 1
        self.star_counts[stars_earned] += 1

        # Save last snapshot for external consumers
        self.last_snapshot = {
            "stars": stars_earned,
            "gold": gold,
            "elixir": elixir,
            "dark_elixir": dark,
            "add_gold": add_gold,
            "add_elixir": add_elixir,
            "add_dark": add_dark,
        }

        snapshot = {
            "stars": stars_earned,
            "gold": gold,
            "elixir": elixir,
            "dark_elixir": dark,
            "add_gold": add_gold,
            "add_elixir": add_elixir,
            "add_dark": add_dark,
            "total_gold": self.total_gold,
            "total_elixir": self.total_elixir,
            "total_dark_elixir": self.total_dark_elixir,
            "battle_count": self.battle_count,
        }

        log(
            f"LOOT SNAPSHOT: {stars_earned}★ | gold={gold:,} (+{add_gold:,}) | "
            f"elixir={elixir:,} (+{add_elixir:,}) | dark={dark:,} (+{add_dark:,})"
        )
        log(
            f"LOOT TOTALS: gold={self.total_gold:,}, elixir={self.total_elixir:,}, "
            f"dark={self.total_dark_elixir:,} after {self.battle_count} battle(s)"
        )
        return snapshot

    def get_stats(self) -> dict:
        """Return totals and averages per attack and per minute."""
        elapsed_seconds = max(time.time() - self.start_time, 1)
        elapsed_minutes = elapsed_seconds / 60.0
        battles = max(self.battle_count, 1)

        return {
            "total_gold": self.total_gold,
            "total_elixir": self.total_elixir,
            "total_dark_elixir": self.total_dark_elixir,
            "battle_count": self.battle_count,
            "avg_gold_per_attack": self.total_gold / battles,
            "avg_elixir_per_attack": self.total_elixir / battles,
            "avg_dark_per_attack": self.total_dark_elixir / battles,
            "avg_gold_per_min": self.total_gold / elapsed_minutes,
            "avg_elixir_per_min": self.total_elixir / elapsed_minutes,
            "avg_dark_per_min": self.total_dark_elixir / elapsed_minutes,
            "elapsed_minutes": elapsed_minutes,
            "star_counts": self.star_counts.copy(),
            "zero_star_battles": self.star_counts[0],
            "one_star_battles": self.star_counts[1],
            "two_star_battles": self.star_counts[2],
            "three_star_battles": self.star_counts[3],
        }






# ================================
# ACCOUNT STATS HELPERS
# ================================

APPROVED_ACCOUNTS = {"lewis", "williamleeming", "steve", "lewis8", "lewis7", "lewis6", "lewis5", "lewis4", "lewis3", "djbillgates22", "djbillgates23", "djbillgates24", "djbillgates25", "djbillgates26", "djbillgates27", "djbillgates28", "djbillgates29", "djbillgates30", "djbillgates31", "djbillgates32", "djbillgates33", "djbillgates34", "djbillgates35", "djbillgates36", "djbillgates37", "djbillgates38", "djbillgates39", "djbillgates40", "djbillgates41"}
ACCOUNT_NAME_BOX = (111, 13, 289, 41)  # (x1, y1, x2, y2) top-left name area


def _match_approved_account(name: str) -> str | None:
    """Return the canonical account name if OCR name matches APPROVED_ACCOUNTS, else None.

    Tries the name as-is, then swaps each U↔J one at a time to handle common OCR confusion
    where 'J' is misread as 'U' (e.g. 'DUBillGates26' should match 'djbillgates26').
    """
    name_lower = name.lower()
    if name_lower in APPROVED_ACCOUNTS:
        return name_lower
    for i, ch in enumerate(name_lower):
        if ch in ("u", "j"):
            swapped = name_lower[:i] + ("j" if ch == "u" else "u") + name_lower[i + 1:]
            if swapped in APPROVED_ACCOUNTS:
                return swapped
    return None
TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def normalize_account_name(name: str) -> str:
    return (name or "").strip().lower()


def stats_csv_path() -> Path:
    return Path(__file__).parent / CONFIG.get("stats_csv", "account_stats.csv")


def load_account_stats() -> dict:
    path = stats_csv_path()
    data = {}
    numeric_fields = [
        "total_time_seconds",
        "total_gold",
        "total_elixir",
        "total_dark_elixir",
        "stars_0",
        "stars_1",
        "stars_2",
        "stars_3",
        "attacks",
        "walls_upgraded",
    ]
    if path.exists():
        with path.open(newline="", mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = normalize_account_name(row.get("account", ""))
                if not name:
                    continue
                if name not in data:
                    row["account"] = name
                    data[name] = row
                    continue

                # Merge duplicate entries (case-insensitive) by summing numeric fields
                existing = data[name]
                for field in numeric_fields:
                    try:
                        existing_val = float(existing.get(field, "0") or 0)
                    except Exception:
                        existing_val = 0.0
                    try:
                        new_val = float(row.get(field, "0") or 0)
                    except Exception:
                        new_val = 0.0
                    existing[field] = str(existing_val + new_val)
                existing["account"] = name
    return data


def save_account_stats(data: dict) -> None:
    path = stats_csv_path()
    fieldnames = [
        "account",
        "total_time_seconds",
        "total_gold",
        "total_elixir",
        "total_dark_elixir",
        "stars_0",
        "stars_1",
        "stars_2",
        "stars_3",
        "attacks",
        "walls_upgraded",
    ]
    with path.open(newline="", mode="w", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for name, row in data.items():
            writer.writerow({fn: row.get(fn, "0") for fn in fieldnames})


def ensure_account_row(data: dict, account: str) -> dict:
    account = normalize_account_name(account)
    if account not in data:
        data[account] = {
            "account": account,
            "total_time_seconds": "0",
            "total_gold": "0",
            "total_elixir": "0",
            "total_dark_elixir": "0",
            "stars_0": "0",
            "stars_1": "0",
            "stars_2": "0",
            "stars_3": "0",
            "attacks": "0",
            "walls_upgraded": "0",
        }
    return data[account]


def update_account_stats(account: str, snapshot: dict, battle_duration_sec: float, walls_upgraded: int = 0) -> None:
    if not snapshot:
        log("Phase4: No loot snapshot available; skipping stats update.")
        return
    account = normalize_account_name(account)
    data = load_account_stats()
    row = ensure_account_row(data, account)

    def add_field(key: str, amount: float):
        current = float(row.get(key, "0") or 0)
        row[key] = str(current + amount)

    # Update time and loot
    add_field("total_time_seconds", battle_duration_sec)
    add_field("total_gold", snapshot.get("gold", 0) + snapshot.get("add_gold", 0))
    add_field("total_elixir", snapshot.get("elixir", 0) + snapshot.get("add_elixir", 0))
    add_field("total_dark_elixir", snapshot.get("dark_elixir", 0) + snapshot.get("add_dark", 0))

    # Stars and attacks
    stars = int(snapshot.get("stars", 0))
    stars_key = f"stars_{stars}" if stars in (0, 1, 2, 3) else None
    if stars_key:
        add_field(stars_key, 1)
    add_field("attacks", 1)
    add_field("walls_upgraded", walls_upgraded)

    row["account"] = account
    data[account] = row
    save_account_stats(data)
    log(f"Stats updated for account '{account}' (+{walls_upgraded} walls)")


# ================================
# ACCOUNT NAME OCR
# ================================


def _clean_text(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "", text or "").strip()


def read_account_name(box: tuple = ACCOUNT_NAME_BOX) -> str:
    """Capture name box and OCR using tesseract (subprocess, same as tesseract_reader)."""
    # Capture region
    screenshot = pyautogui.screenshot(region=(box[0], box[1], box[2] - box[0], box[3] - box[1]))

    # Preprocess similar to tesseract_reader
    if screenshot.mode != "L":
        screenshot = screenshot.convert("L")
    w, h = screenshot.size
    screenshot = screenshot.resize((w * 3, h * 3), Image.Resampling.LANCZOS)
    screenshot = ImageEnhance.Contrast(screenshot).enhance(2.0)
    screenshot = ImageEnhance.Brightness(screenshot).enhance(1.1)

    # Save to temp file
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        temp_image = tmp.name
        screenshot.save(temp_image)

    try:
        result = subprocess.run(
            [TESSERACT_PATH, temp_image, "stdout"],
            capture_output=True,
            text=False,  # Don't auto-decode; handle manually
            timeout=10,
        )
        
        # Manually decode with UTF-8, fallback to latin-1 if needed
        try:
            raw_text = result.stdout.decode('utf-8').strip()
        except (UnicodeDecodeError, AttributeError):
            try:
                raw_text = result.stdout.decode('latin-1', errors='ignore').strip()
            except (UnicodeDecodeError, AttributeError):
                raw_text = ""
        
        if not raw_text:
            log(f"Account OCR: No text returned from Tesseract")
            return ""

        # If OCR returns multiple lines, keep only the first non-empty line
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        if len(lines) > 1:
            text = lines[0]
        else:
            text = raw_text

        # If OCR output is long (likely spaces/noise), limit to first 20 chars
        if len(text) > 20:
            text = text[:20]

        cleaned = _clean_text(text)
        log(f"Account OCR raw='{raw_text}' cleaned='{cleaned}'")
        return cleaned
    except Exception as e:
        log(f"Account OCR failed: {e}")
        return ""
    finally:
        try:
            os.remove(temp_image)
        except Exception:
            pass




# ================================
# HELPER FUNCTIONS
# ================================

def log(message: str) -> None:
    """Print timestamped log message."""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")


def check_for_error_buttons_in_screenshot(screenshot: Image.Image) -> bool:
    """
    Check for error recovery buttons using a provided screenshot.
    Returns True if a recovery button was found and clicked.
    """
    recovery_buttons = [
        ("try_again_button", "try_again_button"),
        ("reload_game_button", "reload_game"),
    ]

    for config_key, label in recovery_buttons:
        template_name = CONFIG.get(config_key)
        if not template_name:
            continue
        coords = find_template(template_name, confidence=0.7, screenshot=screenshot)
        if coords:
            log(f"ERROR DETECTED: {label} found at ({coords[0]}, {coords[1]})")
            log(f"Clicking {label} to recover from error...")
            click_with_jitter(*coords)
            time.sleep(2)  # Wait for game to reload
            return True

    # Check for no_gems error: out of gems for speed-ups
    no_gems_coords = find_template("no_gems.png", confidence=0.7, screenshot=screenshot)
    if no_gems_coords:
        global _gem_upgrades_disabled_account
        current_acct = (_default_session.current_account_name or "") if _default_session else ""
        log(f"GEM ERROR: no_gems.png found — no gems remaining for '{current_acct}'. Dismissing and disabling gem upgrades.")
        screen_w, screen_h = pyautogui.size()
        click_with_jitter(screen_w * 3 // 4, screen_h // 2)
        time.sleep(0.5)
        CONFIG["gem_upgrades"] = False
        _gem_upgrades_disabled_account = current_acct
        return True

    return False


def check_for_error_button() -> bool:
    """
    Check for error recovery buttons (try_again and reload_game).
    If found, click it and return True to signal restart from Phase 1.
    Returns False if button not found (normal operation).
    """
    screenshot = pyautogui.screenshot()
    return check_for_error_buttons_in_screenshot(screenshot)


def is_coord_valid(x: float, y: float) -> bool:
    """
    Validate spell deployment coordinate against two compound constraints.
    
    Constraint A: (136/185)*x + (42954/185) > y > (565/768)*x - (286531/384)
    Constraint B: (-247/324)*x + (573359/324) > y > (-541/718)*x + (543849/718)
    #(1539.0, 823.0)

    Both constraints must be satisfied (AND logic) for the coordinate to be valid.
    Boundary values are treated as invalid (strict > comparisons).
    
    Args:
        x: X coordinate (float)
        y: Y coordinate (float)
    
    Returns:
        True if both constraints are satisfied, False otherwise
    """
    try:
        x_f = float(x)
        y_f = float(y)
        
        # Constraint A: (136/185)*x + (42954/185) > y > (565/768)*x - (286531/384)
        constraint_a_upper = (136.0 / 185.0) * x_f + (42954.0 / 185.0)
        constraint_a_lower = (565.0 / 768.0) * x_f - (286531.0 / 384.0)
        constraint_a_satisfied = constraint_a_upper > y_f > constraint_a_lower
        
        # Constraint B: (-247/324)*x + (573359/324) > y > (-541/718)*x + (543849/718)
        constraint_b_upper = (-247.0 / 324.0) * x_f + (573359.0 / 324.0)
        constraint_b_lower = (-541.0 / 718.0) * x_f + (543849.0 / 718.0)
        constraint_b_satisfied = constraint_b_upper > y_f > constraint_b_lower
        
        # Both constraints must be satisfied
        is_valid = constraint_a_satisfied and constraint_b_satisfied
        
        # Log the detailed evaluation for debugging
        log(f"  [VALIDATION] ({x_f:.1f}, {y_f:.1f}): "
            f"A({constraint_a_lower:.1f} < {y_f:.1f} < {constraint_a_upper:.1f})={constraint_a_satisfied} "
            f"B({constraint_b_lower:.1f} < {y_f:.1f} < {constraint_b_upper:.1f})={constraint_b_satisfied} "
            f"-> {'VALID' if is_valid else 'INVALID'}")
        
        return is_valid
    except Exception as e:
        log(f"  [VALIDATION ERROR] Failed to validate ({x}, {y}): {e}")
        return False


def is_in_rejected_region(x: float, y: float, rejected_regions: List[Tuple[float, float]]) -> bool:
    """
    Check if a coordinate falls within any rejected region.
    
    A rejected region is a square of size CONFIG["rejected_region_size"] centered on a rejected coordinate.
    Default: 20-pixel square = ±10 pixels in x and y.
    
    Args:
        x: X coordinate to check
        y: Y coordinate to check
        rejected_regions: List of (center_x, center_y) for rejected regions
    
    Returns:
        True if coordinate is inside any rejected region, False otherwise
    """
    if not rejected_regions:
        return False
    
    region_size = CONFIG.get("rejected_region_size", 20)
    half_size = region_size / 2.0
    
    for center_x, center_y in rejected_regions:
        if (center_x - half_size <= x <= center_x + half_size and 
            center_y - half_size <= y <= center_y + half_size):
            return True
    
    return False


def _get_region_image(x1: int, y1: int, x2: int, y2: int, screenshot: Optional[Image.Image] = None) -> Image.Image:
    if screenshot is None:
        return pyautogui.screenshot(region=(x1, y1, x2 - x1, y2 - y1))
    if isinstance(screenshot, np.ndarray):
        region = screenshot[y1:y2, x1:x2]
        return Image.fromarray(region)
    return screenshot.crop((x1, y1, x2, y2)) 


def _ocr_image_to_text(image: Image.Image, config: str = "--psm 6") -> str:
    return pytesseract.image_to_string(np.array(image), config=config).strip()


def _ocr_image_to_data(image: Image.Image, config: str = "--psm 6") -> dict:
    return pytesseract.image_to_data(np.array(image), config=config, output_type=pytesseract.Output.DICT)


def _digits_from_text(text: str, replacements: Optional[dict] = None) -> str:
    if replacements:
        for src, dest in replacements.items():
            text = text.replace(src, dest)
    return "".join(c for c in text if c.isdigit())


def extract_loot_amount(x1: int, y1: int, x2: int, y2: int, screenshot: Optional[Image.Image] = None) -> Optional[int]:
    """Extract text (loot amount) from screen region using OCR and return as integer."""
    if not HAS_PYTESSERACT:
        log("WARNING: pytesseract not installed, skipping loot extraction")
        return None
    
    try:
        region_img = _get_region_image(x1, y1, x2, y2, screenshot=screenshot)
        loot_text = _ocr_image_to_text(region_img)
        
        if loot_text:
            log(f"Raw OCR text: {loot_text}")
            replacements = {"$": "5", "O": "0", "o": "0", "S": "5", "s": "5"}
            cleaned = _digits_from_text(loot_text, replacements=replacements)
            
            if cleaned:
                loot_value = int(cleaned)
                log(f"Loot amount extracted: {loot_value:,}")
                return loot_value
            log("No digits found in extracted text")
            return None
        log("No loot amount found in region")
        return None
    except Exception as e:
        log(f"Error extracting loot: {e}")
        return None


def extract_number_from_region(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    label: str = "number",
    screenshot: Optional[Image.Image] = None,
) -> Optional[int]:
    """Extract number from screen region using OCR and return as integer."""
    if not HAS_PYTESSERACT:
        log(f"WARNING: pytesseract not installed, skipping {label} extraction")
        return None
    
    try:
        region_img = _get_region_image(x1, y1, x2, y2, screenshot=screenshot)
        text = _ocr_image_to_text(region_img)
        
        if text:
            log(f"Raw OCR text for {label}: {text}")
            cleaned = _digits_from_text(text)
            
            if cleaned:
                value = int(cleaned)
                log(f"{label} extracted: {value:,}")
                return value
            log(f"No digits found in {label}")
            return None
        log(f"No {label} found in region")
        return None
    except Exception as e:
        log(f"Error extracting {label}: {e}")
        return None


def find_text_in_region(
    search_text: str,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    confidence: float = 0.75,
    screenshot: Optional[Image.Image] = None,
    find_lowest: bool = False,
) -> Optional[Tuple[int, int]]:
    """
    Search for text in a screen region using OCR and return center coordinates of the text.
    Returns (x, y) center of the text bounding box if found, None otherwise.
    confidence parameter is used for filtering low-confidence OCR results.
    If find_lowest=True, returns the match with the greatest y (lowest on screen).
    """
    if not HAS_PYTESSERACT:
        log(f"WARNING: pytesseract not installed, skipping text search for '{search_text}'")
        return None
    
    try:
        region_img = _get_region_image(x1, y1, x2, y2, screenshot=screenshot)
        data = _ocr_image_to_data(region_img)
        
        matches = []
        # Search for the target text
        for i, text in enumerate(data['text']):
            if search_text.lower() in text.lower():
                # Get confidence of this OCR result
                conf = int(data['conf'][i])

                if conf >= (confidence * 100):  # Convert 0-1 confidence to 0-100 scale
                    # Get bounding box
                    x = data['left'][i]
                    y = data['top'][i]
                    w = data['width'][i]
                    h = data['height'][i]

                    # Calculate center coordinates in screen space
                    center_x = x1 + x + w // 2
                    center_y = y1 + y + h // 2
                    matches.append((center_x, center_y, conf))

        if matches:
            if find_lowest:
                center_x, center_y, conf = max(matches, key=lambda m: m[1])
            else:
                center_x, center_y, conf = matches[0]
            log(f"Found '{search_text}' at ({center_x}, {center_y}) with confidence {conf}%")
            return (center_x, center_y)
        
        log(f"Text '{search_text}' not found in region with confidence >= {confidence:.2f}")
        return None
    
    except Exception as e:
        log(f"Error searching for text '{search_text}': {e}")
        return None


def find_all_text_in_region(
    search_text: str,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    confidence: float = 0.75,
    screenshot: Optional[Image.Image] = None,
) -> List[Tuple[int, int]]:
    """
    Search for all occurrences of text in a screen region using OCR.
    Returns a list of (x, y) center coordinates for every match found.
    """
    if not HAS_PYTESSERACT:
        log(f"WARNING: pytesseract not installed, skipping text search for '{search_text}'")
        return []

    try:
        region_img = _get_region_image(x1, y1, x2, y2, screenshot=screenshot)
        data = _ocr_image_to_data(region_img)

        results = []
        for i, text in enumerate(data['text']):
            if search_text.lower() in text.lower():
                conf = int(data['conf'][i])
                if conf >= (confidence * 100):
                    x = data['left'][i]
                    y = data['top'][i]
                    w = data['width'][i]
                    h = data['height'][i]
                    center_x = x1 + x + w // 2
                    center_y = y1 + y + h // 2
                    results.append((center_x, center_y))

        log(f"Found {len(results)} occurrence(s) of '{search_text}' in region")
        return results

    except Exception as e:
        log(f"Error searching for all '{search_text}': {e}")
        return []


# ================================
# PHASE 4 HELPER FUNCTIONS
# ================================

def pixel_is_close(x: int, y: int, target_rgb: Tuple[int, int, int], tol: int, screenshot_np: Optional[np.ndarray] = None) -> bool:
    """
    Check if pixel at (x, y) matches target_rgb within Euclidean distance tolerance.
    Takes fresh screenshot, samples pixel color, computes distance, returns True if <= tol.
    Logs sampled color and distance for debugging.
    """
    try:
        if screenshot_np is None:
            screenshot = pyautogui.screenshot()
            screenshot_np = np.array(screenshot)
        
        # Extract pixel color at (x, y). numpy uses [row, col] = [y, x]
        pixel_color = screenshot_np[y, x]
        
        # Compute Euclidean distance
        distance = np.sqrt(np.sum((pixel_color.astype(int) - np.array(target_rgb, dtype=int)) ** 2))
        
        log(f"  Pixel at ({x}, {y}): RGB{tuple(pixel_color)}, distance to target {target_rgb}: {distance:.2f}")
        
        return distance <= tol
    except Exception as e:
        log(f"Error checking pixel at ({x}, {y}): {e}")
        return False


def click_text_in_box_and_wait(
    box: Tuple[int, int, int, int],
    text: str,
    max_attempts: int,
    template_name: Optional[str] = None,
    find_rightmost: bool = False,
    find_leftmost: bool = False,
) -> Optional[Tuple[int, int]]:
    """
    Wrapper around find_text_in_region that searches for text in a box with retries.
    Special handling for buttons using template matching.
    box is (x1, y1, x2, y2). Returns center coordinates if found, None otherwise.
    Logs each attempt and result.
    
    Args:
        box: Search region (x1, y1, x2, y2)
        text: Text to search for or button type
        max_attempts: Number of retry attempts
        template_name: Optional template filename to use instead of OCR. If not provided,
                      will auto-detect based on text type.
        find_rightmost: If True and using template matching, finds all matches and returns
                   the one with highest x coordinate (rightmost)
        find_leftmost: If True and using template matching, finds all matches and returns
                  the one with lowest x coordinate (leftmost)
    """
    x1, y1, x2, y2 = box
    
    template_map = {
        "more": "more_button.png",
        "add": "add_wall_button.png",
        "remove": "remove_wall_button.png",
    }
    if text.lower() == "upgrade" and template_name:
        template_map["upgrade"] = template_name

    template_key = text.lower()
    if template_key in template_map:
        template_to_find = template_map[template_key]
        log(f"  Searching for '{text}' using template matching ({template_to_find})...")
        for attempt in range(1, max_attempts + 1):
            coords = None
            if find_rightmost or find_leftmost:
                pick = "rightmost" if find_rightmost else "leftmost"
                coords, raw_count, distinct_count = find_template_with_count(
                    template_to_find,
                    confidence=0.75,
                    pick=pick,
                )
                if coords:
                    log(f"  '{text}' buttons found: {distinct_count} (raw matches: {raw_count})")
            else:
                coords = find_template(
                    template_to_find,
                    confidence=0.75,
                    find_rightmost=find_rightmost,
                    find_leftmost=find_leftmost,
                )

            if coords:
                log(f"  '{text}' template found at {coords}")
                return coords
            if attempt < max_attempts:
                time.sleep(0.2)
        log(f"  '{text}' template not found in {max_attempts} attempts")
        return None
    
    # Original OCR-based search for other text
    confidence = 0.75
    
    for attempt in range(1, max_attempts + 1):
        log(f"  Searching for '{text}' in box ({x1},{y1})-({x2},{y2}) (attempt {attempt}/{max_attempts}, conf={confidence})")
        coords = find_text_in_region(text, x1, y1, x2, y2, confidence=confidence)
        
        if coords:
            return coords
        
        if attempt < max_attempts:
            time.sleep(0.2)
    
    log(f"  '{text}' not found in box after {max_attempts} attempts")
    return None


# ================================
# SPACE KEY LISTENER
# ================================


 
class SpaceListener:
    """Listens for Space key press to pause/resume the script."""
    
    def __init__(self, session=None):
        self.handler = None
        self._session = session
    
    def start(self):
        """Start listening for Space key."""
        session = self._session
        if not HAS_KEYBOARD:
            log("WARNING: 'keyboard' module not installed. Space key listener disabled.")
            log("Install with: pip install keyboard")
            return
        if session is None:
            log("WARNING: SpaceListener has no session reference; pausing disabled.")
            return
        
        def on_space(_):
            session.pause_requested = not session.pause_requested
            if session.pause_requested:
                log("\n" + "="*60)
                log("PAUSED - Press SPACE to resume")
                log("="*60)
            else:
                log("\n" + "="*60)
                log("RESUMED")
                log("="*60)
        
        self.handler = keyboard.on_press_key("space", on_space, suppress=False)
        log("Space key listener started. Press SPACE to pause/resume at any time.")
    
    def stop(self):
        """Stop listening for Space key."""
        if HAS_KEYBOARD and self.handler:
            try:
                keyboard.unhook(self.handler)
            except Exception:
                pass






def random_delay() -> None:
    """Sleep for a random duration between min and max delay."""
    delay = random.uniform(CONFIG["min_delay"], CONFIG["max_delay"])
    time.sleep(delay)


def add_jitter(x: int, y: int) -> Tuple[int, int]:
    """Add random pixel offset to coordinates."""
    jitter = CONFIG["click_randomness_px"]
    x_offset = random.randint(-jitter, jitter)
    y_offset = random.randint(-jitter, jitter)
    return (x + x_offset, y + y_offset)


def is_resource_full(pixel_coords: List[Tuple[int, int]], color_tolerance: int = 10) -> bool:
    """Check if a resource bar looks full by comparing multiple pixel colors."""
    try:
        screenshot = pyautogui.screenshot()
        screenshot_np = np.array(screenshot)

        colors = []
        for x, y in pixel_coords:
            pixel_color = screenshot_np[y, x]  # numpy is [row, col] = [y, x]
            colors.append(pixel_color)
            log(f"  Pixel at ({x}, {y}): RGB{tuple(pixel_color)}")

        reference_color = colors[0]
        for color in colors[1:]:
            diff = np.sqrt(np.sum((reference_color.astype(int) - color.astype(int)) ** 2))
            log(f"  Color diff: {diff:.2f}")
            if diff > color_tolerance:
                log(f"  Colors differ (>{color_tolerance}), not full")
                return False

        log("  All pixels similar - resource appears FULL")
        return True
    except Exception as e:
        log(f"Error checking resource fullness: {e}")
        return False


def is_pixel_near_color(
    x: int, y: int, target: Tuple[int, int, int], tolerance: int = 30,
    screenshot_np: Optional[np.ndarray] = None,
) -> bool:
    """Return True if the pixel at (x, y) is within `tolerance` of `target` RGB."""
    try:
        if screenshot_np is None:
            screenshot_np = np.array(pyautogui.screenshot())
        pixel = screenshot_np[y, x].astype(int)
        diff = np.sqrt(np.sum((pixel[:3] - np.array(target, dtype=int)) ** 2))
        log(f"  Pixel at ({x}, {y}): RGB{tuple(pixel[:3])}  target={target}  diff={diff:.2f}")
        return diff <= tolerance
    except Exception as e:
        log(f"Error in is_pixel_near_color: {e}")
        return False


def check_gold_full() -> bool:
    """Check if gold bar is full by testing the furthest-left pixel against the full-bar colour."""
    # Backup (old multi-point similarity check):
    # gold_pixels = [(1605, 67), (1823, 67), (1763, 67), (1732, 67)]
    # return is_resource_full(gold_pixels, color_tolerance=40)
    gold_left_x, gold_left_y = 1605, 67
    gold_full_colour = (np.int64(231), np.int64(192), np.int64(13))
    return is_pixel_near_color(gold_left_x, gold_left_y, gold_full_colour, tolerance=40)


def check_elixir_full() -> bool:
    """Check if elixir bar is full by testing the furthest-left pixel against the full-bar colour."""
    # Backup (old multi-point similarity check):
    # elixir_pixels = [(1605, 152), (1823, 152), (1763, 152), (1732, 152)]
    # return is_resource_full(elixir_pixels, color_tolerance=40)
    elixir_left_x, elixir_left_y = 1605, 152
    elixir_full_colour = (np.int64(192), np.int64(39), np.int64(192))
    return is_pixel_near_color(elixir_left_x, elixir_left_y, elixir_full_colour, tolerance=40)


def _attempt_gem_speed_up(context: str = "") -> None:
    """After confirming an upgrade, search the bottom of the screen for gem_upgrade.png.
    If found, click it then click gem_upgrade_confirm.png to speed up the upgrade with gems.
    Does nothing if gem_upgrades is disabled in CONFIG.
    """
    if not CONFIG.get("gem_upgrades", False):
        return
    log(f"Gem upgrade: Checking for gem_upgrade.png ({context})")
    screen_w, screen_h = pyautogui.size()
    gem_coords = find_template(
        "gem_upgrade.png",
        search_box=(0, int(screen_h * 0.6), screen_w, screen_h),
        confidence=0.8,
    )
    if not gem_coords:
        log("Gem upgrade: gem_upgrade.png not found - skipping")
        return
    log(f"Gem upgrade: Found at {gem_coords}, clicking...")
    click_with_jitter(*gem_coords)
    time.sleep(0.5)
    confirm_coords = find_template("gem_upgrade_confirm.png", confidence=0.8)
    if confirm_coords:
        log(f"Gem upgrade: Confirming at {confirm_coords}")
        click_with_jitter(*confirm_coords)
        time.sleep(0.5)
    else:
        log("Gem upgrade: gem_upgrade_confirm.png not found - gem speed-up not confirmed")


def pop_gem_upgrades_disabled() -> str:
    """Return the account name if gem upgrades were just disabled (no_gems detected), else ''.
    Resets the flag. Call from workers after each battle to persist the change to JSON.
    """
    global _gem_upgrades_disabled_account
    acct = _gem_upgrades_disabled_account
    _gem_upgrades_disabled_account = ""
    return acct


def find_template(
    template_name: str,
    confidence: float = None,
    search_region: bool = False,
    search_box: Optional[Tuple[int, int, int, int]] = None,
    find_rightmost: bool = False,
    find_leftmost: bool = False,
    screenshot: Optional[Image.Image] = None,
) -> Optional[Tuple[int, int]]:
    """
    Search for template image on screen using OpenCV template matching.
    Returns (x, y) center coordinates if found, None otherwise.
    Delegates to the shared vision module.
    """
    if confidence is None:
        confidence = CONFIG["confidence_threshold"]

    # Resolve template path
    script_dir = Path(__file__).parent
    if CONFIG["image_folder"] == ".":
        template_path = script_dir / template_name
    else:
        template_path = Path(CONFIG["image_folder"]) / template_name

    if not template_path.exists():
        log(f"ERROR: Template not found: {template_path}")
        return None

    # Determine region (x1, y1, x2, y2) for vision module
    region = None
    if search_box is not None:
        region = search_box
    elif search_region:
        region = CONFIG["search_region"]

    # Determine find mode
    if find_rightmost:
        find_mode = "rightmost"
    elif find_leftmost:
        find_mode = "leftmost"
    else:
        find_mode = "best"

    coords, max_val = _vision.find_template(
        template_path=template_path,
        threshold=confidence,
        screenshot=screenshot,
        region=region,
        find_mode=find_mode,
    )

    # Preserve original logging behaviour
    log(f"  Template match confidence: {max_val:.3f} (threshold: {confidence:.3f})")
    if coords is not None:
        if find_mode in ("rightmost", "leftmost"):
            log(f"  Found match(es), selecting {find_mode} at ({coords[0]}, {coords[1]})")
        else:
            log(f"  Match found at ({coords[0]}, {coords[1]})")
    elif find_mode in ("rightmost", "leftmost"):
        log(f"  No matches found above threshold {confidence:.3f}")

    return coords


def find_rightmost_template_with_count(template_name: str, confidence: float = None, search_region: bool = False) -> Tuple[Optional[Tuple[int, int]], int]:
    """
    Find all matches above threshold and return the rightmost match plus count of distinct buttons.
    Returns (coords, distinct_button_count). coords is None if no matches.
    Delegates to the shared vision module.
    """
    if confidence is None:
        confidence = CONFIG["confidence_threshold"]

    script_dir = Path(__file__).parent
    if CONFIG["image_folder"] == ".":
        template_path = script_dir / template_name
    else:
        template_path = Path(CONFIG["image_folder"]) / template_name

    if not template_path.exists():
        log(f"ERROR: Template not found: {template_path}")
        return None, 0

    region = CONFIG["search_region"] if search_region else None

    coords, raw_count, cluster_count = _vision.find_template_with_clusters(
        template_path=template_path,
        threshold=confidence,
        region=region,
        pick="rightmost",
    )

    if coords is None:
        log(f"  No matches found above threshold {confidence:.3f}")
    else:
        log(f"  Found {raw_count} match(es) in {cluster_count} distinct cluster(s), selecting rightmost at ({coords[0]}, {coords[1]})")

    return coords, cluster_count


def find_template_with_count(
    template_name: str,
    confidence: float = None,
    search_region: bool = False,
    pick: str = "rightmost",
) -> Tuple[Optional[Tuple[int, int]], int, int]:
    """
    Find all matches above threshold and return the chosen match plus counts.
    Returns (coords, raw_match_count, distinct_button_count). coords is None if no matches.
    Delegates to the shared vision module.
    """
    if confidence is None:
        confidence = CONFIG["confidence_threshold"]

    script_dir = Path(__file__).parent
    if CONFIG["image_folder"] == ".":
        template_path = script_dir / template_name
    else:
        template_path = Path(CONFIG["image_folder"]) / template_name

    if not template_path.exists():
        log(f"ERROR: Template not found: {template_path}")
        return None, 0, 0

    region = CONFIG["search_region"] if search_region else None

    coords, raw_count, cluster_count = _vision.find_template_with_clusters(
        template_path=template_path,
        threshold=confidence,
        region=region,
        pick=pick,
    )

    if coords is None:
        log(f"  No matches found above threshold {confidence:.3f}")
    else:
        log(
            f"  Found {raw_count} match(es) in {cluster_count} distinct cluster(s), "
            f"selecting {pick} at ({coords[0]}, {coords[1]})"
        )

    return coords, raw_count, cluster_count


def search_and_click(template_name: str, description: str = None, max_attempts: int = None, use_fallback: bool = True) -> bool:
    """
    Search for template and click it if found.
    Retries up to max_attempts times (default from CONFIG).
    If use_fallback=False, does not try lower confidence thresholds.
    Returns True if found and clicked, False otherwise.
    """
    if description is None:
        description = template_name
    
    if max_attempts is None:
        max_attempts = CONFIG["max_search_attempts"]
    
    log(f"Searching for {description}...")
    
    # Determine how to pick the find button when multiple are visible
    find_rightmost = False
    find_leftmost = False
    if template_name == CONFIG["find_button"]:
        if CONFIG.get("do_ranked", True):
            find_rightmost = True
        else:
            find_leftmost = True
    
    # Try with configured confidence first
    for attempt in range(1, max_attempts + 1):
        coords = None
        match_count = 0
        if find_rightmost:
            coords, match_count = find_rightmost_template_with_count(template_name)
        else:
            coords = find_template(template_name, find_leftmost=find_leftmost)
        
        if coords:
            if find_rightmost:
                if match_count > 1:
                    CONFIG["event_active_for_battle"] = False
                    log("Multiple find buttons detected; disabling event troops for this battle")
                else:
                    CONFIG["event_active_for_battle"] = CONFIG.get("event_active", False)
            elif template_name == CONFIG["find_button"]:
                CONFIG["event_active_for_battle"] = CONFIG.get("event_active", False)
            # Add random jitter and click with smooth mouse movement
            click_x, click_y = add_jitter(*coords)
            log(f"Found {description} at ({coords[0]}, {coords[1]}), clicking at ({click_x}, {click_y})")
            click_with_jitter(*coords)
            random_delay()
            return True
        
        if attempt < max_attempts:
            log(f"  Attempt {attempt}/{max_attempts} - not found, retrying...")
            time.sleep(CONFIG["wait_between_attempts"])
    
    # If fallback disabled, just return False
    if not use_fallback:
        log(f"FAILED: Could not find {description} after {max_attempts} attempts")
        return False
    
    # If still not found, try with progressively lower confidence thresholds
    log(f"Trying with lower confidence thresholds...")
    for lower_conf in [0.5, 0.4, 0.3]:
        log(f"  Attempting with confidence {lower_conf}...")
        coords = None
        match_count = 0
        if find_rightmost:
            coords, match_count = find_rightmost_template_with_count(template_name, confidence=lower_conf)
        else:
            coords = find_template(template_name, confidence=lower_conf, find_leftmost=find_leftmost)
        if coords:
            if find_rightmost:
                if match_count > 1:
                    CONFIG["event_active_for_battle"] = False
                    log("Multiple find buttons detected; disabling event troops for this battle")
                else:
                    CONFIG["event_active_for_battle"] = CONFIG.get("event_active", False)
            elif template_name == CONFIG["find_button"]:
                CONFIG["event_active_for_battle"] = CONFIG.get("event_active", False)
            click_x, click_y = add_jitter(*coords)
            log(f"Found {description} with lower confidence at ({coords[0]}, {coords[1]}), clicking at ({click_x}, {click_y})")
            click_with_jitter(*coords)
            random_delay()
            return True
        time.sleep(0.2)
    
    log(f"FAILED: Could not find {description} even with low confidence thresholds")
    return False


def _get_image_folder_path() -> Path:
    """Return the configured image folder path."""
    script_dir = Path(__file__).parent
    if CONFIG.get("image_folder") == ".":
        return script_dir
    return Path(CONFIG["image_folder"])


def _discover_clan_games_challenge_templates() -> List[str]:
    """Return sorted challenge template filenames matching clan_games_challenge_*.png."""
    prefix = CONFIG.get("clan_games_challenge_prefix", "clan_games_challenge_")
    image_folder = _get_image_folder_path()
    pattern = f"{prefix}*.png"
    templates = sorted(path.name for path in image_folder.glob(pattern) if path.is_file())
    return templates




def click_with_jitter(x: int, y: int) -> None:
    """Click coordinates with random jitter and smooth mouse movement to target."""
    click_x, click_y = add_jitter(x, y)
    
    # Move mouse smoothly to the target position (over 0.075-0.15 seconds)
    move_duration = random.uniform(0.075, 0.15)
    pyautogui.moveTo(click_x, click_y, duration=move_duration)
    
    # Small delay before clicking
    time.sleep(random.uniform(0.065, 0.13))
    pyautogui.click()


def click_deploy(x: int, y: int) -> None:
    """Fast deployment click — teleports cursor and clicks with no movement animation.
    Use only for rapid mass troop placement where human-like movement is not needed."""
    click_x, click_y = add_jitter(x, y)
    pyautogui.click(click_x, click_y)


def click_smooth(x: int, y: int) -> None:
    """Click coordinates with smooth mouse movement (no jitter)."""
    # Move mouse smoothly to the target position
    move_duration = random.uniform(0.075, 0.15)
    pyautogui.moveTo(x, y, duration=move_duration)
    
    # Small delay before clicking
    time.sleep(random.uniform(0.065, 0.13))
    pyautogui.click()
    

def press_key_with_click(key: str, click_coord: Tuple[int, int]) -> None:
    """Press and hold a key while clicking a coordinate (for ability activation)."""
    click_x, click_y = add_jitter(*click_coord)
    
    # Hold down key, click coordinate, then release key
    pyautogui.keyDown(key)
    time.sleep(0.1)  # Hold key briefly
    pyautogui.click(click_x, click_y)
    time.sleep(0.1)  # Click delay
    pyautogui.keyUp(key)
    
    log(f"Pressed '{key.upper()}' + clicked at ({click_x}, {click_y})")






# ================================
# PHASE IMPLEMENTATIONS
# ================================















# ================================
# MAIN LOOP
# ================================





# ================================
# HOME BATTLE SESSION
# ================================

class HomeBattleSession:
    """Encapsulates all mutable session state for Home Village automation.

    Instance attributes replace the former module-level globals
    ``stop_requested``, ``pause_requested``, ``current_account_name``,
    ``walls_upgraded_this_battle``, ``LOOT_TRACKER``, and ``space_listener``.

    Phase functions (``phase1_enter_battle``, ``phase2_prepare``, etc.) are
    instance methods so they naturally access ``self.<state>`` instead of
    scattered ``global`` declarations.
    """

    def __init__(self) -> None:
        self.stop_requested: bool = False
        self.pause_requested: bool = False
        self.current_account_name: Optional[str] = None
        self.walls_upgraded_this_battle: int = 0
        self.loot_tracker: "AutoLootTracker" = AutoLootTracker()
        self.space_listener: "SpaceListener" = SpaceListener(session=self)

    def ensure_approved_account(self, max_attempts: int = 100) -> bool:
        for attempt in range(1, max_attempts + 1):
            name = read_account_name()
            matched = _match_approved_account(name) if name else None
            if matched:
                self.current_account_name = matched
                self.stop_requested = False  # Clear any stop flag set by a previous failed recovery
                log(f"Approved account detected: {name}" + (f" (matched as '{matched}')" if matched != name.lower() else ""))
                return True
            log(f"Account name attempt {attempt}/{max_attempts} failed (got '{name}')")

            # On retry, randomly scroll up or down
            if attempt < max_attempts:
                scroll_random(WHEEL_DELTA * 3)
                time.sleep(0.5)

        log("Could not verify approved account after 100 attempts - checking for known errors...")

        # Check for basic error buttons (try_again, reload_game, etc.)
        if check_for_error_button():
            log("Error button found and clicked - retrying account check after recovery...")
            time.sleep(3)
        else:
            # No known error popup - hard reset the game
            log("No known error popup found - performing hard game restart...")
            pyautogui.hotkey('alt', 'f4')  # Close game window
            # Backup (old click-to-close): pyautogui.click(1859, 16)
            time.sleep(5)
            pyautogui.doubleClick(340, 160, interval=0.2)  # Relaunch game
            # Backup (old post-launch click): pyautogui.click(1517, 148)
            time.sleep(20)
            log("Hard game restart complete - retrying account check...")

        # Retry account check with a reduced set of attempts after recovery
        for attempt in range(1, 21):
            name = read_account_name()
            matched = _match_approved_account(name) if name else None
            if matched:
                self.current_account_name = matched
                self.stop_requested = False  # Clear any stop flag set by a previous failed recovery
                log(f"Approved account detected after recovery: {name}" + (f" (matched as '{matched}')" if matched != name.lower() else ""))
                return True
            log(f"Post-recovery attempt {attempt}/20 failed (got '{name}')")
            if attempt < 20:
                scroll_random(WHEEL_DELTA * 3)
                time.sleep(0.5)

        log("Could not verify approved account after recovery. Stopping script.")
        self.stop_requested = True
        return False

    def run_clan_games_flow(self) -> bool:
        """
        Run Clan Games routine before normal Phase 1 attack entry.

        Returns:
            True when routine completed or skipped safely.
            False on failure (caller should abort this cycle).
        """
        if self.stop_requested:
            return False

        def clan_games_click(x: int, y: int, action_desc: str = "") -> None:
            click_with_jitter(x, y)
            random_delay()
            if action_desc:
                log(f"Clan Games: Waiting 1 second after {action_desc}")
            else:
                log("Clan Games: Waiting 1 second after click")
            time.sleep(1.0)

        log("Clan Games: Starting pre-attack routine")

        # Step 1: Drag from (733,291) to (1177,958) twice
        for drag_num in range(1, 3):
            if self.stop_requested:
                return False
            log(f"Clan Games: Dragging map ({drag_num}/2) from (733,291) to (1177,958)")
            pyautogui.moveTo(733, 291, duration=0.1)
            pyautogui.dragTo(1177, 958, duration=0.4, button="left")
            time.sleep(0.2)

        # Step 2: Find clan games stand with retries
        stand_template = CONFIG.get("clan_games_stand_template", "clan_games_stand.png")
        stand_confidence = float(CONFIG.get("clan_games_stand_confidence", CONFIG["confidence_threshold"]))
        stand_retry_attempts = int(CONFIG.get("clan_games_stand_retry_attempts", 10))
        stand_retry_delay = float(CONFIG.get("clan_games_stand_retry_delay", 1.0))

        stand_coords = None
        for attempt in range(1, stand_retry_attempts + 1):
            if self.stop_requested:
                return False
            log(f"Clan Games: Searching for stand '{stand_template}' (attempt {attempt}/{stand_retry_attempts})")
            stand_coords = find_template(stand_template, confidence=stand_confidence)
            if stand_coords:
                log(f"Clan Games: Found stand at {stand_coords}, clicking")
                clan_games_click(*stand_coords, action_desc="stand click")
                log("Clan Games: Waiting 5 seconds for challenges screen to load")
                time.sleep(5.0)
                break
            if attempt < stand_retry_attempts:
                time.sleep(stand_retry_delay)

        if not stand_coords:
            log("Clan Games: Stand not found after retries - aborting this battle cycle")
            return False

        def is_pixel_close_to_yellow(
            pixel: Tuple[int, int],
            target_yellow: Tuple[int, int, int] = (245, 215, 80),
            tolerance: float = 90.0,
            label: str = "yellow-check",
        ) -> bool:
            x, y = pixel
            try:
                shot = pyautogui.screenshot(region=(x, y, 1, 1))
                rgb = shot.getpixel((0, 0))
                if isinstance(rgb, tuple) and len(rgb) >= 3:
                    r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
                else:
                    log(f"Clan Games: Unexpected pixel format at {pixel}: {rgb}")
                    return False

                tr, tg, tb = target_yellow
                distance = ((r - tr) ** 2 + (g - tg) ** 2 + (b - tb) ** 2) ** 0.5
                log(f"Clan Games: {label} pixel RGB=({r},{g},{b}), yellow distance={distance:.1f}")
                return distance <= tolerance
            except Exception as exc:
                log(f"Clan Games: Failed {label} pixel check at {pixel}: {exc}")
                return False

        # Step 2.4: Early active-screen check before running any clan-games checks
        if is_pixel_close_to_yellow((513, 978), label="entry-active"):
            log("Clan Games: Entry active indicator detected at (513,978) - exiting menu and continuing")
            clan_games_click(1704, 79, action_desc="menu exit click (entry active)")
            return True

        # Step 2.5: If cooldown is active, exit menu and continue normal Phase 1
        cooldown_template = CONFIG.get("clan_games_cooldown_template", "clan_games_cooldown.png")
        log(f"Clan Games: Checking for cooldown indicator '{cooldown_template}'")
        cooldown_coords = find_template(cooldown_template)
        if cooldown_coords:
            log(f"Clan Games: Cooldown detected at {cooldown_coords} - exiting menu and continuing")
            clan_games_click(1704, 79, action_desc="menu exit click (cooldown)")
            return True

        # Step 2.6: If active challenge indicator pixel is yellow, exit menu and continue
        if is_pixel_close_to_yellow((890, 459), label="active-challenge"):
            log("Clan Games: Active challenge indicator detected at (890,459) - exiting menu and continuing")
            clan_games_click(1704, 79, action_desc="menu exit click (active challenge)")
            return True

        # Step 3: Search challenge list region for any clan_games_challenge_*.png
        challenge_region = CONFIG.get("clan_games_challenge_region", (700, 200, 1700, 800))
        challenge_confidence = float(CONFIG.get("clan_games_challenge_confidence", CONFIG["confidence_threshold"]))
        challenge_templates = _discover_clan_games_challenge_templates()
        if not challenge_templates:
            log("Clan Games: No challenge templates found with configured prefix - aborting this battle cycle")
            return False

        def find_all_template_centers_in_box(
            template_name: str,
            confidence: float,
            search_box: Tuple[int, int, int, int],
        ) -> List[Tuple[int, int]]:
            """Return all distinct template match centers above threshold in a search box.
            Delegates to the shared vision module."""
            script_dir = Path(__file__).parent
            if CONFIG["image_folder"] == ".":
                template_path = script_dir / template_name
            else:
                template_path = Path(CONFIG["image_folder"]) / template_name

            if not template_path.exists():
                log(f"ERROR: Template not found: {template_path}")
                return []

            return _vision.find_all_templates(
                template_path=template_path,
                threshold=confidence,
                region=search_box,
            )

        def find_visible_challenges() -> List[Tuple[str, Tuple[int, int]]]:
            visible = []
            for template_name in challenge_templates:
                centers = find_all_template_centers_in_box(
                    template_name,
                    challenge_confidence,
                    challenge_region,
                )
                for center in centers:
                    visible.append((template_name, center))
            return visible

        visible_challenges = find_visible_challenges()

        # If none found, scroll and check once more
        if not visible_challenges:
            log("Clan Games: No matching challenge found, scrolling down twice and retrying")
            pyautogui.moveTo(1177, 513, duration=0.1)
            scroll_api(WHEEL_DELTA * 3, "down")
            time.sleep(0.2)
            scroll_api(WHEEL_DELTA * 3, "down")
            time.sleep(0.4)
            visible_challenges = find_visible_challenges()

        start_template = CONFIG.get("clan_games_start_template", "clan_games_start.png")

        # Fallback path when no challenge template was found
        if not visible_challenges:
            log("Clan Games: No configured challenge template found after retry, running fallback start sequence")
            clan_games_click(797, 280, action_desc="fallback challenge area click")

            start_coords = find_template(start_template)
            if not start_coords:
                log("Clan Games: Could not find clan_games_start.png in fallback path - aborting this battle cycle")
                return False

            log(f"Clan Games: Clicking start at {start_coords}")
            clan_games_click(*start_coords, action_desc="start button click")
            time.sleep(2.0)

            log("Clan Games: Clicking start position again")
            clan_games_click(*start_coords, action_desc="second start click")

            log("Clan Games: Clicking confirmation at (1120,667)")
            clan_games_click(1120, 667, action_desc="confirmation click")

            log("Clan Games: Exiting menu at (1704,79)")
            clan_games_click(1704, 79, action_desc="menu exit click")
            return True

        # Normal path when a configured challenge was found
        selected_template, selected_coords = random.choice(visible_challenges)
        log(f"Clan Games: Found {len(visible_challenges)} challenge(s), selecting '{selected_template}' at {selected_coords}")
        clan_games_click(*selected_coords, action_desc="challenge selection click")

        start_coords = find_template(start_template)
        if not start_coords:
            log("Clan Games: Challenge selected but start button not found (likely already active) - exiting menu and continuing")
            clan_games_click(1704, 79, action_desc="challenges screen exit click")
            return True

        log(f"Clan Games: Clicking start at {start_coords}")
        clan_games_click(*start_coords, action_desc="start button click")

        log("Clan Games: Exiting challenges screen at (1704,79)")
        clan_games_click(1704, 79, action_desc="challenges screen exit click")

        log("Clan Games: Routine complete")
        return True

    def perform_wall_upgrade_flow(self, resource_type: str) -> bool:
        """
        Implements the complete Phase 4 upgrade flow for a single resource (gold or elixir).

        Flow:
        0. Click upgrade menu and search for "wall", click it (with scrolling if needed)
        1. Search "More" box for "More" text (single attempt; if not found, skip Phase 4)
        2. Click "More"
        3. Re-search "More" box:
           - If CASE A (still present): search upgrade box for "Upgrade", click it, find confirm_singular_template
           - If CASE B (not present): search add_box for "Add", enter Add loop checking pixels, on trigger handle Remove/Upgrade/okay

        Args:
            resource_type: "gold" or "elixir"

        Returns:
            True if completed normally or skipped safely (continue to next battle)
            False if unrecoverable failure (abort Phase 4, return to Phase 1)
        """
        if self.stop_requested:
            return False

        phase4_cfg = CONFIG["phase4"]
        log(f"\nPhase4: Starting upgrade flow for {resource_type.upper()}")

        # ========== STEP 0: Open upgrade menu and find "wall" ==========
        log("Phase4: Opening upgrade menu at (907, 44)...")
        click_with_jitter(907, 44)
        time.sleep(0.1)

        # Search for "wall" text with scroll retry
        log("Phase4: Searching for 'wall' in upgrade list...")
        wall_coords = None
        max_scroll_attempts = 20
        scroll_attempt = 0

        while scroll_attempt < max_scroll_attempts and not self.stop_requested:
            log(f"  Searching for 'wall' (scroll attempt {scroll_attempt + 1}/{max_scroll_attempts})")
            wall_coords = find_text_in_region("wall", 744, 134, 1210, 684, confidence=0.75, find_lowest=True)

            if wall_coords:
                log(f"Phase4: Found 'wall' at {wall_coords}")
                break

            # Not found, scroll down by clicking and dragging
            if scroll_attempt < max_scroll_attempts - 1:
                log("  'wall' not found, scrolling down...")
                pyautogui.moveTo(866, 458, duration=0.1)
                pyautogui.drag(0, -200, duration=0.3)
                time.sleep(0.4)

            scroll_attempt += 1

        if not wall_coords:
            log(f"Phase4: 'wall' not found after {max_scroll_attempts} scroll attempts - ABORTING Phase 4")
            return False  # Fatal error - can't find wall to upgrade

        # Click the wall to select it
        log(f"Phase4: Clicking 'wall' at {wall_coords}...")
        click_with_jitter(*wall_coords)
        time.sleep(0.5)

        # Increment wall counter for first wall selection
        self.walls_upgraded_this_battle += 1
        log(f"Phase4: Wall selected - count: {self.walls_upgraded_this_battle}")

        # ========== STEP 1: Search "More" box (1 attempt only) ==========
        log(f"Phase4: Searching for 'More' in more_box...")
        more_coords = click_text_in_box_and_wait(phase4_cfg["more_box"], "More", max_attempts=1)

        if not more_coords:
            log(f"Phase4: 'More' not found on first check - skipping Phase 4 for this battle")
            return True  # Safe skip - continue to next battle

        log(f"Phase4: 'More' found at {more_coords} - clicking")

        # ========== STEP 2: Click "More" ==========
        click_with_jitter(*more_coords)
        random_delay()
        time.sleep(phase4_cfg["post_click_delay"])

        # ========== STEP 3: Re-search "More" box to determine case ==========
        log(f"Phase4: Re-checking 'More' box to determine case...")
        more_still_present = click_text_in_box_and_wait(phase4_cfg["more_box"], "More", max_attempts=1)

        if more_still_present:
            # ========== CASE A: Single-wall upgrade (More still present) ==========
            log(f"Phase4: Re-check: 'More' STILL PRESENT -> SINGLE-WALL path (CASE A)")

            # Determine which upgrade box to search based on resource type
            if resource_type == "gold":
                upgrade_box = phase4_cfg["upgrade_box_gold"]
            else:  # elixir
                upgrade_box = phase4_cfg["upgrade_box_elixir"]

            # Search for "Upgrade" in the box (use singular template for single-wall case)
            log(f"Phase4: Searching for 'Upgrade' in {resource_type} upgrade box...")
            # For gold, select leftmost; for elixir, select rightmost
            find_rightmost = (resource_type == "elixir")
            find_leftmost = (resource_type == "gold")
            upgrade_coords = click_text_in_box_and_wait(
                upgrade_box,
                "Upgrade",
                max_attempts=phase4_cfg["max_retry_attempts"],
                template_name="upgrade_button_singular.png",
                find_rightmost=find_rightmost,
                find_leftmost=find_leftmost,
            )

            if not upgrade_coords:
                log(f"Phase4: 'Upgrade' not found in {resource_type} box after retries - ABORTING Phase 4 (CASE A)")
                return False  # Fatal error - abort to Phase 1

            log(f"Phase4: 'Upgrade' found at {upgrade_coords} - clicking")
            click_with_jitter(*upgrade_coords)
            random_delay()
            time.sleep(phase4_cfg["post_click_delay"])

            # Search for confirm_singular_template
            log(f"Phase4: Searching for '{phase4_cfg['confirm_singular_template']}'...")
            confirm_coords = None
            for attempt in range(1, phase4_cfg["max_retry_attempts"] + 1):
                confirm_coords = find_template(phase4_cfg["confirm_singular_template"])
                if confirm_coords:
                    log(f"Phase4: Confirm template found at {confirm_coords}")
                    break
                if attempt < phase4_cfg["max_retry_attempts"]:
                    time.sleep(0.2)

            if not confirm_coords:
                log(f"Phase4: Confirm template not found after retries - ABORTING Phase 4 (CASE A)")
                return False  # Fatal error - abort to Phase 1

            log(f"Phase4: Clicking confirm template at {confirm_coords}")
            click_with_jitter(*confirm_coords)
            random_delay()
            time.sleep(phase4_cfg["post_click_delay"])
            _attempt_gem_speed_up("Phase4 CASE A")

            log(f"Phase4: CASE A ({resource_type.upper()}) upgrade complete - returning True")
            return True

        else:
            # ========== CASE B: Add loop (More not present) ==========
            log(f"Phase4: Re-check: 'More' NOT PRESENT -> ADD-LOOP path (CASE B)")

            # Search for "Add" in add_box
            log(f"Phase4: Searching for 'Add' in add_box...")
            add_coords = click_text_in_box_and_wait(phase4_cfg["add_box"], "Add", max_attempts=phase4_cfg["max_retry_attempts"])

            if not add_coords:
                log(f"Phase4: 'Add' not found - treating as safe skip")
                return True  # Safe skip - no Add button means phase is complete

            log(f"Phase4: 'Add' found - entering Add loop (max {phase4_cfg['max_add_clicks']} clicks)")

            # Determine pixel sets to check based on resource type
            if resource_type == "gold":
                target_pixel_set = phase4_cfg["gold_pixel_set"]
            else:  # elixir
                target_pixel_set = phase4_cfg["elixir_pixel_set"]

            alternate_pixel_set = phase4_cfg["alternate_pixel_set"]
            target_color = phase4_cfg["target_red_color"]
            pixel_tol = phase4_cfg["pixel_tolerance"]

            # ========== CASE B: Add loop ==========
            pixel_trigger_found = False
            # Track which trigger sets fired this cycle
            resource_trigger = False  # True if gold/elixir set matched
            alternate_trigger = False  # True if alternate set matched

            for add_click_num in range(1, phase4_cfg["max_add_clicks"] + 1):
                log(f"Phase4: Add click #{add_click_num}/{phase4_cfg['max_add_clicks']}")

                # Click "Add"
                click_with_jitter(*add_coords)
                random_delay()
                time.sleep(phase4_cfg["add_click_delay"])

                # Increment wall counter for each Add click
                self.walls_upgraded_this_battle += 1
                log(f"Phase4: Add clicked - wall count: {self.walls_upgraded_this_battle}")

                # Check pixel triggers
                log(f"Phase4:  Checking pixel triggers...")

                screenshot_np = np.array(pyautogui.screenshot())

                # Check resource-specific pixels
                for px, py in target_pixel_set:
                    if pixel_is_close(px, py, target_color, pixel_tol, screenshot_np=screenshot_np):
                        log(f"Phase4:  PIXEL TRIGGER: {resource_type.upper()} set matched at ({px}, {py})")
                        resource_trigger = True
                        break

                # Check alternate pixels (resource-independent)
                for px, py in alternate_pixel_set:
                    if pixel_is_close(px, py, target_color, pixel_tol, screenshot_np=screenshot_np):
                        log(f"Phase4:  PIXEL TRIGGER: ALTERNATE set matched at ({px}, {py})")
                        alternate_trigger = True
                        break

                # If any trigger fired, we can proceed (but after checking both sets to allow both=True)
                if resource_trigger or alternate_trigger:
                    pixel_trigger_found = True
                    break

            if not pixel_trigger_found:
                log(f"Phase4: Add loop completed without pixel trigger - ABORTING Phase 4 (CASE B)")
                return False  # Fatal error - abort to Phase 1

            log(f"Phase4: Pixel triggers: resource={resource_trigger}, alternate={alternate_trigger}")

            # ========== HANDLE_PIXEL_TRIGGER ==========
            # Decide whether Remove is required (only if resource-specific trigger fired)
            remove_required = bool(resource_trigger)

            if remove_required:
                if resource_trigger and alternate_trigger:
                    log("Phase4: Both triggers detected -> clicking 'Remove' (resource rules)")
                else:
                    log("Phase4: Resource-specific trigger detected -> searching for 'Remove' (mandatory).")

                remove_coords = click_text_in_box_and_wait(
                    phase4_cfg["remove_box"],
                    "Remove",
                    max_attempts=phase4_cfg["max_retry_attempts"]
                )
                if not remove_coords:
                    log("Phase4: 'Remove' NOT found after retries - FATAL ERROR - ABORTING Phase 4")
                    return False
                log(f"Phase4: 'Remove' found at {remove_coords} - clicking")
                click_with_jitter(*remove_coords)
                random_delay()
                time.sleep(phase4_cfg["post_click_delay"])

                # Decrement wall counter when Remove is clicked
                self.walls_upgraded_this_battle -= 1
                log(f"Phase4: Remove clicked - wall count decreased to: {self.walls_upgraded_this_battle}")
            else:
                log("Phase4: Alternate-only trigger -> SKIPPING 'Remove' and proceeding to 'Upgrade'.")

            # Determine which upgrade box to use (use _alt variants if available)
            if resource_type == "gold":
                upgrade_box = phase4_cfg["upgrade_box_gold_alt"]
            else:  # elixir
                upgrade_box = phase4_cfg["upgrade_box_elixir_alt"]

            # Search for "Upgrade" in the appropriate box (use multiple template for add-loop case)
            log(f"Phase4: Searching for 'Upgrade' in {resource_type} upgrade box (alt)...")
            # For gold, select leftmost; for elixir, select rightmost
            find_rightmost = (resource_type == "elixir")
            find_leftmost = (resource_type == "gold")
            upgrade_coords = click_text_in_box_and_wait(
                upgrade_box,
                "Upgrade",
                max_attempts=phase4_cfg["max_retry_attempts"],
                template_name="upgrade_button_multiple.png",
                find_rightmost=find_rightmost,
                find_leftmost=find_leftmost,
            )

            if not upgrade_coords:
                log(f"Phase4: 'Upgrade' not found in {resource_type} box after retries - ABORTING Phase 4 (CASE B)")
                return False  # Fatal error

            log(f"Phase4: 'Upgrade' found at {upgrade_coords} - clicking")
            click_with_jitter(*upgrade_coords)
            random_delay()
            time.sleep(phase4_cfg["post_click_delay"])

            # Search for okay_upgrade_template
            log(f"Phase4: Searching for '{phase4_cfg['okay_upgrade_template']}'...")
            okay_coords = None
            for attempt in range(1, phase4_cfg["max_retry_attempts"] + 1):
                okay_coords = find_template(phase4_cfg["okay_upgrade_template"])
                if okay_coords:
                    log(f"Phase4: Okay upgrade template found at {okay_coords}")
                    break
                if attempt < phase4_cfg["max_retry_attempts"]:
                    time.sleep(0.2)

            if not okay_coords:
                log(f"Phase4: Okay upgrade template not found after retries - ABORTING Phase 4 (CASE B)")
                return False  # Fatal error

            log(f"Phase4: Clicking okay upgrade template at {okay_coords}")
            click_with_jitter(*okay_coords)
            random_delay()
            time.sleep(phase4_cfg["post_click_delay"])
            _attempt_gem_speed_up("Phase4 CASE B")

            log(f"Phase4: CASE B ({resource_type.upper()}) upgrade complete - returning True")
            return True

    def plan_and_perform_wall_upgrades(self) -> bool:
        """
        High-level coordinator for Phase 4 upgrades.
        Checks resource fullness and calls perform_wall_upgrade_flow for gold and elixir independently.
        Returns True if successful or skipped, False if fatal error (abort Phase 4).
        """
        if self.stop_requested:
            return False

        log("\nPhase4: Coordinator starting - checking resource fullness")

        # Before checking loot fullness, clear optional star bonus popup if present
        phase4_cfg = CONFIG.get("phase4", {})
        star_bonus_template = phase4_cfg.get("star_bonus_okay_template", "star_bonus_okay.png")
        log(f"Phase4: Checking for optional star bonus popup '{star_bonus_template}'...")
        star_bonus_coords = find_template(star_bonus_template)
        if star_bonus_coords:
            log(f"Phase4: Found star bonus okay button at {star_bonus_coords} - clicking")
            click_with_jitter(*star_bonus_coords)
            random_delay()
            time.sleep(phase4_cfg.get("post_click_delay", 0.25))
        else:
            log("Phase4: Star bonus popup not found - continuing")

        gold_full = check_gold_full()
        elixir_full = check_elixir_full()

        if not gold_full and not elixir_full:
            log(f"Phase4: Neither resource is full (gold={gold_full}, elixir={elixir_full}) - skipping Phase 4")
            return True  # Skip Phase 4, continue farming

        log(f"Phase4: Resource status - gold_full={gold_full}, elixir_full={elixir_full}")

        # Try gold upgrade if gold is full
        if gold_full:
            log("Phase4: ========== UPGRADING GOLD ==========")
            if not self.perform_wall_upgrade_flow("gold"):
                log("Phase4: Gold upgrade failed - ABORTING Phase 4")
                return False  # Fatal - abort to Phase 1
        else:
            log("Phase4: Gold not full - skipping gold upgrade")

        # Try elixir upgrade if elixir is full
        if elixir_full:
            log("Phase4: ========== UPGRADING ELIXIR ==========")
            if not self.perform_wall_upgrade_flow("elixir"):
                log("Phase4: Elixir upgrade failed - ABORTING Phase 4")
                return False  # Fatal - abort to Phase 1
        else:
            log("Phase4: Elixir not full - skipping elixir upgrade")

        log("Phase4: ========== UPGRADES COMPLETE ==========")
        return True

    def phase4_upgrade(self) -> bool:
        """
        PHASE 4: Upgrade Walls with Full Loot

        Coordinates the new Phase 4 upgrade flow which implements the exact
        More/Add/Upgrade sequence. Uses plan_and_perform_wall_upgrades() to
        handle gold and elixir upgrades with pixel-triggered detection.

        Returns True on success or safe skip, False on fatal error (abort to Phase 1).
        """
        if self.stop_requested:
            return False

        log("=" * 60)
        log("PHASE 4: UPGRADING WALLS (NEW FLOW)")
        log("=" * 60)

        result = self.plan_and_perform_wall_upgrades()

        log("=" * 60)
        if result:
            log("PHASE 4 COMPLETE")
        else:
            log("PHASE 4 FAILED - ABORTING TO PHASE 1")
        log("=" * 60)

        return result

    def upgrade_account(self) -> bool:
        """
        PHASE 5: Upgrade Storage / Place New Building / Any Other Building
        (Town Hall is intentionally skipped)

        Conditions to run:
        - BOTH gold AND elixir are full
        - A free builder is available (nobuilders.png NOT found)

        Search order (each phase uses up to max_scrolls scroll-downs):
        A) Storage  — click → upgrade_button_singular.png → confirm_storage.png → return
        B) New      — reject if 'Hut' found at same y ±5px (Builder's Hut); accepted New
                      → click → arrow_orange.png → click 100px left+down → build_confirm.png → return
        C) Other    — template-match gold_upgrade.png / elixir_upgrade.png cost icons;
                      reject rows matching PHASE_C_EXCLUDE_WORDS or buildergems;
                      pick topmost valid → upgrade_button_singular → confirm_storage.png → return

        After each successful action the bot returns to attacking (resources depleted).
        If nothing is found across all three phases, safe-skip.
        """
        if self.stop_requested:
            return False

        # Words that disqualify a building row from Phase C.
        # Add entries here to exclude additional buildings in future.
        PHASE_C_EXCLUDE_WORDS: List[str] = ["Town", "Hall", "Hut"]

        log("=" * 60)
        log("PHASE 5: UPGRADE ACCOUNT (Storage / New Building / Other)")
        log("=" * 60)

        search_x1, search_y1, search_x2, search_y2 = 771, 149, 1045, 667
        scroll_cx = (search_x1 + search_x2) // 2  # 957
        scroll_cy = (search_y1 + search_y2) // 2  # 395
        max_scrolls = 3
        max_retry = 5

        def _scroll_down_once() -> None:
            pyautogui.moveTo(scroll_cx, scroll_cy, duration=0.1)
            pyautogui.drag(0, -200, duration=0.3)
            time.sleep(0.4)

        def _scroll_up_n(n: int) -> None:
            for _ in range(n):
                pyautogui.moveTo(scroll_cx, scroll_cy, duration=0.1)
                pyautogui.drag(0, 200, duration=0.3)
                time.sleep(0.4)

        def _get_valid_matches(word: str) -> List[Tuple[int, int]]:
            """
            Find all occurrences of word in the search region.
            Check for 'Suggested' label: if found, discard any matches whose y is
            above (less than) the Suggested y — those are already-in-progress items.
            Returns the filtered list (may be empty).
            """
            all_matches = find_all_text_in_region(word, search_x1, search_y1, search_x2, search_y2, confidence=0.75)
            if not all_matches:
                return []

            suggested = find_text_in_region("Suggested", search_x1, search_y1, search_x2, search_y2, confidence=0.75)
            if suggested:
                suggested_y = suggested[1]
                valid = [(x, y) for (x, y) in all_matches if y > suggested_y]
                log(f"Phase5: 'Suggested' at y={suggested_y} — {len(valid)}/{len(all_matches)} '{word}' match(es) are below it (valid)")
            else:
                log(f"Phase5: 'Suggested' not found — all {len(all_matches)} '{word}' match(es) valid")
                valid = all_matches

            return valid

        def _search_with_scroll_down(word: str) -> Optional[Tuple[int, int]]:
            """
            Search for word with Suggested filtering and random selection,
            scrolling down up to max_scrolls times. Returns a randomly chosen
            valid coord or None.
            """
            for attempt in range(max_scrolls + 1):
                log(f"Phase5: Searching for '{word}' (attempt {attempt + 1}/{max_scrolls + 1})")
                valid = _get_valid_matches(word)
                if valid:
                    chosen = random.choice(valid)
                    log(f"Phase5: Randomly selected '{word}' at {chosen} from {len(valid)} valid option(s)")
                    return chosen
                if attempt < max_scrolls:
                    log(f"Phase5: No valid '{word}' found, scrolling down...")
                    _scroll_down_once()
            return None

        def _find_template_with_retry(name: str) -> Optional[Tuple[int, int]]:
            """Template search with max_retry attempts. Returns coords or None."""
            for attempt in range(1, max_retry + 1):
                coords = find_template(name)
                if coords:
                    return coords
                if attempt < max_retry:
                    time.sleep(0.2)
            return None

        def _do_place_new_building(item_coords: Tuple[int, int]) -> bool:
            """Click item, find arrow_orange.png, click 100px left+down, find build_confirm.png, click it."""
            log(f"Phase5: Clicking item (placement flow) at {item_coords}...")
            click_with_jitter(*item_coords)
            time.sleep(2.0)

            log("Phase5: Searching for 'arrow_orange.png'...")
            arrow_coords = _find_template_with_retry("arrow_orange.png")
            if not arrow_coords:
                log("Phase5: 'arrow_orange.png' not found - aborting placement")
                return False

            click_x = arrow_coords[0] - 100
            click_y = arrow_coords[1] + 100
            log(f"Phase5: Clicking 100px left and down from arrow at ({click_x}, {click_y})")
            click_with_jitter(click_x, click_y)
            time.sleep(0.8)

            log("Phase5: Searching for 'build_confirm.png'...")
            build_confirm_coords = _find_template_with_retry("build_confirm.png")
            if not build_confirm_coords:
                log("Phase5: 'build_confirm.png' not found - aborting placement")
                return False

            log(f"Phase5: Clicking build confirm at {build_confirm_coords}")
            click_with_jitter(*build_confirm_coords)
            time.sleep(0.5)
            _attempt_gem_speed_up("Phase5 new building")
            return True

        def _do_upgrade_confirm(item_coords: Tuple[int, int]) -> bool:
            """Click item, find upgrade button, find confirm. Returns True on success."""
            log(f"Phase5: Clicking item at {item_coords}...")
            click_with_jitter(*item_coords)
            time.sleep(0.5)

            log("Phase5: Searching for 'upgrade_button_singular.png'...")
            upgrade_coords = _find_template_with_retry("upgrade_button_singular.png")
            if not upgrade_coords:
                log("Phase5: Upgrade button not found - aborting this attempt")
                return False
            log(f"Phase5: Clicking upgrade button at {upgrade_coords}")
            click_with_jitter(*upgrade_coords)
            time.sleep(0.5)

            log("Phase5: Searching for 'confirm_storage.png'...")
            confirm_coords = _find_template_with_retry("confirm_storage.png")
            if not confirm_coords:
                log("Phase5: Confirm button not found - aborting this attempt")
                return False
            log(f"Phase5: Clicking confirm at {confirm_coords}")
            click_with_jitter(*confirm_coords)
            time.sleep(0.5)
            _attempt_gem_speed_up("Phase5 upgrade")
            return True

        # ===== Main loop: keep upgrading while conditions are met =====
        iteration = 0
        upgraded_anything = False
        nothing_found_to_upgrade = False
        while not self.stop_requested:
            iteration += 1
            log(f"Phase5: ===== ITERATION {iteration} =====")

            # Re-check conditions at the top of every iteration
            gold_full = check_gold_full()
            elixir_full = check_elixir_full()
            if not (gold_full and elixir_full):
                log(f"Phase5: Gold and elixir not both full (gold={gold_full}, elixir={elixir_full}) - exiting Phase 5")
                break

            no_builders_coords = find_template(
                "nobuilders.png",
                confidence=0.8,
                search_box=(835, 2, 1094, 129),
            )
            if no_builders_coords:
                log("Phase5: No free builder available - exiting Phase 5")
                break

            log("Phase5: Conditions met (both full, free builder) - opening upgrade menu...")
            click_with_jitter(907, 50)
            time.sleep(0.3)

            # ===== PHASE A: Storage =====
            log("Phase5: ===== PHASE A: Searching for Storage =====")
            storage_coords = _search_with_scroll_down("Storage")

            if storage_coords:
                storage_y = storage_coords[1]
                # Check if any "New" text sits on the same row as this Storage entry.
                # If so it is a new storage to be placed, not an existing one to upgrade.
                new_matches_in_region = find_all_text_in_region(
                    "New", search_x1, search_y1, search_x2, search_y2, confidence=0.75
                )
                matching_new_ys = [ny for (_, ny) in new_matches_in_region if abs(ny - storage_y) <= 15]
                is_new_storage = bool(matching_new_ys)

                if is_new_storage:
                    log(f"Phase5: 'New' found at same y as Storage (storage_y={storage_y}, new_y(s)={matching_new_ys}) - using placement flow")
                    if _do_place_new_building(storage_coords):
                        log(f"Phase5: New storage placed (iteration {iteration}) - waiting 2s then re-checking conditions")
                        upgraded_anything = True
                        time.sleep(2)
                        continue
                    log("Phase5: New storage placement failed - continuing to Phase B")
                else:
                    log(f"Phase5: No 'New' found at same y as Storage (storage_y={storage_y}, new_ys checked={[ny for (_, ny) in new_matches_in_region]}) - using upgrade flow")
                    if _do_upgrade_confirm(storage_coords):
                        log(f"Phase5: Storage upgraded (iteration {iteration}) - waiting 2s then re-checking conditions")
                        upgraded_anything = True
                        time.sleep(2)
                        continue
                    log("Phase5: Storage upgrade failed - continuing to Phase B")

            # ===== PHASE B: New building =====
            log("Phase5: ===== PHASE B: Searching for New buildings (scrolling up to reset) =====")
            _scroll_up_n(3)

            new_accepted_coords = None
            for attempt in range(max_scrolls + 1):
                log(f"Phase5: Searching for 'New' (attempt {attempt + 1}/{max_scrolls + 1})")

                new_candidates = _get_valid_matches("New")

                if new_candidates:
                    hut_matches = find_all_text_in_region("Hut", search_x1, search_y1, search_x2, search_y2, confidence=0.75)
                    hut_ys = [hy for (_, hy) in hut_matches]

                    buildergems_coords = find_template(
                        "buildergems.png",
                        search_box=(search_x1, search_y1, search_x2, search_y2),
                    )
                    buildergems_y = buildergems_coords[1] if buildergems_coords else None

                    accepted = []
                    for (nx, ny) in new_candidates:
                        if any(abs(hy - ny) <= 15 for hy in hut_ys):
                            log(f"Phase5: Rejecting 'New' at ({nx},{ny}) - 'Hut' on same y-level (Builder's Hut)")
                        elif buildergems_y is not None and abs(buildergems_y - ny) <= 15:
                            log(f"Phase5: Rejecting 'New' at ({nx},{ny}) - 'buildergems.png' on same y-level (y={buildergems_y})")
                        else:
                            accepted.append((nx, ny))

                    if accepted:
                        chosen = random.choice(accepted)
                        log(f"Phase5: Randomly selected accepted 'New' at {chosen} from {len(accepted)} non-Hut option(s)")
                        new_accepted_coords = chosen
                        break
                    else:
                        log(f"Phase5: All {len(new_candidates)} 'New' match(es) are Builder's Huts - scrolling down")
                else:
                    log("Phase5: No valid 'New' found")

                if attempt < max_scrolls:
                    _scroll_down_once()

            if new_accepted_coords:
                if _do_place_new_building(new_accepted_coords):
                    log(f"Phase5: New building placed (iteration {iteration}) - waiting 2s then re-checking conditions")
                    upgraded_anything = True
                    time.sleep(2)
                    continue
                log("Phase5: New building placement failed - exiting Phase 5")
                break

            # ===== PHASE C: Any other building (not Town Hall, not Builder's Hut) =====
            log("upgrade_account: ===== PHASE C: Searching for any upgradeable building =====")
            _scroll_up_n(3)

            img_folder = (
                Path(__file__).parent
                if CONFIG["image_folder"] == "."
                else Path(CONFIG["image_folder"])
            )
            other_coords: Optional[Tuple[int, int]] = None
            for attempt in range(max_scrolls + 1):
                log(f"upgrade_account: PhaseC attempt {attempt + 1}/{max_scrolls + 1}")

                # Collect all cost-icon positions (gold + elixir)
                cost_positions: List[Tuple[int, int]] = []
                for icon_name in ("gold_upgrade.png", "elixir_upgrade.png"):
                    icon_path = img_folder / icon_name
                    if icon_path.exists():
                        matches = _vision.find_all_templates(
                            template_path=icon_path,
                            threshold=CONFIG["confidence_threshold"],
                            region=(search_x1, search_y1, search_x2, search_y2),
                        )
                        cost_positions.extend(matches)
                    else:
                        log(f"upgrade_account: Warning — template not found: {icon_path}")

                if not cost_positions:
                    log("upgrade_account: No cost icons found")
                    if attempt < max_scrolls:
                        _scroll_down_once()
                    continue

                # Apply Suggested-label filter (same logic as _get_valid_matches)
                suggested = find_text_in_region(
                    "Suggested", search_x1, search_y1, search_x2, search_y2, confidence=0.75
                )
                if suggested:
                    suggested_y = suggested[1]
                    cost_positions = [(x, y) for (x, y) in cost_positions if y > suggested_y]
                    log(f"upgrade_account: 'Suggested' at y={suggested_y} — {len(cost_positions)} icon(s) below it")

                # buildergems template y for exclusion
                buildergems_coords = find_template(
                    "buildergems.png",
                    search_box=(search_x1, search_y1, search_x2, search_y2),
                )
                buildergems_y = buildergems_coords[1] if buildergems_coords else None

                accepted: List[Tuple[int, int]] = []
                for (cx, cy) in cost_positions:
                    # Check each exclusion word via OCR on this row's y-band
                    excluded_by = [
                        w for w in PHASE_C_EXCLUDE_WORDS
                        if find_all_text_in_region(
                            w, search_x1, cy - 15, search_x2, cy + 15, confidence=0.70
                        )
                    ]
                    if excluded_by:
                        log(f"upgrade_account: Rejecting icon at y={cy} — matched exclusion word(s): {excluded_by}")
                        continue
                    if buildergems_y is not None and abs(buildergems_y - cy) <= 15:
                        log(f"upgrade_account: Rejecting icon at y={cy} — buildergems on same row")
                        continue
                    accepted.append((cx, cy))

                if accepted:
                    other_coords = min(accepted, key=lambda p: p[1])  # topmost
                    log(f"upgrade_account: Topmost valid building icon at {other_coords}")
                    break

                log("upgrade_account: All icons excluded — scrolling down")
                if attempt < max_scrolls:
                    _scroll_down_once()

            if not other_coords:
                log("upgrade_account: Nothing found across all phases — exiting")
                nothing_found_to_upgrade = True
                break

            if _do_upgrade_confirm(other_coords):
                log(f"upgrade_account: Building upgraded (iteration {iteration}) — waiting 2s then re-checking")
                upgraded_anything = True
                time.sleep(2)
                continue
            else:
                log("upgrade_account: Building upgrade failed — exiting")
                break

        log("=" * 60)
        log(f"UPGRADE ACCOUNT COMPLETE ({iteration} iteration(s))")
        log("=" * 60)
        # Only return False (trigger account switch) if we genuinely found nothing to upgrade.
        # Early exits (resources not full, no free builder) return True to avoid a spurious switch.
        return upgraded_anything or not nothing_found_to_upgrade

    def rush_upgrade_account(self) -> bool:
        """
        PHASE 5 (Rush mode): Storage → New Building → Town Hall upgrade.

        Identical to upgrade_account() for Phases A and B.  Phase C changes:
        instead of upgrading any non-TownHall building it specifically looks
        for the Town Hall (cost icon whose row contains the word "Hall") and
        upgrades it.  If no Town Hall cost icon is found, it means the TH is
        already upgrading — return False to signal the caller to switch account.

        Builder-gem rows and the Suggested-label filter are applied exactly as
        in upgrade_account().
        """
        if self.stop_requested:
            return False

        log("=" * 60)
        log("PHASE 5 (RUSH): Storage / New Building / Town Hall")
        log("=" * 60)

        search_x1, search_y1, search_x2, search_y2 = 771, 149, 1045, 667
        scroll_cx = (search_x1 + search_x2) // 2
        scroll_cy = (search_y1 + search_y2) // 2
        max_scrolls = 3
        max_retry = 5

        def _scroll_down_once() -> None:
            pyautogui.moveTo(scroll_cx, scroll_cy, duration=0.1)
            pyautogui.drag(0, -200, duration=0.3)
            time.sleep(0.4)

        def _scroll_up_n(n: int) -> None:
            for _ in range(n):
                pyautogui.moveTo(scroll_cx, scroll_cy, duration=0.1)
                pyautogui.drag(0, 200, duration=0.3)
                time.sleep(0.4)

        def _get_valid_matches(word: str) -> List[Tuple[int, int]]:
            all_matches = find_all_text_in_region(word, search_x1, search_y1, search_x2, search_y2, confidence=0.75)
            if not all_matches:
                return []
            suggested = find_text_in_region("Suggested", search_x1, search_y1, search_x2, search_y2, confidence=0.75)
            if suggested:
                suggested_y = suggested[1]
                valid = [(x, y) for (x, y) in all_matches if y > suggested_y]
                log(f"Rush Phase5: 'Suggested' at y={suggested_y} — {len(valid)}/{len(all_matches)} '{word}' match(es) valid")
            else:
                log(f"Rush Phase5: 'Suggested' not found — all {len(all_matches)} '{word}' match(es) valid")
                valid = all_matches
            return valid

        def _search_with_scroll_down(word: str) -> Optional[Tuple[int, int]]:
            for attempt in range(max_scrolls + 1):
                log(f"Rush Phase5: Searching for '{word}' (attempt {attempt + 1}/{max_scrolls + 1})")
                valid = _get_valid_matches(word)
                if valid:
                    chosen = random.choice(valid)
                    log(f"Rush Phase5: Randomly selected '{word}' at {chosen} from {len(valid)} valid option(s)")
                    return chosen
                if attempt < max_scrolls:
                    log(f"Rush Phase5: No valid '{word}' found, scrolling down...")
                    _scroll_down_once()
            return None

        def _find_template_with_retry(name: str) -> Optional[Tuple[int, int]]:
            for attempt in range(1, max_retry + 1):
                coords = find_template(name)
                if coords:
                    return coords
                if attempt < max_retry:
                    time.sleep(0.2)
            return None

        def _do_place_new_building(item_coords: Tuple[int, int]) -> bool:
            log(f"Rush Phase5: Clicking item (placement flow) at {item_coords}...")
            click_with_jitter(*item_coords)
            time.sleep(2.0)
            arrow_coords = _find_template_with_retry("arrow_orange.png")
            if not arrow_coords:
                log("Rush Phase5: 'arrow_orange.png' not found - aborting placement")
                return False
            click_x = arrow_coords[0] - 100
            click_y = arrow_coords[1] + 100
            click_with_jitter(click_x, click_y)
            time.sleep(0.8)
            build_confirm_coords = _find_template_with_retry("build_confirm.png")
            if not build_confirm_coords:
                log("Rush Phase5: 'build_confirm.png' not found - aborting placement")
                return False
            click_with_jitter(*build_confirm_coords)
            time.sleep(0.5)
            _attempt_gem_speed_up("Rush Phase5 new building")
            return True

        def _do_upgrade_confirm(item_coords: Tuple[int, int]) -> bool:
            log(f"Rush Phase5: Clicking item at {item_coords}...")
            click_with_jitter(*item_coords)
            time.sleep(0.5)
            upgrade_coords = _find_template_with_retry("upgrade_button_singular.png")
            if not upgrade_coords:
                log("Rush Phase5: Upgrade button not found - aborting")
                return False
            click_with_jitter(*upgrade_coords)
            time.sleep(0.5)
            confirm_coords = _find_template_with_retry("confirm_storage.png")
            if not confirm_coords:
                log("Rush Phase5: Confirm button not found - aborting")
                return False
            click_with_jitter(*confirm_coords)
            time.sleep(0.5)
            _attempt_gem_speed_up("Rush Phase5 upgrade")
            return True

        iteration = 0
        upgraded_anything = False
        nothing_found_to_upgrade = False

        while not self.stop_requested:
            iteration += 1
            log(f"Rush Phase5: ===== ITERATION {iteration} =====")

            gold_full = check_gold_full()
            elixir_full = check_elixir_full()
            if not (gold_full and elixir_full):
                log(f"Rush Phase5: Resources not both full (gold={gold_full}, elixir={elixir_full}) — exiting")
                break

            no_builders_coords = find_template(
                "nobuilders.png",
                confidence=0.8,
                search_box=(835, 2, 1094, 129),
            )
            if no_builders_coords:
                log("Rush Phase5: No free builder — exiting")
                break

            log("Rush Phase5: Conditions met — opening upgrade menu...")
            click_with_jitter(907, 50)
            time.sleep(0.3)

            # ===== PHASE A: Storage =====
            log("Rush Phase5: ===== PHASE A: Searching for Storage =====")
            storage_coords = _search_with_scroll_down("Storage")

            if storage_coords:
                storage_y = storage_coords[1]
                new_matches_in_region = find_all_text_in_region(
                    "New", search_x1, search_y1, search_x2, search_y2, confidence=0.75
                )
                matching_new_ys = [ny for (_, ny) in new_matches_in_region if abs(ny - storage_y) <= 15]
                is_new_storage = bool(matching_new_ys)

                if is_new_storage:
                    log(f"Rush Phase5: New storage to place at y={storage_y}")
                    if _do_place_new_building(storage_coords):
                        upgraded_anything = True
                        time.sleep(2)
                        continue
                    log("Rush Phase5: New storage placement failed — continuing to Phase B")
                else:
                    log(f"Rush Phase5: Existing storage to upgrade at y={storage_y}")
                    if _do_upgrade_confirm(storage_coords):
                        upgraded_anything = True
                        time.sleep(2)
                        continue
                    log("Rush Phase5: Storage upgrade failed — continuing to Phase B")

            # ===== PHASE B: New building =====
            log("Rush Phase5: ===== PHASE B: Searching for New buildings =====")
            _scroll_up_n(3)

            new_accepted_coords = None
            for attempt in range(max_scrolls + 1):
                log(f"Rush Phase5: Searching for 'New' (attempt {attempt + 1}/{max_scrolls + 1})")
                new_candidates = _get_valid_matches("New")

                if new_candidates:
                    hut_matches = find_all_text_in_region("Hut", search_x1, search_y1, search_x2, search_y2, confidence=0.75)
                    hut_ys = [hy for (_, hy) in hut_matches]

                    buildergems_coords = find_template(
                        "buildergems.png",
                        search_box=(search_x1, search_y1, search_x2, search_y2),
                    )
                    buildergems_y = buildergems_coords[1] if buildergems_coords else None

                    accepted = []
                    for (nx, ny) in new_candidates:
                        if any(abs(hy - ny) <= 15 for hy in hut_ys):
                            log(f"Rush Phase5: Rejecting 'New' at ({nx},{ny}) — Builder's Hut row")
                        elif buildergems_y is not None and abs(buildergems_y - ny) <= 15:
                            log(f"Rush Phase5: Rejecting 'New' at ({nx},{ny}) — buildergems row")
                        else:
                            accepted.append((nx, ny))

                    if accepted:
                        chosen = random.choice(accepted)
                        log(f"Rush Phase5: Selected 'New' at {chosen}")
                        new_accepted_coords = chosen
                        break
                    else:
                        log("Rush Phase5: All 'New' matches are Builder's Huts — scrolling down")
                else:
                    log("Rush Phase5: No valid 'New' found")

                if attempt < max_scrolls:
                    _scroll_down_once()

            if new_accepted_coords:
                if _do_place_new_building(new_accepted_coords):
                    log(f"Rush Phase5: New building placed (iteration {iteration})")
                    upgraded_anything = True
                    time.sleep(2)
                    continue
                log("Rush Phase5: New building placement failed — continuing to Phase C")

            # ===== PHASE C: Town Hall only =====
            log("Rush Phase5: ===== PHASE C: Searching for Town Hall =====")
            _scroll_up_n(3)

            th_coords: Optional[Tuple[int, int]] = None
            for attempt in range(max_scrolls + 1):
                log(f"Rush Phase5: PhaseC attempt {attempt + 1}/{max_scrolls + 1}")

                # Search directly for "Town" or "Hall" text in the region
                town_matches = find_all_text_in_region(
                    "Town", search_x1, search_y1, search_x2, search_y2, confidence=0.50
                )
                hall_matches = find_all_text_in_region(
                    "Hall", search_x1, search_y1, search_x2, search_y2, confidence=0.50
                )
                all_matches = town_matches + hall_matches
                log(f"Rush Phase5: Found {len(town_matches)} 'Town' + {len(hall_matches)} 'Hall' matches")

                if not all_matches:
                    log("Rush Phase5: Neither 'Town' nor 'Hall' found")
                    if attempt < max_scrolls:
                        _scroll_down_once()
                    continue

                # Suggested-label filter
                suggested = find_text_in_region(
                    "Suggested", search_x1, search_y1, search_x2, search_y2, confidence=0.75
                )
                suggested_y = suggested[1] if suggested else None
                if suggested_y:
                    all_matches = [(x, y) for (x, y) in all_matches if y > suggested_y]
                    log(f"Rush Phase5: 'Suggested' at y={suggested_y} — {len(all_matches)} match(es) below it")

                # Filter out buildergems rows
                buildergems_coords = find_template(
                    "buildergems.png",
                    search_box=(search_x1, search_y1, search_x2, search_y2),
                )
                buildergems_y = buildergems_coords[1] if buildergems_coords else None
                if buildergems_y is not None:
                    all_matches = [(x, y) for (x, y) in all_matches if abs(buildergems_y - y) > 15]

                if all_matches:
                    th_coords = min(all_matches, key=lambda p: p[1])
                    log(f"Rush Phase5: Town Hall text found — clicking at {th_coords}")
                    break

                log("Rush Phase5: No valid Town Hall text found on this scroll — scrolling down")
                if attempt < max_scrolls:
                    _scroll_down_once()

            if not th_coords:
                log("Rush Phase5: Town Hall not found — TH must be upgrading, signalling account switch")
                nothing_found_to_upgrade = True
                break

            if _do_upgrade_confirm(th_coords):
                log(f"Rush Phase5: Town Hall upgraded (iteration {iteration})")
                upgraded_anything = True
                time.sleep(2)
                continue
            else:
                log("Rush Phase5: Town Hall upgrade confirm failed — exiting")
                break

        log("=" * 60)
        log(f"RUSH UPGRADE ACCOUNT COMPLETE ({iteration} iteration(s))")
        log("=" * 60)
        return upgraded_anything or not nothing_found_to_upgrade

    def phase1_enter_battle(self, skip_account_check: bool = False) -> bool:
        """
        PHASE 1: Enter Battle
        Search and click: attack_button → find_button → enter_battle
        If any button fails 15 times, restart Phase 1 from the attack button.
        Returns True if successful, False on stop request.
        """

        # Check for pause before starting new battle
        while self.pause_requested:
            time.sleep(0.1)  # Wait until unpaused

        # Ensure we are on an approved account (OCR name check)
        if not skip_account_check:
            if not self.ensure_approved_account():
                return False

        log("=" * 60)
        log("PHASE 1: ENTERING BATTLE")
        log("=" * 60)

        # Check for error button immediately
        if check_for_error_button():
            return False  # Will trigger restart in main loop

        # Check for layout editor and exit if detected
        log("Checking for layout editor...")
        layout_coords = find_template(CONFIG["layout_editor_text"])
        if layout_coords:
            log(f"Layout editor detected at ({layout_coords[0]}, {layout_coords[1]}), clicking exit at (1843, 69)")
            click_with_jitter(1843, 69)
            time.sleep(0.5)
        else:
            log("No layout editor detected, proceeding...")

        # Scroll down 5 times
        log("Scrolling down 5 times...")
        scroll_down_5_times(WHEEL_DELTA * 3)

        # Optional Clan Games routine (runs before normal attack flow)
        if CONFIG.get("clan_games_enabled", False):
            log("Phase 1: Clan Games enabled - running Clan Games routine")
            if not self.run_clan_games_flow():
                log("Phase 1: Clan Games routine failed - aborting this battle cycle")
                return False
            log("Phase 1: Clan Games routine finished - continuing normal battle entry")

        # Claim completed achievements before entering battle.
        # Pixel (85, 39) turns red when an achievement is ready to claim.
        log("Phase 1: Checking for claimable achievements at pixel (85, 39)...")
        achievement_red = (200, 50, 50)
        while not self.stop_requested:
            if is_pixel_near_color(85, 39, achievement_red, tolerance=80):
                log("Phase 1: Achievement pixel is red — clicking (85, 39) to open achievements")
                click_with_jitter(85, 39)
                time.sleep(1.0)
                claim_coords = find_template("claim_reward.png", confidence=0.8)
                if claim_coords:
                    log(f"Phase 1: Clicking claim_reward.png at {claim_coords}")
                    click_with_jitter(*claim_coords)
                    time.sleep(0.5)
                    log("Phase 1: Clicking (100, 356) to return to main screen")
                    click_with_jitter(100, 356)
                    time.sleep(0.5)
                else:
                    log("Phase 1: claim_reward.png not found — closing achievement panel")
                    pyautogui.press("esc")
                    time.sleep(0.5)
                    break
            else:
                log("Phase 1: Achievement pixel not red — no rewards to claim")
                break

        phase1_attempt = 0
        max_phase1_attempts = 5

        while phase1_attempt < max_phase1_attempts:
            phase1_attempt += 1
            if self.stop_requested:
                return False

            log(f"[Phase 1 attempt {phase1_attempt}/{max_phase1_attempts}]")

            # Step 1: Click attack button (15 attempts, no fallback)
            attack_found = search_and_click(CONFIG["attack_button"], "Attack Button", max_attempts=15, use_fallback=False)
            if not attack_found:
                log(f"Failed to find attack button (attempt {phase1_attempt}/{max_phase1_attempts})")
                time.sleep(1.0)
                continue

            log("Attack button clicked, waiting for find button menu...")
            time.sleep(0.5)

            # Step 2: Search for and click find button (will use rightmost if multiple found)
            find_found = search_and_click(CONFIG["find_button"], "Find Button", max_attempts=15, use_fallback=False)
            if not find_found:
                log(f"Failed to find Find button (attempt {phase1_attempt}/{max_phase1_attempts})")
                review_coords = find_template("review_nothanks.png", confidence=0.8)
                if review_coords:
                    log(f"Found review_nothanks.png at {review_coords} — clicking to dismiss")
                    click_with_jitter(*review_coords)
                    time.sleep(0.5)
                time.sleep(1.0)
                continue

            time.sleep(0.5)

            # Optional request flow between find and enter battle
            if CONFIG.get("request_enabled", False):
                log("Request flow enabled - searching for request_button.png...")
                request_button_coords = find_template("request_button.png")
                if request_button_coords:
                    log(f"Found request_button.png at ({request_button_coords[0]}, {request_button_coords[1]}), clicking...")
                    click_with_jitter(*request_button_coords)
                    random_delay()
                    time.sleep(0.2)

                    log("Searching for request_edit.png...")
                    request_edit_coords = find_template("request_edit.png")
                    if request_edit_coords:
                        log(f"Found request_edit.png at ({request_edit_coords[0]}, {request_edit_coords[1]}), clicking...")
                        click_with_jitter(*request_edit_coords)
                        random_delay()
                        time.sleep(0.2)

                        log("Removing existing request items using rightmost request_remove.png...")
                        remove_clicks = 0
                        while not self.stop_requested:
                            remove_coords, match_count = find_rightmost_template_with_count("request_remove.png")
                            if not remove_coords:
                                break
                            remove_clicks += 1
                            log(
                                f"Found request_remove.png (matches={match_count}) at ({remove_coords[0]}, {remove_coords[1]}), clicking rightmost"
                            )
                            click_with_jitter(*remove_coords)
                            random_delay()
                            time.sleep(0.15)
                        log(f"Request remove loop complete (clicked {remove_clicks} remove button(s))")

                        spell_template = "request_spell.png"
                        log(f"Dragging and searching for {spell_template} until found...")
                        spell_icon_coords = None
                        max_drag_attempts = 5
                        drag_attempt = 0
                        while not self.stop_requested and spell_icon_coords is None and drag_attempt < max_drag_attempts:
                            drag_attempt += 1
                            log(f"Drag attempt {drag_attempt}/{max_drag_attempts}")
                            pyautogui.moveTo(1288, 586, duration=0.1)
                            pyautogui.dragTo(733, 586, duration=0.3, button="left")
                            time.sleep(1.0)
                            spell_icon_coords = find_template(spell_template)
                            if spell_icon_coords is None:
                                log(f"{spell_template} not found after drag {drag_attempt}/{max_drag_attempts}")
                                time.sleep(0.2)

                        if spell_icon_coords:
                            log(f"Found {spell_template} at ({spell_icon_coords[0]}, {spell_icon_coords[1]}), clicking 3 times...")
                            for click_num in range(1, 4):
                                click_with_jitter(*spell_icon_coords)
                                random_delay()
                                time.sleep(0.1)
                                log(f"Spell icon click {click_num}/3 complete")

                            log("Clicking confirmation point at (1335, 861)...")
                            click_with_jitter(1335, 861)
                            random_delay()
                            time.sleep(0.2)

                            log("Searching for request_send.png...")
                            request_send_coords = find_template("request_send.png")
                            if request_send_coords:
                                log(f"Found request_send.png at ({request_send_coords[0]}, {request_send_coords[1]}), clicking...")
                                click_with_jitter(*request_send_coords)
                                random_delay()
                                time.sleep(0.2)
                            else:
                                log("request_send.png not found - continuing to enter battle")
                        else:
                            if not self.stop_requested:
                                log(f"{spell_template} not found after {max_drag_attempts} drags - aborting request flow and pressing Escape twice")
                                pyautogui.press("esc")
                                time.sleep(0.15)
                                pyautogui.press("esc")
                            else:
                                log("Stop requested before spell icon was found - skipping remaining request flow")
                    else:
                        log("request_edit.png not found - skipping request edit/remove flow")
                else:
                    log("request_button.png not found - skipping request flow")

            # Optional fill army check between find button and enter battle
            if CONFIG.get("fill_army", False):
                log("Fill army enabled — checking for army_not_full.png...")
                army_not_full = find_template(
                    "army_not_full.png",
                    search_box=(600, 250, 900, 350),
                    confidence=0.8,
                )
                if army_not_full:
                    log("Army not full — opening barracks to fill army...")
                    click_with_jitter(1100, 388)
                    time.sleep(0.5)
                    log("Clicking train button at (257, 805) 20 times to fill army...")
                    for i in range(20):
                        click_with_jitter(257, 805)
                        time.sleep(0.2)
                    CONFIG["num_battle_points"] += 20
                    log(f"Army topped up — increased battle points to {CONFIG['num_battle_points']}")
                    # Persist the updated num_battle_points to account_configs.json
                    account_name = normalize_account_name(self.current_account_name or "")
                    if account_name:
                        try:
                            cfg_path = Path(__file__).parent / "account_configs.json"
                            cfg_data = json.loads(cfg_path.read_text(encoding="utf-8"))
                            if account_name in cfg_data.get("accounts", {}):
                                cfg_data["accounts"][account_name]["num_battle_points"] = CONFIG["num_battle_points"]
                                cfg_path.write_text(json.dumps(cfg_data, indent=2), encoding="utf-8")
                                log(f"Saved num_battle_points={CONFIG['num_battle_points']} for '{account_name}' to account_configs.json")
                        except Exception as e:
                            log(f"Warning: failed to save num_battle_points to config: {e}")
                    log("Clicking back at (257, 500)...")
                    click_with_jitter(257, 500)
                    time.sleep(0.5)
                else:
                    log("Army is full — continuing to enter battle")

            # Step 3: Click enter battle button (15 attempts, no fallback)
            enter_found = search_and_click(CONFIG["enter_battle"], "Enter Battle Button", max_attempts=15, use_fallback=False)
            if not enter_found:
                log(f"Failed to find enter battle button (attempt {phase1_attempt}/{max_phase1_attempts})")
                time.sleep(1.0)
                continue

            # Additional click after entering battle
            time.sleep(0.1)
            log("Clicking confirmation at (1122, 680)...")
            click_with_jitter(1122, 680)

            # All steps successful
            log("✓ Successfully entered battle!")
            return True

        # If we get here, all attempts failed
        log(f"✗ Phase 1 failed after {max_phase1_attempts} attempts - returning False")
        return False

    def phase2_prepare(self) -> bool:
        """
        PHASE 2A: Preparation
        - Wait for end_button to confirm battle is loaded
        - Extract and validate loot amount
        - Skip and restart Phase 2A if loot is below threshold or not found
        - Scroll down once loot is acceptable
        Returns True when ready to proceed, False on failure/stop.
        """
        if self.stop_requested:
            return False

        log("=" * 60)
        log("PHASE 2A: PREPARATION")
        log("=" * 60)

        # ========== EMERGENCY LOW-GOLD CHECK ==========
        # Check if out of gold (more_gold_text.png found = no gold left = attack any base)
        log("Checking for low-gold condition (more_gold_text.png)...")
        more_gold_coords = find_template("more_gold_text.png", confidence=0.70)

        if more_gold_coords:
            log(f"LOW GOLD DETECTED at {more_gold_coords} - must attack immediately!")
            log("Clicking emergency attack point at (955, 658)...")
            click_with_jitter(955, 658)
            time.sleep(0.1)
            log("Emergency low-gold attack activated - proceeding without loot validation")
            return True

        log("Sufficient gold available - proceeding with normal loot validation checks")

        first_pass = True
        while True:
            if self.stop_requested:
                return False
            if not first_pass:
                log("Retrying Phase 2A: waiting for a new battle...")
            first_pass = False

            # Wait for battle to load by detecting end button or surrender button (do NOT click it)
            log("Waiting for battle to load (searching for end/surrender button)...")
            battle_loaded = False
            surrender_button_found = False
            for attempt in range(1, CONFIG["max_search_attempts"] + 1):
                screenshot = pyautogui.screenshot()
                if check_for_error_buttons_in_screenshot(screenshot):
                    return False
                end_coords = find_template(CONFIG["end_button"], screenshot=screenshot)
                surrender_coords = find_template(CONFIG["surrender_button"], screenshot=screenshot)

                if end_coords:
                    log(f"Battle loaded! End button detected at ({end_coords[0]}, {end_coords[1]}) - NOT clicking, just verifying...")
                    battle_loaded = True
                    surrender_button_found = False
                    break
                elif surrender_coords:
                    log(f"Battle loaded! Surrender button detected at ({surrender_coords[0]}, {surrender_coords[1]}) - skipping loot validation...")
                    battle_loaded = True
                    surrender_button_found = True
                    break

                if attempt < CONFIG["max_search_attempts"]:
                    time.sleep(CONFIG["wait_between_attempts"])

            if not battle_loaded:
                log("FAILED: Battle did not load (end/surrender button not found)")
                return False

            # If surrender button found, skip loot validation and attack immediately
            if surrender_button_found:
                log("Surrender button detected - attacking first base without loot validation")

                # Scroll down a little bit using Windows API
                log("Scrolling down...")
                scroll_down_api(WHEEL_DELTA)  # Scroll down
                time.sleep(0.3)

                # Small delay before moving to Phase 2B
                time.sleep(0.1)
                return True

            # Normal loot validation for end button case
            # Extract loot amount from the battle info box
            loot_amount = extract_loot_amount(78, 121, 208, 152)
            min_loot = CONFIG["min_loot_amount"]

            # Check if loot is acceptable
            if loot_amount is None or loot_amount < min_loot:
                if loot_amount is None:
                    log("Loot not found - skipping this battle")
                else:
                    log(f"Loot too low ({loot_amount:,} < {min_loot:,}) - skipping this battle")

                # Click skip button at (1788, 819)
                log("Clicking skip button at (1788, 819)...")
                click_with_jitter(1788, 819)
                time.sleep(0.1)
                # Loop back to wait for next battle
                continue

            # Loot is acceptable, continue with battle
            log(f"Loot acceptable ({loot_amount:,} >= {min_loot:,}) - proceeding with battle")

            # Scroll down a little bit
            log("Scrolling down...")
            pyautogui.scroll(-3)  # Negative value scrolls down
            time.sleep(0.3)

            # Small delay before moving to Phase 2B
            time.sleep(0.1)
            return True

    def phase2_execute(self) -> bool:
        """
        PHASE 2B: Deployment & Abilities
        - Find and click edrag button
        - Click battle points
        - Run ability click sequence
        """
        if self.stop_requested:
            return False

        log("=" * 60)
        log("PHASE 2B: DEPLOYMENT & ABILITIES")
        log("=" * 60)

        # Spell deployment phase with coordinate validation
        max_spell_clicks = CONFIG.get("max_spell_clicks", 15)
        if max_spell_clicks == 0:
            log("Spell capacity is 0 - skipping spell deployment entirely")
        elif not search_and_click(CONFIG["spell_icon"], "Spell Icon", use_fallback=False):
            log("WARNING: Spell icon not found, skipping spell deployment")
        else:
            # Initialize spell deployment tracking - all 15 air defense levels (reverse order)
            ad_templates = [
                CONFIG["ad_15"],
                CONFIG["ad_14"],
                CONFIG["ad_13"],
                CONFIG["ad_12"],
                CONFIG["ad_11"],
                CONFIG["ad_10"],
                CONFIG["ad_9"],
                CONFIG["ad_8"],
                CONFIG["ad_7"],
                CONFIG["ad_6"],
                CONFIG["ad_5"],
                CONFIG["ad_4"],
                CONFIG["ad_3"],
                CONFIG["ad_2"],
                CONFIG["ad_1"],
            ]
            total_spell_clicks = 0
            screen_w, screen_h = pyautogui.size()
            center_x, center_y = screen_w // 2, screen_h // 2

            # Track rejected regions locally to prevent retrying same invalid areas
            rejected_regions: List[Tuple[float, float]] = []
            region_size = CONFIG.get("rejected_region_size", 20)

            log(f"Spell deployment: max_clicks={max_spell_clicks}, rejected_region_size={region_size}px")

            while total_spell_clicks < max_spell_clicks and not self.stop_requested:
                found_valid_target = False
                for tmpl in ad_templates:
                    coords = find_template(tmpl, confidence=CONFIG["ad_confidence_threshold"], search_region=True)

                    if coords:
                        candidate_x, candidate_y = float(coords[0]), float(coords[1])
                        log(f"  Template '{tmpl}' candidate at ({candidate_x}, {candidate_y})")

                        # Check if candidate is in a previously rejected region
                        if is_in_rejected_region(candidate_x, candidate_y, rejected_regions):
                            log(f"    SKIP: Candidate inside rejected region (size={region_size}px)")
                            continue

                        # Validate the coordinate
                        if is_coord_valid(candidate_x, candidate_y):
                            log(f"    ACCEPT: Valid coordinate, dropping spells x3")

                            # Click up to 3 times or until max_spell_clicks reached
                            for click_num in range(1, 4):
                                if total_spell_clicks >= max_spell_clicks:
                                    log(f"      Max spell clicks ({max_spell_clicks}) reached, stopping spell deployment")
                                    break

                                click_with_jitter(int(candidate_x), int(candidate_y))
                                total_spell_clicks += 1
                                log(f"      Click {click_num}/3 at ({candidate_x}, {candidate_y}) (total: {total_spell_clicks}/{max_spell_clicks})")
                                time.sleep(0.1)

                            found_valid_target = True
                            break  # Move to next iteration of while loop to search for next target
                        else:
                            # Coordinate is invalid, add to rejected regions
                            rejected_regions.append((candidate_x, candidate_y))
                            half_size = region_size / 2.0
                            log(f"    REJECT: Invalid coordinate, added rejected region: "
                                f"[{candidate_x - half_size:.0f}, {candidate_x + half_size:.0f}] x "
                                f"[{candidate_y - half_size:.0f}, {candidate_y + half_size:.0f}]")
                            continue  # Try next template

                if found_valid_target:
                    continue  # Loop back to search for next target

                # No more valid air defenses found; drop remaining spells at center
                remaining = max_spell_clicks - total_spell_clicks
                if remaining > 0:
                    log(f"No more valid air defense coordinates; dropping {remaining} spell(s) at center ({center_x}, {center_y})")
                    for click_num in range(1, remaining + 1):
                        click_with_jitter(center_x, center_y)
                        total_spell_clicks += 1
                        log(f"  Center spell click {click_num}/{remaining} at ({center_x}, {center_y}) (total: {total_spell_clicks}/{max_spell_clicks})")
                        time.sleep(0.1)
                break

            log(f"Spell deployment complete: {total_spell_clicks} spell clicks, {len(rejected_regions)} rejected regions")

        # Search for and click the troop button (edrag, drag, azdrag, or barbarian based on config)
        troop_type = CONFIG.get("troop_type", "edrag")
        if troop_type == "drag":
            troop_button_template = CONFIG["drag_button"]
            troop_description = "drag button"
        elif troop_type == "azdrag":
            troop_button_template = CONFIG["azdrag_button"]
            troop_description = "azdrag button"
        elif troop_type == "barbarian":
            troop_button_template = CONFIG["barb_button"]
            troop_description = "barb button"
        else:  # default to edrag
            troop_button_template = CONFIG["edrag_button"]
            troop_description = "edrag button"

        log(f"Searching for {troop_description} to activate...")
        troop_coords = None
        for attempt in range(1, CONFIG["max_search_attempts"] + 1):
            troop_coords = find_template(troop_button_template)

            if troop_coords:
                log(f"Found {troop_description} at ({troop_coords[0]}, {troop_coords[1]}), clicking...")
                click_smooth(*troop_coords)
                break

            if attempt < CONFIG["max_search_attempts"]:
                time.sleep(CONFIG["wait_between_attempts"])
        else:
            log(f"WARNING: {troop_description.capitalize()} not found, continuing anyway...")

        # Small delay before starting clicks
        time.sleep(0.1)

        # Click the battle points in sequence for dragons (limited by num_battle_points config)
        # If more than 10 points requested, loop through the 10 positions multiple times
        num_points = CONFIG["num_battle_points"]
        battle_points_coords = CONFIG["ten_battle_points"]
        log(f"Clicking {num_points} battle points in sequence for dragons...")

        fast_placement = num_points > 16
        if fast_placement:
            log(f"Troop count > 16 ({num_points}) - using fast deployment clicks")
        for i in range(num_points):
            # Use modulo to loop through the 10 positions
            coord_index = i % len(battle_points_coords)
            x, y = battle_points_coords[coord_index]
            log(f"Placing troop at battle point {i+1}: ({x}, {y})")
            if fast_placement:
                click_deploy(x, y)
            else:
                click_with_jitter(x, y)
                random_delay()
            if (i + 1) % 10 == 0 and i + 1 < num_points:
                log(f"Completed {i + 1} battle points, looping back to position 1...")

        log(f"All {num_points} troops placed!")

        # Check if event is active (place event dragons)
        event_active = CONFIG.get("event_active_for_battle", CONFIG.get("event_active", False))
        siege_machine_active = CONFIG.get("siege_machine_active", False)

        log(f"DEBUG: event_active_for_battle={CONFIG.get('event_active_for_battle', 'NOT SET')}, event_active config={CONFIG.get('event_active', False)}, final event_active={event_active}")

        # Get all battle points for random selection (if needed for event troops)
        all_battle_points = CONFIG["ten_battle_points"]

        if event_active:
            log("Event is active! Placing event dragons...")

            # Search for event troop button
            event_troop_button = CONFIG.get("event_troop_button", "drag_button.png")
            log(f"Searching for {event_troop_button} to activate...")

            event_troop_found = False
            for attempt in range(1, CONFIG["max_search_attempts"] + 1):
                event_troop_coords = find_template(event_troop_button, confidence=CONFIG.get("confidence_threshold", 0.75))

                if event_troop_coords:
                    log(f"Found event troop button at ({event_troop_coords[0]}, {event_troop_coords[1]}), clicking...")
                    click_smooth(*event_troop_coords)
                    event_troop_found = True
                    break

                if attempt < CONFIG["max_search_attempts"]:
                    time.sleep(CONFIG["wait_between_attempts"])

            if not event_troop_found:
                log("WARNING: Event troop button not found, skipping event placement...")
            else:
                # Place event troops at random battle points
                event_troop_count = CONFIG.get("event_troop_count", 16)
                if event_troop_count <= len(all_battle_points):
                    event_troop_points = random.sample(all_battle_points, event_troop_count)
                else:
                    event_troop_points = random.choices(all_battle_points, k=event_troop_count)
                log(f"Placing event dragons at {len(event_troop_points)} battle points: {event_troop_points}")

                for i, (x, y) in enumerate(event_troop_points):
                    log(f"Placing event dragon at battle point {i+1}: ({x}, {y})")
                    click_with_jitter(x, y)
                    random_delay()

                log("Event dragon placement complete!")
        else:
            log(f"Event NOT active for this battle - skipping event dragons (event_active_for_battle={CONFIG.get('event_active_for_battle', 'NOT SET')})")

        # Small delay before hero placement
        time.sleep(0.1)

        # Calculate hero coordinates based on event and siege status
        base_hero_coords = [511, 622, 733, 844]

        # Determine whether the event troop occupies a separate slot from the main troop
        _troop_type = CONFIG.get("troop_type", "edrag")
        if _troop_type == "drag":
            _main_tpl = CONFIG["drag_button"]
        elif _troop_type == "azdrag":
            _main_tpl = CONFIG["azdrag_button"]
        elif _troop_type == "barbarian":
            _main_tpl = CONFIG["barb_button"]
        else:
            _main_tpl = CONFIG["edrag_button"]
        _event_tpl = CONFIG.get("event_troop_button", "")
        event_adds_slot = event_active and (_event_tpl != _main_tpl)

        # Apply coordinate shifts
        hero_x_shift = 0
        if event_adds_slot:
            hero_x_shift += 111  # Shift right only when event adds a distinct extra slot

        if siege_machine_active:
            hero_x_shift += 111  # Shift right another 111 if siege is active

        # Calculate the shifted hero coordinates
        hero_coords = [x + hero_x_shift for x in base_hero_coords]

        # Determine siege placement coordinate (original hero position before shifts)
        siege_placement_x = None
        if siege_machine_active:
            if event_adds_slot:
                siege_placement_x = 622  # Original first hero position after event shift
            else:
                siege_placement_x = 511  # Original first hero position without event shift
            log(f"Siege machine will be placed at x={siege_placement_x}")

        num_heroes = CONFIG["num_heroes"]

        # Trim hero coords to num_heroes
        selected_hero_coords = hero_coords[:num_heroes]

        # If no heroes, skip hero placement
        if num_heroes == 0:
            log("No heroes configured, skipping hero placement and abilities.")
            return True

        log(f"Hero coordinates after shifts: {selected_hero_coords}")
        abilities_coord = CONFIG["abilities_click_coord"]

        log(f"Placing {num_heroes} hero(es)...")
        for i, x_coord in enumerate(selected_hero_coords):
            log(f"Selecting hero {i+1} at ({x_coord}, 991)")
            click_with_jitter(x_coord, 991)
            log(f"Placing hero {i+1} at abilities coord {abilities_coord}")
            click_with_jitter(*abilities_coord)
            random_delay()

        log("All heroes placed!")

        # Place siege machine if active
        if siege_machine_active and siege_placement_x is not None:
            log(f"Placing siege machine at ({siege_placement_x}, 991)...")
            click_with_jitter(siege_placement_x, 991)
            log(f"Placing siege machine at abilities coord {abilities_coord}")
            click_with_jitter(*abilities_coord)
            log("Siege machine placed!")

        # Wait before activating abilities
        time_before_ability = CONFIG["time_before_ability"]
        log(f"Waiting {time_before_ability} seconds before activating abilities...")
        time.sleep(time_before_ability)

        # Activate all hero abilities (and siege if active)
        log("Activating all hero abilities...")
        for i, x_coord in enumerate(selected_hero_coords):
            log(f"Activating ability for hero {i+1} at ({x_coord}, 991)")
            click_with_jitter(x_coord, 991)
            random_delay()

        # Activate siege machine ability if active
        #if siege_machine_active and siege_placement_x is not None:
        #    log(f"Activating siege machine ability at ({siege_placement_x}, 991)")
        #    click_with_jitter(siege_placement_x, 991)

        log("Ability sequence complete!")
        return True

    def phase3_wait_for_return(self) -> bool:
        """
        PHASE 3: Wait for Battle to End
        Poll for return button or claim reward button every polling_interval_phase3 seconds.
        Click it when found.
        Returns True when return button is clicked, False if error.
        """
        if self.stop_requested:
            return False

        log("=" * 60)
        log("PHASE 3: WAITING FOR BATTLE TO END")
        log("=" * 60)

        poll_interval = CONFIG["polling_interval_phase3"]
        log(f"Polling for return button or claim reward button every {poll_interval} seconds...")

        attempt = 0
        battle_start_time = time.time()
        while True:
            attempt += 1

            # Check for return/claim reward buttons using a single screenshot
            screenshot = pyautogui.screenshot()
            if check_for_error_buttons_in_screenshot(screenshot):
                return False
            return_coords = find_template(CONFIG["return_button"], screenshot=screenshot)

            # Check for claim reward button
            claim_reward_coords = find_template(CONFIG["claim_reward_button"], screenshot=screenshot)

            if return_coords:
                log(f"Battle ended! Return button found at ({return_coords[0]}, {return_coords[1]})")

                # Wait for loot numbers to appear, then capture before exiting
                log("Waiting 2 seconds to capture loot before returning...")
                time.sleep(2.5)
                try:
                    snapshot = self.loot_tracker.extract_and_record()
                    log(f"✓ Loot captured successfully: {snapshot}")
                except Exception as e:
                    log(f"✗ WARNING: Failed to record loot automatically: {e}")
                    import traceback
                    traceback.print_exc()

                # Click return button with jitter
                click_x, click_y = add_jitter(*return_coords)
                log(f"Clicking return button at ({click_x}, {click_y})")
                pyautogui.click(click_x, click_y)
                random_delay()

                self.dismiss_star_bonus_popup_after_return()

                return True

            elif claim_reward_coords:
                log(f"Battle ended! Claim reward button found at ({claim_reward_coords[0]}, {claim_reward_coords[1]})")

                # Wait for loot numbers to appear, then capture before exiting
                log("Waiting 2 seconds to capture loot before claiming reward...")
                time.sleep(2.5)
                try:
                    snapshot = self.loot_tracker.extract_and_record()
                    log(f"✓ Loot captured successfully: {snapshot}")
                except Exception as e:
                    log(f"✗ WARNING: Failed to record loot automatically: {e}")
                    import traceback
                    traceback.print_exc()

                # Click claim reward button with jitter
                click_x, click_y = add_jitter(*claim_reward_coords)
                log(f"Clicking claim reward button at ({click_x}, {click_y})")
                pyautogui.click(click_x, click_y)

                # Wait 5 seconds
                log("Waiting 5 seconds after claiming reward...")
                time.sleep(5)

                # Click the screen 5 times with 1 second gaps
                log("Clicking screen 5 times with 1 second intervals...")
                screen_w, screen_h = pyautogui.size()
                center_x, center_y = screen_w // 2, screen_h // 2
                for i in range(1, 6):
                    log(f"Click {i}/5 at center ({center_x}, {center_y})")
                    pyautogui.click(center_x, center_y)
                    if i < 5:  # Don't wait after the last click
                        time.sleep(1)

                # Wait 2 seconds after the 5th click
                log("Waiting 2 seconds after 5th click...")
                time.sleep(2)

                # Click at (955, 902)
                log("Clicking at final position (955, 902)")
                click_with_jitter(955, 902)
                random_delay()

                self.dismiss_star_bonus_popup_after_return()

                return True

            elapsed = time.time() - battle_start_time
            if elapsed > 600:
                log(f"WARNING: Battle has lasted over 10 minutes ({elapsed:.0f}s). Performing hard reset...")
                pyautogui.hotkey('alt', 'f4')
                time.sleep(5)
                pyautogui.doubleClick(340, 160, interval=0.2)
                time.sleep(20)
                return False

            log(f"Battle still in progress... (check #{attempt})")
            time.sleep(poll_interval)

    def dismiss_star_bonus_popup_after_return(self, max_attempts: int = 5, retry_delay_seconds: float = 1.0) -> bool:
        """
        Optionally dismiss the star bonus popup after returning home.

        Searches for the configured star bonus okay template multiple times with
        a fixed delay between attempts. Returns True if popup was found and clicked,
        False if not found after all attempts.
        """
        phase4_cfg = CONFIG.get("phase4", {})
        star_bonus_template = phase4_cfg.get("star_bonus_okay_template", "star_bonus_okay.png")

        log(
            f"Phase3: Checking for optional star bonus popup '{star_bonus_template}' "
            f"up to {max_attempts} times ({retry_delay_seconds:.1f}s gap)..."
        )

        for attempt in range(1, max_attempts + 1):
            if self.stop_requested:
                return False

            star_bonus_coords = find_template(star_bonus_template)
            if star_bonus_coords:
                log(
                    f"Phase3: Star bonus popup found on attempt {attempt}/{max_attempts} "
                    f"at {star_bonus_coords} - clicking"
                )
                click_with_jitter(*star_bonus_coords)
                random_delay()
                time.sleep(phase4_cfg.get("post_click_delay", 0.25))
                return True

            if attempt < max_attempts:
                log(f"Phase3: Star bonus popup not found (attempt {attempt}/{max_attempts}) - retrying...")
                time.sleep(retry_delay_seconds)

        log("Phase3: Star bonus popup not found after all retries - continuing as normal")
        return False

    def _perform_wall_upgrade(self, resource_type: str = "gold", confirm_click_x: int = 1075) -> bool:
        """
        [DEPRECATED] Old Phase 4 upgrade helper - kept for backward compatibility.

        This function implements the old text-based wall upgrade flow that requires
        manually dragging through the upgrade list to find "wall". It is retained as
        a fallback for edge cases or gradual migration scenarios.

        New code should use perform_wall_upgrade_flow() instead, which implements the
        exact More/Add/Upgrade/pixel-trigger sequence.

        Helper function to perform a single wall upgrade (gold or elixir).
        - Click (907,44) to open upgrades menu
        - Search for "wall" text in region (744,134) to (1210,684)
        - If not found, drag down and retry (max 5 drags)
        - Click the wall text when found
        - Click (934,818) 5 times with 0.2s delay
        - Click (confirm_click_x, 818) once
        - Click (1162,642) once
        """

        log(f"[DEPRECATED] _perform_wall_upgrade: Performing {resource_type.upper()} wall upgrade...")

        # Step 1: Click upgrade menu
        log("Clicking upgrade menu at (907,44)...")
        click_with_jitter(907, 44)
        time.sleep(0.1)

        # Step 2: Search for "wall" text with drag retry
        wall_coords = None
        max_scroll_attempts = 20
        scroll_attempt = 0

        while scroll_attempt < max_scroll_attempts and not self.stop_requested:
            log(f"Searching for 'wall' in region... (attempt {scroll_attempt + 1}/{max_scroll_attempts})")

            wall_coords = find_text_in_region("wall", 744, 134, 1210, 684, confidence=0.75, find_lowest=True)

            if wall_coords:
                log(f"Found 'wall' at {wall_coords}")
                break

            # Not found, drag down in the region
            if scroll_attempt < max_scroll_attempts - 1:
                log("Wall not found, dragging down...")
                pyautogui.moveTo(977, 670, duration=0.2)
                pyautogui.mouseDown()
                pyautogui.moveTo(977, 430, duration=0.3)
                pyautogui.mouseUp()
                time.sleep(0.4)

            scroll_attempt += 1

        if not wall_coords:
            log(f"WARNING: Could not find 'wall' text after {max_scroll_attempts} scroll attempts - skipping this upgrade")
            return True

        # Step 3: Click the wall text
        log(f"Clicking wall at {wall_coords}...")
        click_with_jitter(*wall_coords)
        time.sleep(0.1)

        # Step 4: Click the resource confirm button 5 times (894,867)
        log("Clicking resource confirm button 5 times...")
        #for i in range(5):
        #    click_with_jitter(894, 867)
        #    time.sleep(0.2)

        log("Resource confirm clicks complete!")

        # Step 5: Click the upgrade confirm button (confirm_click_x, 867)
        log(f"Clicking upgrade confirm button at ({confirm_click_x}, 867)...")
        click_with_jitter(confirm_click_x, 867)
        time.sleep(0.1)

        # Step 6: Click final confirmation at (1136,672)
        log("Clicking final confirmation at (1136,672)...")
        #click_with_jitter(1136, 672)
        #time.sleep(0.1)
        click_with_jitter(1288, 958)
        time.sleep(0.1)

        log(f"{resource_type.upper()} upgrade complete!")
        return True

    def main(self):
        """Main automation loop."""

        log("=" * 60)
        log("CLASH OF CLANS AUTOMATION SCRIPT")
        log("=" * 60)
        log(f"Image folder: {CONFIG['image_folder']}")
        log(f"Confidence threshold: {CONFIG['confidence_threshold']}")
        log(f"Click jitter: ±{CONFIG['click_randomness_px']}px")

        num_runs = CONFIG["num_runs"]
        if num_runs is None or num_runs <= 0:
            log("Running in INFINITE mode (press SPACE or Ctrl+C to stop)")
            infinite_mode = True
        else:
            log(f"Running {num_runs} battles")
            infinite_mode = False

        log("=" * 60)

        # Start Space key listener (when running standalone, not via GUI)
        self.space_listener.start()

        # Validate image folder and list available templates
        script_dir = Path(__file__).parent
        if CONFIG["image_folder"] == ".":
            image_folder = script_dir
        else:
            image_folder = Path(CONFIG["image_folder"])

        log(f"Script directory: {script_dir}")
        log(f"Looking for templates in: {image_folder.absolute()}")

        # List all PNG files found
        png_files = list(image_folder.glob("*.png"))
        if png_files:
            log(f"Found {len(png_files)} PNG files:")
            for png_file in png_files:
                log(f"  - {png_file.name}")
        else:
            log("WARNING: No PNG files found in template folder!")

        # Check for required template files
        required_templates = [
            CONFIG["attack_button"],
            CONFIG["find_button"],
            CONFIG["enter_battle"],
            CONFIG["end_button"],
            CONFIG["edrag_button"],
            CONFIG["return_button"],
        ]
        missing_files = []
        for template in required_templates:
            template_path = image_folder / template
            if not template_path.exists():
                missing_files.append(template)

        if missing_files:
            log("ERROR: Missing required template files:")
            for missing in missing_files:
                log(f"  - {missing}")
            log("Please add these PNG template images to the script folder.")
            sys.exit(1)

        log("All required template files found!")
        log("=" * 60)

        # Start delay
        log("Starting in 3 seconds... (press Ctrl+C to cancel)")
        time.sleep(3)

        run_count = 0

        try:
            while True:
                # Check if Space was pressed to stop
                if self.stop_requested:
                    break

                # Check for pause - wait here before starting next battle
                while self.pause_requested:
                    time.sleep(0.1)  # Poll pause flag every 100ms

                run_count += 1
                battle_start_time = time.time()

                # Reset wall counter for new battle
                self.walls_upgraded_this_battle = 0

                if not infinite_mode:
                    log(f"\n{'=' * 60}")
                    log(f"STARTING BATTLE {run_count}/{num_runs}")
                    log(f"{'=' * 60}\n")
                else:
                    log(f"\n{'=' * 60}")
                    log(f"STARTING BATTLE #{run_count}")
                    log(f"{'=' * 60}\n")

                # Check for error button before starting battle phases
                if check_for_error_button():
                    log("Error button was clicked - restarting from Phase 1...")
                    continue

                # Execute the 3 phases in sequence

                # PHASE 1: Enter battle
                if not self.phase1_enter_battle():
                    log("ERROR: Failed to enter battle. Stopping.")
                    break

                # PHASE 2A + 2B: Battle actions split
                if not self.phase2_prepare():
                    log("ERROR: Failed during Phase 2A (prep). Stopping.")
                    break
                if not self.phase2_execute():
                    log("ERROR: Failed during Phase 2B (deploy). Stopping.")
                    break

                # PHASE 3: Wait for battle to end
                if not self.phase3_wait_for_return():
                    log("ERROR: Failed to detect return button. Stopping.")
                    break

                # PHASE 4: Upgrade walls if loot is full (conditional on auto_upgrade_walls setting)
                if CONFIG.get("auto_upgrade_walls", True):
                    log("Waiting 5 seconds before Phase 4 to allow loading...")
                    time.sleep(5)
                    self.phase4_upgrade()
                else:
                    log("Phase 4 skipped (auto_upgrade_walls is False)")

                # PHASE 5: Upgrade storages if loot is full and a free builder is available
                if CONFIG.get("auto_upgrade_storages", True):
                    log("Phase 5: Upgrading account...")
                    self.upgrade_account()
                else:
                    log("Phase 5 skipped (auto_upgrade_storages is False)")

                # Update per-account stats after battle completes
                battle_duration = time.time() - battle_start_time
                snapshot = getattr(self.loot_tracker, "last_snapshot", None)

                log(f"DEBUG: Preparing to save stats - account='{self.current_account_name}', snapshot={snapshot is not None}, walls={self.walls_upgraded_this_battle}")

                if self.current_account_name and snapshot:
                    try:
                        update_account_stats(self.current_account_name, snapshot, battle_duration, self.walls_upgraded_this_battle)
                        log(f"✓ Stats successfully saved for '{self.current_account_name}'")
                    except Exception as e:
                        log(f"✗ ERROR saving stats: {e}")
                        import traceback
                        traceback.print_exc()
                else:
                    if not self.current_account_name:
                        log("✗ Stats update skipped: No account name found")
                    if not snapshot:
                        log("✗ Stats update skipped: No loot snapshot captured")

                log(f"\nBattle {run_count} completed successfully!\n")

                # Check if we've reached the run limit
                if not infinite_mode and run_count >= num_runs:
                    log("=" * 60)
                    log(f"COMPLETED ALL {num_runs} BATTLES!")
                    log("=" * 60)
                    break

                # Small delay before next battle
                log("Waiting before starting next battle...")
                time.sleep(2.0)

        except KeyboardInterrupt:
            log("\n" + "=" * 60)
            log("STOPPED BY USER (Ctrl+C)")
            log(f"Completed {run_count - 1} full battles")
            log("=" * 60)

        except Exception as e:
            log(f"\nERROR: Unexpected exception occurred: {e}")
            import traceback
            traceback.print_exc()

        finally:
            self.space_listener.stop()
            log("Script terminated.")


# ================================
# BACKWARD COMPATIBILITY
# ================================

# Default session for standalone (non-GUI) usage.
_default_session: HomeBattleSession = HomeBattleSession()


def _compat_ensure_approved_account(max_attempts: int = 100) -> bool:
    return _default_session.ensure_approved_account(max_attempts)


def _compat_phase1_enter_battle(skip_account_check: bool = False) -> bool:
    return _default_session.phase1_enter_battle(skip_account_check)


def _compat_phase2_prepare() -> bool:
    return _default_session.phase2_prepare()


def _compat_phase2_execute() -> bool:
    return _default_session.phase2_execute()


def _compat_phase3_wait_for_return() -> bool:
    return _default_session.phase3_wait_for_return()


def _compat_phase4_upgrade() -> bool:
    return _default_session.phase4_upgrade()


def _compat_upgrade_account() -> bool:
    return _default_session.upgrade_account()


def _compat_rush_upgrade_account() -> bool:
    return _default_session.rush_upgrade_account()


def _compat_main() -> None:
    return _default_session.main()


# Module-level aliases (so ``from Autoclash import phase1_enter_battle`` still works)
ensure_approved_account = _compat_ensure_approved_account
phase1_enter_battle = _compat_phase1_enter_battle
phase2_prepare = _compat_phase2_prepare
phase2_execute = _compat_phase2_execute
phase3_wait_for_return = _compat_phase3_wait_for_return
phase4_upgrade = _compat_phase4_upgrade
upgrade_account = _compat_upgrade_account
rush_upgrade_account = _compat_rush_upgrade_account
main = _compat_main

# Expose default-session objects under their historic names
LOOT_TRACKER = _default_session.loot_tracker
space_listener = _default_session.space_listener
stop_requested = False       # read-only compat; real state lives on session
pause_requested = False      # read-only compat; real state lives on session
# current_account_name: use _default_session.current_account_name directly
walls_upgraded_this_battle = 0


if __name__ == "__main__":
    _default_session.main()
