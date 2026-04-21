#!/usr/bin/env python3
"""
Clash of Clans Builder Base Automation Script
==============================================
Automates Builder Base battles using template matching and pyautogui.

Features:
- Template-based detection of game UI elements
- Automated deployment sequences with random jitter
- Hero ability activation
- Star counting and battle tracking
- Debug mode for testing without clicking
- Graceful handling of battle timeouts and errors

Required packages (install with pip):
    pip install opencv-python numpy pyautogui pillow

Usage:
    python Autoclash_BB.py           # Normal mode
    python Autoclash_BB.py --dry-run # Debug mode (no clicks)
"""

import pyautogui
import cv2
import numpy as np
from PIL import Image
import time
import logging
import signal
import sys
import random
import threading
from pathlib import Path
from typing import Optional, Tuple
import vision as _vision

# Optional: keyboard module for global Space key detection
try:
    import keyboard  # type: ignore
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False
    logging.warning("keyboard module not installed - Space key stopping disabled")

# ================================
# CONFIGURATION
# ================================
CONFIG = {
    # Template filenames
    "BBattack": "BBattack.png",
    "BBfind_match": "BBfind_match.png",
    "return_button": "BBreturn_button.png",
    "end_battle": "end_button.png",
    "okay_upgrade": "okay_BB.png",
    "use_star_jar": "use_star_jar.png",
    "star_jar_accept": "star_jar_accept.png",
    "try_again_button": "try_again_button.png",
    "reload_game_button": "reload_game.png",
    "return_home_button": "return_home.png",
    "account_load_okay": "account_load_okay.png",
    
    # Template matching threshold
    "TEMPLATE_THRESH_DEFAULT": 0.85,
    
    # Color targets and tolerances (RGB)
    "PURPLE_RGB": (177, 60, 224),
    "PURPLE_TOL": 100,
    "ORANGE_RGB": (206, 139, 40),
    "ORANGE_TOL": 50,
    
    # Timings (seconds)
    "DEPLOY_INTERVAL_MIN": 0.1,
    "DEPLOY_INTERVAL_MAX": 0.2,
    "HERO_CHECK_INTERVAL": 1.0,
    "POLL_INTERVAL": 0.5,
    "BATTLE_TIMEOUT": 300,  # seconds - if exceeded, stop script entirely
    
    # Click jitter (pixels)
    "CLICK_JITTER": 5,
    
    # Max battles (None = infinite)
    "MAX_BATTLES": None,
    
    # Debug mode (if True, log clicks but don't execute them)
    "DEBUG": False,

    # Repeated-failure recovery
    "FAILURE_RECOVERY_THRESHOLD": 100,
    "HARD_RESET_CLOSE_COORD": (1859, 16),
    "HARD_RESET_RELAUNCH_COORD": (340, 160),
    "HARD_RESET_POST_LAUNCH_COORD": (1517, 148),
}

# ================================
# COORDINATE SEQUENCES
# ================================
DEPLOY_SEQUENCE = [(16, 319), (542, 694), (998, 380), (124, 408),  (775, 560), (1309, 156)]
HERO_DEPLOY = [(324, 982), (788, 536)]
FIRST_HALF_PIXELS = [(1677, 856), (1719, 856), (1762, 856)]
STAR_PIXELS = [(752, 329), (966, 254), (1182, 343)]
IN_BATTLE_PIXEL = (479, 931)
HERO_ABILITY_PIXEL = (350, 874)

# Second-half sequences (when first half is won with 3 stars)
SECOND_HALF_STAR_RGB = (168, 199, 214)
SECOND_HALF_STAR_TOL = 50
SECOND_HALF_STAR_PIXELS = [(754, 339), (966, 260), (1178, 337)]
SECOND_HALF_DRAG_START = (600, 258)
SECOND_HALF_DRAG_END = (1044, 724)
SECOND_HALF_DEPLOY_POINTS = [(787, 858), (877, 791), (983, 724), (1252, 527), (1469, 503), (1548, 563), (1634, 629), (1763, 727)]
SECOND_HALF_TROOP_TEMPLATE = "bbsecondhalftroop.png"
SECOND_HALF_TROOP_CLICK_OFFSET_Y = -60
HERO_ICON_PIXEL = (324, 982)
HERO_SECOND_CLICK = (1031, 668)

# ================================
# LOGGING
# ================================
logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s] %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)



# ================================
# SIGNAL HANDLING
# ================================
def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully."""
    # Set shutdown flag on default session if it exists
    if '_default_session' in globals():
        _default_session.shutdown_requested = True
    logger.info("SIGINT received - shutting down gracefully...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

# ================================
# SPACE KEY LISTENER
# ================================
class SpaceListener:
    """Listens for Space key press to gracefully stop the script."""
    
    def __init__(self, session=None):
        self.handler = None
        self._session = session
    
    def start(self):
        """Start listening for Space key."""
        if not HAS_KEYBOARD:
            logger.info("keyboard module not available - Space key stopping disabled")
            return
        
        _sess = self._session
        def on_space(_):
            if _sess is not None:
                _sess.shutdown_requested = True
            logger.info("")
            logger.info("=" * 60)
            logger.info("SPACE BAR PRESSED - STOPPING GRACEFULLY...")
            logger.info("=" * 60)
        
        self.handler = keyboard.on_press_key("space", on_space, suppress=False)
        logger.info("Space key listener started. Press SPACE to stop at any time.")
    
    def stop(self):
        """Stop listening for Space key."""
        if HAS_KEYBOARD and self.handler:
            keyboard.unhook(self.handler)
            self.handler = None


# ================================
# UTILITY FUNCTIONS
# ================================

def screenshot_cv() -> np.ndarray:
    """
    Capture screenshot and return as BGR NumPy array for OpenCV.
    
    Returns:
        np.ndarray: BGR image array (height, width, 3)
    """
    pil_img = pyautogui.screenshot()
    # Convert PIL RGB to BGR for OpenCV
    cv_img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    return cv_img


def screenshot_pil() -> Image.Image:
    """
    Capture screenshot and return as PIL Image for pixel checks.
    
    Returns:
        Image.Image: PIL Image in RGB mode
    """
    return pyautogui.screenshot()


def add_jitter(x: int, y: int, jitter_px: int = CONFIG["CLICK_JITTER"]) -> Tuple[int, int]:
    """
    Add random jitter to coordinates.
    
    Args:
        x: X coordinate
        y: Y coordinate
        jitter_px: Max jitter in pixels (±)
    
    Returns:
        Tuple[int, int]: Jittered (x, y)
    """
    x_offset = random.randint(-jitter_px, jitter_px)
    y_offset = random.randint(-jitter_px, jitter_px)
    return (x + x_offset, y + y_offset)


def random_interval() -> float:
    """
    Return random interval between DEPLOY_INTERVAL_MIN and DEPLOY_INTERVAL_MAX.
    
    Returns:
        float: Random interval in seconds
    """
    return random.uniform(CONFIG["DEPLOY_INTERVAL_MIN"], CONFIG["DEPLOY_INTERVAL_MAX"])


def smooth_click(x: int, y: int, move_duration: float = 0.1) -> None:
    """
    Move mouse smoothly to coordinates and click (no teleporting).
    
    Args:
        x: X coordinate
        y: Y coordinate
        move_duration: Duration of mouse movement in seconds
    """
    pyautogui.moveTo(x, y, duration=move_duration)
    pyautogui.click()


def find_template(
    cv_img: np.ndarray,
    template_path: str,
    threshold: float = None,
    region: Optional[Tuple[int, int, int, int]] = None,
    log_not_found: bool = True
) -> Optional[Tuple[int, int]]:
    """
    Search for template image in screenshot using OpenCV template matching.
    Delegates to the shared vision module.

    Args:
        cv_img: OpenCV BGR image array
        template_path: Path to template image file
        threshold: Match threshold (0-1). Defaults to CONFIG['TEMPLATE_THRESH_DEFAULT']
        region: Optional region (x, y, w, h) to search within
        log_not_found: Whether to log when template is not found (default True)

    Returns:
        Optional[Tuple[int, int]]: Center coordinates (x, y) if match found, else None
    """
    if threshold is None:
        threshold = CONFIG["TEMPLATE_THRESH_DEFAULT"]

    # Resolve template path relative to script directory
    script_dir = Path(__file__).parent
    template_full_path = script_dir / template_path

    # Convert (x, y, w, h) region to (x1, y1, x2, y2) for vision module
    vision_region = None
    if region:
        x, y, w, h = region
        vision_region = (x, y, x + w, y + h)

    coords, max_val = _vision.find_template(
        template_path=template_full_path,
        threshold=threshold,
        screenshot=cv_img,
        region=vision_region,
        bgr=True,
    )

    if coords is not None:
        logger.info(f"✓ Found {template_path} at ({coords[0]}, {coords[1]})")
        return coords

    if log_not_found:
        logger.debug(f"Template match: {template_path} -> confidence {max_val:.3f} (threshold {threshold:.3f})")
        logger.debug(f"✗ Template not found: {template_path}")
    return None


def search_and_click(
    template_name: str,
    threshold: float = None,
    region: Optional[Tuple[int, int, int, int]] = None,
    click_type: str = "click"
) -> bool:
    """
    Search for template and click if found (or log if in DEBUG mode).
    
    Args:
        template_name: Key in CONFIG (e.g., "BBattack")
        threshold: Match threshold (optional)
        region: Search region (optional)
        click_type: "click", "down", or "up"
    
    Returns:
        bool: True if found and clicked/logged, False otherwise
    """
    template_path = CONFIG.get(template_name)
    if not template_path:
        logger.error(f"Template name not in CONFIG: {template_name}")
        return False
    
    cv_img = screenshot_cv()
    coords = find_template(cv_img, template_path, threshold, region)
    
    if coords:
        x, y = coords
        x_jit, y_jit = add_jitter(x, y)
        
        if CONFIG["DEBUG"]:
            logger.info(f"[DEBUG] Would {click_type} at ({x_jit}, {y_jit})")
        else:
            if click_type == "click":
                smooth_click(x_jit, y_jit)
            elif click_type == "down":
                pyautogui.moveTo(x_jit, y_jit, duration=0.1)
                pyautogui.mouseDown()
            elif click_type == "up":
                pyautogui.moveTo(x_jit, y_jit, duration=0.1)
                pyautogui.mouseUp()
            logger.info(f"Clicked {template_name} at ({x_jit}, {y_jit})")
        
        return True
    
    return False


def pixel_is_close(
    pil_img: Image.Image,
    coord: Tuple[int, int],
    target_rgb: Tuple[int, int, int],
    tol: int,
    log_result: bool = False
) -> bool:
    """
    Check if pixel at coordinate matches target RGB within tolerance.
    
    Args:
        pil_img: PIL Image
        coord: (x, y) coordinate
        target_rgb: Target RGB tuple
        tol: Euclidean distance tolerance
        log_result: Whether to log the result (default False to reduce spam)
    
    Returns:
        bool: True if pixel is close to target, False otherwise
    """
    try:
        pixel = pil_img.getpixel(coord)
        if isinstance(pixel, int):
            # Grayscale, convert to RGB
            pixel = (pixel, pixel, pixel)
        elif len(pixel) == 4:
            # RGBA, take first 3 channels
            pixel = pixel[:3]
        
        # Compute Euclidean distance
        distance = np.sqrt(sum((pixel[i] - target_rgb[i]) ** 2 for i in range(3)))
        is_close = distance <= tol
        
        if log_result:
            logger.debug(f"Pixel at {coord}: RGB{pixel}, distance to {target_rgb}: {distance:.1f} (tol {tol}) -> {is_close}")
        return is_close
    except Exception as e:
        logger.error(f"Error checking pixel at {coord}: {e}")
        return False


def wait_for_pixel(
    coord: Tuple[int, int],
    target_rgb: Tuple[int, int, int],
    tol: int,
    timeout: float,
    poll_interval: float = CONFIG["POLL_INTERVAL"]
) -> bool:
    """
    Wait for pixel to match target RGB within timeout.
    
    Args:
        coord: (x, y) coordinate
        target_rgb: Target RGB tuple
        tol: Euclidean distance tolerance
        timeout: Max seconds to wait
        poll_interval: Seconds between polls
    
    Returns:
        bool: True if pixel matched before timeout, False otherwise
    """
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        pil_img = screenshot_pil()
        
        if pixel_is_close(pil_img, coord, target_rgb, tol):
            logger.info(f"✓ Pixel {coord} matched target RGB {target_rgb}")
            return True
        
        time.sleep(poll_interval)
    
    logger.warning(f"✗ Pixel {coord} did not match target RGB {target_rgb} within {timeout}s")
    return False


def wait_until_stars_not_orange(timeout: float = 45.0, poll_interval: float = 0.5) -> bool:
    """
    Wait until star pixels are no longer orange (first-half stars disappear).
    
    Args:
        timeout: Max seconds to wait
        poll_interval: Seconds between polls
    
    Returns:
        bool: True if stars became non-orange before timeout, False otherwise
    """
    logger.info("Waiting for first-half stars to disappear...")
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        pil_img = screenshot_pil()
        orange_count = 0
        
        for pixel_coord in STAR_PIXELS:
            if pixel_is_close(pil_img, pixel_coord, CONFIG["ORANGE_RGB"], CONFIG["ORANGE_TOL"]):
                orange_count += 1
        
        if orange_count == 0:
            logger.info("✓ First-half stars are no longer visible")
            return True
        
        time.sleep(poll_interval)
    
    logger.warning(f"✗ Stars still orange after {timeout}s timeout")
    return False


def perform_drag(start: Tuple[int, int], end: Tuple[int, int], times: int = 1, duration: float = 0.5) -> None:
    """
    Perform drag gesture from start to end coordinates, optionally multiple times.
    
    Args:
        start: Starting (x, y) coordinate
        end: Ending (x, y) coordinate
        times: Number of times to repeat the drag
        duration: Duration of each drag movement in seconds
    """
    for i in range(times):
        x_start, y_start = add_jitter(*start)
        x_end, y_end = add_jitter(*end)
        
        if CONFIG["DEBUG"]:
            logger.info(f"[DEBUG] Would drag {i+1}/{times}: ({x_start}, {y_start}) -> ({x_end}, {y_end})")
        else:
            pyautogui.mouseDown(x_start, y_start)
            time.sleep(0.1)
            pyautogui.moveTo(x_end, y_end, duration=duration)
            pyautogui.mouseUp()
        
        logger.info(f"Drag {i+1}/{times} from {start} to {end}")
        time.sleep(random_interval())

def validate_templates() -> bool:
    """
    Validate that all required template files exist.
    Abort program if any are missing.
    
    Returns:
        bool: True if all templates found, exits program otherwise
    """
    logger.info("Validating templates...")
    
    script_dir = Path(__file__).parent
    required_templates = ["BBattack", "BBfind_match", "return_button", "end_battle", "okay_upgrade", "use_star_jar", "star_jar_accept"]
    missing = []
    
    for template_key in required_templates:
        template_filename = CONFIG.get(template_key)
        if not template_filename:
            missing.append(template_key)
            continue
        
        template_path = script_dir / template_filename
        if not template_path.exists():
            missing.append(str(template_path))
    
    if missing:
        logger.error(f"Missing template files: {missing}")
        logger.error("ABORTING PROGRAM")
        sys.exit(1)
    
    logger.info("✓ All templates found")
    return True

# ================================
# BUILDER BATTLE SESSION CLASS
# ================================
class BuilderBattleSession:
    """Encapsulates all mutable state for a Builder Base battle session."""

    def __init__(self):
        self.shutdown_requested = False
        self._last_failure_key = None
        self._same_failure_count = 0
        self._bbattack_fail_count = 0
        self.stats = {
            "battles_completed": 0,
            "total_stars": 0,
            "last_battle_stars": 0,
            "first_half_successes": 0,
            "start_time": time.time(),
            "star_counts": {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0},
        }
        self.space_listener = SpaceListener(session=self)

    def phase1_find_match(self) -> bool:
        """
        PHASE 1: Find and enter a match

        Step 1: Click "BBattack" button
        Step 2: Click "BBfind_match" button

        Returns:
            bool: True if successful, False otherwise
        """
        logger.info("=" * 60)
        logger.info("PHASE 1: FIND MATCH")
        logger.info("=" * 60)

        # Step 1: Click attack button
        if not search_and_click("BBattack", threshold=0.8):
            self._bbattack_fail_count += 1
            logger.error(f"Failed to find BBattack button ({self._bbattack_fail_count}/20)")
            if self._bbattack_fail_count >= 20:
                logger.warning("BBattack button missing 20 times in a row — performing hard reset")
                self._bbattack_fail_count = 0
                self.perform_hard_game_restart()
            return False

        self._bbattack_fail_count = 0
        time.sleep(0.2)

        # Check for star jar and use it if available
        logger.info("Checking for star jar...")
        if search_and_click("use_star_jar"):
            logger.info("Star jar found, clicking to use it")
            time.sleep(0.3)
            # Look for accept button
            if search_and_click("star_jar_accept"):
                logger.info("Star jar accepted successfully")
                time.sleep(0.3)
            else:
                logger.warning("Star jar accept button not found, continuing anyway")
        else:
            logger.info("No star jar available, continuing normally")

        # Step 2: Click find match button
        if not search_and_click("BBfind_match"):
            logger.error("Failed to find BBfind_match button")
            return False

        logger.info("✓ Phase 1 complete")
        return True

    def phase2_attack(self) -> bool:
        """
        PHASE 2: Execute attack sequence

        - Wait for in-battle indicator pixel to be purple
        - Execute deployment sequence
        - Deploy hero and manage hero ability
        - Monitor for battle end
        - Count stars
        - Return home and end battle

        Returns:
            bool: True if successful, False otherwise
        """
        logger.info("=" * 60)
        logger.info("PHASE 2: ATTACK")
        logger.info("=" * 60)

        battle_start_time = time.time()
        first_half_success_count = 0

        # Backup-mode timing: require this many continuous seconds of non-gray to trigger
        backup_nongray_start_time = None
        backup_required_seconds = 3.0  # seconds
        # Flag to avoid re-triggering same backup action
        backup_end_triggered = False

        # ========== WAIT FOR BATTLE TO START ==========
        logger.info("Waiting for battle to start (purple indicator pixel)...")
        if not wait_for_pixel(IN_BATTLE_PIXEL, CONFIG["PURPLE_RGB"], CONFIG["PURPLE_TOL"], 20.0):
            logger.error("Battle did not start (timeout waiting for purple pixel)")
            return False

        logger.info("✓ Battle started")

        # ========== DEPLOYMENT GESTURE ==========
        logger.info("Executing deployment gesture (drag from 1122,891 to 622,69)...")
        x_start, y_start = add_jitter(1122, 891)
        x_end, y_end = add_jitter(622, 69)

        time.sleep(1.0)

        if CONFIG["DEBUG"]:
            logger.info(f"[DEBUG] Would mouseDown({x_start}, {y_start}) -> moveTo({x_end}, {y_end}) -> mouseUp()")
        else:
            pyautogui.mouseDown(x_start, y_start)
            time.sleep(0.5)
            pyautogui.moveTo(x_end, y_end, duration=0.5)
            pyautogui.mouseUp()

        time.sleep(random_interval())

        # ========== FIRST CLICK ==========
        x, y = add_jitter(455, 986)
        if CONFIG["DEBUG"]:
            logger.info(f"[DEBUG] Would click(455, 986) at ({x}, {y})")
        else:
            smooth_click(x, y)
        logger.info(f"Clicked at (455, 986)")
        time.sleep(random_interval())

        # ========== DEPLOYMENT SEQUENCE ==========
        logger.info("Executing deployment sequence...")
        for i, (orig_x, orig_y) in enumerate(DEPLOY_SEQUENCE):
            x, y = add_jitter(orig_x, orig_y)

            if CONFIG["DEBUG"]:
                logger.info(f"[DEBUG] Deploy click {i+1}/6: Would click({orig_x}, {orig_y}) at ({x}, {y})")
            else:
                smooth_click(x, y)

            logger.info(f"Deploy click {i+1}/6 at ({orig_x}, {orig_y})")
            time.sleep(random_interval())

        # ========== HERO DEPLOYMENT ==========
        logger.info("Deploying hero...")
        for i, (orig_x, orig_y) in enumerate(HERO_DEPLOY):
            x, y = add_jitter(orig_x, orig_y)

            if CONFIG["DEBUG"]:
                logger.info(f"[DEBUG] Hero click {i+1}/2: Would click({orig_x}, {orig_y}) at ({x}, {y})")
            else:
                smooth_click(x, y)

            logger.info(f"Hero click {i+1}/2 at ({orig_x}, {orig_y})")
            time.sleep(random_interval())

        # ========== BATTLE WATCH LOOP ==========
        logger.info("Entering battle watch loop...")
        battle_over = False
        backup_mode_activated = False
        second_half_started = False
        second_half_attempted = False

        # State tracking to reduce repetitive logging
        prev_hero_ability_available = False
        prev_star_orange_count = 0
        prev_button_pixel_is_gray = True
        prev_return_button_found = False

        while not battle_over:
            # Check for timeout
            elapsed = time.time() - battle_start_time
            if elapsed > CONFIG["BATTLE_TIMEOUT"]:
                logger.error(f"BATTLE TIMEOUT EXCEEDED ({elapsed:.1f}s > {CONFIG['BATTLE_TIMEOUT']}s)")
                logger.error("Battle timed out — performing hard game restart and continuing...")
                self.perform_hard_game_restart()
                return False

            # Get current screenshot
            pil_img = screenshot_pil()

            # Check for hero ability activation (purple pixel at hero ability location)
            hero_ability_available = pixel_is_close(pil_img, HERO_ABILITY_PIXEL, CONFIG["PURPLE_RGB"], CONFIG["PURPLE_TOL"])

            if hero_ability_available and not prev_hero_ability_available:
                logger.info("Hero ability available - activating...")
                x, y = add_jitter(324, 982)

                if CONFIG["DEBUG"]:
                    logger.info(f"[DEBUG] Would click hero ability at ({x}, {y})")
                else:
                    smooth_click(x, y)

                time.sleep(random_interval())

            prev_hero_ability_available = hero_ability_available

            # Check for first-half success (all 3 orange pixels)
            first_half_orange_count = 0
            for pixel_coord in FIRST_HALF_PIXELS:
                if pixel_is_close(pil_img, pixel_coord, CONFIG["ORANGE_RGB"], CONFIG["ORANGE_TOL"]):
                    first_half_orange_count += 1

            # Check current star count (needed for second-half decision)
            star_orange_count = 0
            for pixel_coord in STAR_PIXELS:
                if pixel_is_close(pil_img, pixel_coord, CONFIG["ORANGE_RGB"], CONFIG["ORANGE_TOL"]):
                    star_orange_count += 1

            # First-half success handling - ALWAYS do second-half
            if first_half_orange_count == 3 and not second_half_attempted:
                second_half_attempted = True
                logger.info("✓ First-half WON - starting second-half routine!")

                # Wait 5 seconds before proceeding to second-half
                logger.info("Waiting 5 seconds before second-half deployment...")
                time.sleep(5.0)

                # Wait for stars to disappear
                if not wait_until_stars_not_orange(timeout=45.0):
                    logger.warning("Stars didn't disappear, proceeding anyway...")

                # Second-half deployment sequence
                logger.info("=== SECOND HALF DEPLOYMENT ===")

                # Drag gesture twice
                logger.info("Performing deployment drag gesture (2x)...")
                perform_drag(SECOND_HALF_DRAG_START, SECOND_HALF_DRAG_END, times=2, duration=0.5)

                # Click troop select by template (30 px above detected icon)
                troop_select_coords = None
                for attempt in range(1, 6):
                    cv_img = screenshot_cv()
                    troop_select_coords = find_template(
                        cv_img,
                        SECOND_HALF_TROOP_TEMPLATE,
                        CONFIG["TEMPLATE_THRESH_DEFAULT"],
                        log_not_found=False,
                    )
                    if troop_select_coords:
                        break
                    logger.debug(
                        f"Second-half troop template not found (attempt {attempt}/5): {SECOND_HALF_TROOP_TEMPLATE}"
                    )
                    time.sleep(0.4)

                if not troop_select_coords:
                    logger.warning(
                        f"Failed to find second-half troop template after retries: {SECOND_HALF_TROOP_TEMPLATE}"
                    )
                    logger.warning(
                        "Skipping second-half deployment for this battle; waiting for return button until battle timeout"
                    )
                    continue

                troop_click_x = int(troop_select_coords[0])
                troop_click_y = int(troop_select_coords[1] + SECOND_HALF_TROOP_CLICK_OFFSET_Y)
                x, y = add_jitter(troop_click_x, troop_click_y)
                if CONFIG["DEBUG"]:
                    logger.info(f"[DEBUG] Would click second-half troop select at ({x}, {y})")
                else:
                    smooth_click(x, y)
                logger.info(
                    f"Clicked second-half troop select at ({troop_click_x}, {troop_click_y}) from template {SECOND_HALF_TROOP_TEMPLATE}"
                )
                time.sleep(random_interval())

                # Deploy troops at all points
                logger.info("Deploying second-half troops...")
                for i, (orig_x, orig_y) in enumerate(SECOND_HALF_DEPLOY_POINTS):
                    x, y = add_jitter(orig_x, orig_y)
                    if CONFIG["DEBUG"]:
                        logger.info(f"[DEBUG] Would click deploy point {i+1}/{len(SECOND_HALF_DEPLOY_POINTS)} at ({x}, {y})")
                    else:
                        smooth_click(x, y)
                    logger.info(f"Second-half deploy {i+1}/{len(SECOND_HALF_DEPLOY_POINTS)} at ({orig_x}, {orig_y})")
                    time.sleep(random_interval())

                # Click hero icon
                x, y = add_jitter(*HERO_ICON_PIXEL)
                if CONFIG["DEBUG"]:
                    logger.info(f"[DEBUG] Would click hero icon at ({x}, {y})")
                else:
                    smooth_click(x, y)
                logger.info(f"Clicked hero icon at {HERO_ICON_PIXEL}")
                time.sleep(random_interval())

                # Click hero second deployment location
                x, y = add_jitter(*HERO_SECOND_CLICK)
                if CONFIG["DEBUG"]:
                    logger.info(f"[DEBUG] Would click hero deployment at ({x}, {y})")
                else:
                    smooth_click(x, y)
                logger.info(f"Clicked hero deployment at {HERO_SECOND_CLICK}")
                time.sleep(random_interval())

                second_half_started = True
                first_half_success_count += 1
                logger.info("✓ Second-half deployment complete - continuing battle watch")

            # Check for 2-star success (2 out of 3 stars orange AND button pixel is gray - activates backup mode)
            # (Recompute star_orange_count only if not already done above - but we already did it, so use existing value)

            # Check if button pixel (1684, 819) is gray (224, 224, 224)
            button_pixel_is_gray = pixel_is_close(pil_img, (1684, 819), (224, 224, 224), 20)

            # Log star count and button pixel state changes
            if star_orange_count != prev_star_orange_count:
                logger.debug(f"Star count changed: {prev_star_orange_count} -> {star_orange_count} orange")
            if button_pixel_is_gray != prev_button_pixel_is_gray:
                logger.debug(f"Button pixel changed: {'gray' if prev_button_pixel_is_gray else 'non-gray'} -> {'gray' if button_pixel_is_gray else 'non-gray'}")

            prev_star_orange_count = star_orange_count
            prev_button_pixel_is_gray = button_pixel_is_gray

            # Activate backup mode when 2+ stars and pixel is gray
            if not backup_mode_activated and star_orange_count >= 2 and button_pixel_is_gray:
                logger.info(f"✓ BACKUP MODE ACTIVATED: {star_orange_count}/3 stars orange and button pixel is gray")
                backup_mode_activated = True

            # -----------------------
            # Backup mode (time-based)
            # Trigger: button pixel stays non-gray for backup_required_seconds
            # -----------------------
            if backup_mode_activated and not backup_end_triggered:
                # If button pixel is non-gray, start or continue timer
                if not button_pixel_is_gray:
                    if backup_nongray_start_time is None:
                        backup_nongray_start_time = time.time()
                        logger.debug(
                            f"Backup mode: pixel became non-gray -> start timer at {backup_nongray_start_time:.3f}"
                        )
                    else:
                        elapsed = time.time() - backup_nongray_start_time
                        logger.debug(
                            f"Backup mode: pixel non-gray for {elapsed:.2f}s (need {backup_required_seconds:.1f}s)"
                        )
                        if elapsed >= backup_required_seconds:
                            logger.info(
                                f"✔ BACKUP TRIGGER: button pixel non-gray for {elapsed:.1f}s (>= {backup_required_seconds:.1f}s) — ending first-half"
                            )
                            # Existing behavior: click the end_battle / okay_upgrade and mark first-half success
                            if search_and_click("end_battle"):
                                time.sleep(random_interval())
                            if search_and_click("okay_upgrade"):
                                time.sleep(random_interval())

                            first_half_success_count += 1
                            backup_end_triggered = True
                else:
                    # Pixel returned to gray: reset timer
                    if backup_nongray_start_time is not None:
                        logger.debug(
                            f"Backup mode: pixel returned to gray after {time.time() - backup_nongray_start_time:.2f}s -> resetting timer"
                        )
                    backup_nongray_start_time = None

            # Check for return button (battle end)
            cv_img = screenshot_cv()
            return_button_found = find_template(cv_img, CONFIG["return_button"], CONFIG["TEMPLATE_THRESH_DEFAULT"], log_not_found=False) is not None

            # Only log when return button state changes
            if return_button_found != prev_return_button_found:
                if return_button_found:
                    logger.info("✓ Return button detected - battle ending")
                    battle_over = True
                else:
                    logger.debug("Return button no longer detected")
            elif return_button_found:
                battle_over = True

            prev_return_button_found = return_button_found

            # Sleep before next check (faster polling in backup mode for responsiveness)
            poll_interval = CONFIG["HERO_CHECK_INTERVAL"]
            if backup_mode_activated and not backup_end_triggered:
                poll_interval = min(poll_interval, 0.25)
            time.sleep(poll_interval)

        time.sleep(2.0)  # Wait 2 seconds for stars to appear after button found


        # ========== STAR COUNTING ==========
        logger.info("Counting stars...")
        pil_img = screenshot_pil()

        # Count stars based on whether second-half was played
        if second_half_started:
            # Second-half: check for blue stars (168,199,214) and add 3
            blue_star_count = 0
            for star_pixel in SECOND_HALF_STAR_PIXELS:
                pixel_rgb = pil_img.getpixel(star_pixel)
                if pixel_is_close(pil_img, star_pixel, SECOND_HALF_STAR_RGB, SECOND_HALF_STAR_TOL):
                    blue_star_count += 1
                    logger.info(f"✓ Second-half star pixel {star_pixel} is blue (RGB: {pixel_rgb})")
                else:
                    logger.info(f"✗ Second-half star pixel {star_pixel} is not blue (RGB: {pixel_rgb})")
            stars_this_battle = 3 + blue_star_count
            logger.info(f"Second-half battle: {blue_star_count} blue stars → Total: {stars_this_battle} stars")
        else:
            # Normal first-half only: check orange stars (0-3)
            stars_this_battle = 0
            for star_pixel in STAR_PIXELS:
                if pixel_is_close(pil_img, star_pixel, CONFIG["ORANGE_RGB"], CONFIG["ORANGE_TOL"]):
                    stars_this_battle += 1
                    logger.info(f"✓ Star pixel {star_pixel} is orange")
                else:
                    logger.info(f"✗ Star pixel {star_pixel} is not orange")
            logger.info(f"First-half only: {stars_this_battle} orange stars")

        logger.info(f"Stars this battle: {stars_this_battle}")
        self.stats["last_battle_stars"] = stars_this_battle
        self.stats["total_stars"] += stars_this_battle

        # Track star breakdown (0-6 range for second-half support)
        logger.debug(f"Updating star_counts[{stars_this_battle}] from {self.stats['star_counts'][stars_this_battle]} to {self.stats['star_counts'][stars_this_battle] + 1}")
        if 0 <= stars_this_battle <= 6:
            self.stats["star_counts"][stars_this_battle] += 1
            logger.info(f"✓ Updated star_counts: {self.stats['star_counts']}")
        else:
            logger.warning(f"Star count {stars_this_battle} is out of range [0-6]! Not updating breakdown.")

        # ========== RETURN HOME AND END BATTLE ==========
        logger.info("Returning home and ending battle...")

        # Find and click return button with 2 second wait after being found
        if search_and_click("return_button"):
            time.sleep(2.0)  # Wait 2 seconds for stars to appear after button found
            time.sleep(random_interval())

        # Sleep for UI animations
        time.sleep(3)

        # Click okay_upgrade if present
        if search_and_click("okay_upgrade"):
            time.sleep(random_interval())

        # End battle gestures (exact order and coordinates)
        logger.info("Executing end-battle gestures...")

        # Gesture 1: mouseDown(1089,112) -> moveTo(1012,363) -> mouseUp()
        x_start, y_start = add_jitter(1089, 112)
        x_end, y_end = add_jitter(1012, 363)

        if CONFIG["DEBUG"]:
            logger.info(f"[DEBUG] Would mouseDown({x_start}, {y_start}) -> moveTo({x_end}, {y_end}) -> mouseUp()")
        else:
            pyautogui.mouseDown(x_start, y_start)
            time.sleep(0.1)
            pyautogui.moveTo(x_end, y_end, duration=0.3)
            pyautogui.mouseUp()

        time.sleep(random_interval())

        # Gesture 2: click(1247,124)
        x, y = add_jitter(1247, 124)
        if CONFIG["DEBUG"]:
            logger.info(f"[DEBUG] Would click(1247, 124) at ({x}, {y})")
        else:
            smooth_click(x, y)
        logger.info("End gesture 2")
        time.sleep(random_interval())

        # Gesture 3: click(1399,913)
        x, y = add_jitter(1399, 913)
        if CONFIG["DEBUG"]:
            logger.info(f"[DEBUG] Would click(1399, 913) at ({x}, {y})")
        else:
            smooth_click(x, y)
        logger.info("End gesture 3")
        time.sleep(random_interval())

        # Gesture 4: click(1621,102)
        x, y = add_jitter(1621, 102)
        if CONFIG["DEBUG"]:
            logger.info(f"[DEBUG] Would click(1621, 102) at ({x}, {y})")
        else:
            smooth_click(x, y)
        logger.info("End gesture 4")
        time.sleep(random_interval())

        logger.info("✓ Phase 2 complete")
        return True


    # ================================
    # MAIN LOOP
    # ================================

    def reset_failure_watchdog(self) -> None:
        """Reset repeated-failure tracking."""
        self._last_failure_key = None
        self._same_failure_count = 0

    def register_failure(self, failure_key: str) -> int:
        """Track repeated failures by key and return same-key streak count."""
        key = (failure_key or "unknown").strip().lower()
        if key == self._last_failure_key:
            self._same_failure_count += 1
        else:
            self._last_failure_key = key
            self._same_failure_count = 1
        return self._same_failure_count

    def scan_and_click_known_error_templates(self) -> bool:
        """Check known error popups/buttons and click one if found."""
        templates_to_try = [
            (CONFIG.get("return_home_button"), "return_home"),
            (CONFIG.get("account_load_okay"), "account_load_okay"),
            (CONFIG.get("try_again_button"), "try_again_button"),
            (CONFIG.get("reload_game_button"), "reload_game"),
        ]

        cv_img = screenshot_cv()
        for template_name, label in templates_to_try:
            if not template_name:
                continue
            coords = find_template(
                cv_img,
                template_name,
                CONFIG["TEMPLATE_THRESH_DEFAULT"],
                log_not_found=False,
            )
            if coords:
                x, y = coords
                x_jit, y_jit = add_jitter(x, y)
                if CONFIG["DEBUG"]:
                    logger.info(f"[DEBUG] Would click recovery template '{label}' at ({x_jit}, {y_jit})")
                else:
                    smooth_click(x_jit, y_jit)
                logger.warning(f"Recovery: detected {label}; clicked to recover")
                time.sleep(2)
                return True

        return False

    def perform_hard_game_restart(self) -> None:
        """Hard-close and relaunch game via fixed coordinates."""
        logger.warning("Recovery: no known error popup found; performing hard game restart")
        close_x, close_y = CONFIG["HARD_RESET_CLOSE_COORD"]
        relaunch_x, relaunch_y = CONFIG["HARD_RESET_RELAUNCH_COORD"]
        post_x, post_y = CONFIG["HARD_RESET_POST_LAUNCH_COORD"]

        pyautogui.hotkey('alt', 'f4')  # Close game window
        # Backup (old click-to-close): _click_direct(close_x, close_y, "hard-close")
        time.sleep(5)

        if CONFIG["DEBUG"]:
            logger.info(f"[DEBUG] Would doubleClick relaunch at ({relaunch_x}, {relaunch_y})")
        else:
            pyautogui.doubleClick(relaunch_x, relaunch_y, interval=0.2)

        # Backup (old post-launch click): _click_direct(post_x, post_y, "post-launch")
        time.sleep(20)

    def handle_repeated_failure(self, failure_key: str, action_label: str = "Recovery") -> bool:
        """Run full recovery when same failure repeats beyond threshold."""
        count = self.register_failure(failure_key)
        threshold = int(CONFIG.get("FAILURE_RECOVERY_THRESHOLD", 100))
        if count < threshold:
            return False

        logger.warning(
            f"{action_label}: '{failure_key}' failed {count} times. Running full error recovery..."
        )
        self.reset_failure_watchdog()

        if self.scan_and_click_known_error_templates():
            logger.warning(f"{action_label}: recovered via detected popup; retrying process")
            time.sleep(2)
            return True

        self.perform_hard_game_restart()
        logger.warning(f"{action_label}: game restarted; retrying process")
        return True

    def main(self):
        """
        Main automation loop.

        - Validate templates
        - Loop until MAX_BATTLES reached or user interrupts
        - Execute Phase 1 (find match) and Phase 2 (attack) for each battle
        - Report stats on exit
        """
        logger.info("=" * 60)
        logger.info("CLASH OF CLANS BUILDER BASE AUTOMATION")
        logger.info("=" * 60)
        logger.info(f"DEBUG MODE: {CONFIG['DEBUG']}")
        logger.info(f"MAX BATTLES: {CONFIG['MAX_BATTLES']}")
        logger.info(f"BATTLE TIMEOUT: {CONFIG['BATTLE_TIMEOUT']}s")
        logger.info("=" * 60)

        # Start Space key listener
        self.space_listener.start()

        # Validate templates
        validate_templates()
        self.reset_failure_watchdog()

        # Main loop
        try:
            battle_num = 0

            while True:
                battle_num += 1

                # Check if max battles reached
                if CONFIG["MAX_BATTLES"] is not None and battle_num > CONFIG["MAX_BATTLES"]:
                    logger.info(f"MAX_BATTLES ({CONFIG['MAX_BATTLES']}) reached")
                    break

                # Check for shutdown request
                if self.shutdown_requested:
                    logger.info("Shutdown requested")
                    break

                logger.info(f"\n{'='*60}")
                logger.info(f"BATTLE {battle_num}")
                logger.info(f"{'='*60}")

                # Opportunistic popup recovery before phase execution
                if self.scan_and_click_known_error_templates():
                    logger.warning("Recovered pre-battle popup; retrying battle loop")
                    time.sleep(2)
                    continue

                # Phase 1: Find match
                if not self.phase1_find_match():
                    self.handle_repeated_failure("bb.phase1.find_match", action_label="Phase 1")
                    logger.warning("Phase 1 failed, retrying in 3 seconds...")
                    time.sleep(3)
                    continue

                time.sleep(1)

                # Phase 2: Attack
                if self.phase2_attack():
                    self.stats["battles_completed"] = battle_num
                    self.reset_failure_watchdog()
                    logger.info(f"✓ Battle {battle_num} complete (stars: {self.stats['last_battle_stars']})")
                else:
                    self.handle_repeated_failure("bb.phase2.attack", action_label="Phase 2")
                    logger.warning(f"✗ Battle {battle_num} failed")

                time.sleep(2)

        except KeyboardInterrupt:
            logger.info("\nKeyboard interrupt - shutting down...")

        except Exception as e:
            self.handle_repeated_failure("bb.main.exception", action_label="Error")
            logger.error(f"Unexpected error: {e}", exc_info=True)

        finally:
            # Stop space listener
            self.space_listener.stop()

            # Print final self.stats
            elapsed_minutes = (time.time() - self.stats["start_time"]) / 60.0
            logger.info("\n" + "=" * 60)
            logger.info("FINAL STATISTICS")
            logger.info("=" * 60)
            logger.info(f"Battles completed: {self.stats['battles_completed']}")
            logger.info(f"Total stars earned: {self.stats['total_stars']}")
            logger.info(f"Average stars per battle: {self.stats['total_stars'] / max(self.stats['battles_completed'], 1):.2f}")
            logger.info(f"First-half successes: {self.stats['first_half_successes']}")
            logger.info(f"Runtime: {elapsed_minutes:.1f} minutes")
            logger.info("=" * 60)
            logger.info("SCRIPT TERMINATED")


# ================================
# BACKWARD-COMPATIBLE MODULE-LEVEL ALIASES
# ================================
_default_session: BuilderBattleSession = BuilderBattleSession()

def _compat_phase1_find_match(*a, **kw):
    return _default_session.phase1_find_match(*a, **kw)
phase1_find_match = _compat_phase1_find_match

def _compat_phase2_attack(*a, **kw):
    return _default_session.phase2_attack(*a, **kw)
phase2_attack = _compat_phase2_attack

def _compat_reset_failure_watchdog(*a, **kw):
    return _default_session.reset_failure_watchdog(*a, **kw)
reset_failure_watchdog = _compat_reset_failure_watchdog

def _compat_register_failure(*a, **kw):
    return _default_session.register_failure(*a, **kw)
register_failure = _compat_register_failure

def _compat_scan_and_click_known_error_templates(*a, **kw):
    return _default_session.scan_and_click_known_error_templates(*a, **kw)
scan_and_click_known_error_templates = _compat_scan_and_click_known_error_templates

def _compat_perform_hard_game_restart(*a, **kw):
    return _default_session.perform_hard_game_restart(*a, **kw)
perform_hard_game_restart = _compat_perform_hard_game_restart

def _compat_handle_repeated_failure(*a, **kw):
    return _default_session.handle_repeated_failure(*a, **kw)
handle_repeated_failure = _compat_handle_repeated_failure

def _compat_main(*a, **kw):
    return _default_session.main(*a, **kw)
main = _compat_main

# State aliases for backward compat
shutdown_requested = _default_session.shutdown_requested  # snapshot; prefer _default_session.shutdown_requested
stats = _default_session.stats
space_listener = _default_session.space_listener


if __name__ == "__main__":
    # Check for --dry-run flag
    if "--dry-run" in sys.argv or "--debug" in sys.argv:
        CONFIG["DEBUG"] = True
        logger.info("Running in DEBUG mode (no clicks)")

    _default_session.main()
