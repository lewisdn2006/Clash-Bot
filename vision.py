#!/usr/bin/env python3
"""
Shared computer vision utilities for Clash of Clans bot automation.
==================================================================

Provides core template-matching functions used by both Autoclash.py and
Autoclash_BB.py, eliminating duplicate implementations.

All public functions are stateless and side-effect free (no logging, no clicks).
Callers are responsible for logging and acting on results.
"""

import cv2
import numpy as np
import pyautogui
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Tuple, List, Union

from PIL import Image


def safe_screenshot(region=None) -> Image.Image:
    """Take a screenshot with retry logic. Retries up to 10 times with 5s delays.
    If all attempts fail, kills all running Python processes and exits.
    """
    max_attempts = 10
    for attempt in range(1, max_attempts + 1):
        try:
            if region is not None:
                return pyautogui.screenshot(region=region)
            return pyautogui.screenshot()
        except Exception as exc:
            print(f"[safe_screenshot] Attempt {attempt}/{max_attempts} failed: {exc}")
            if attempt < max_attempts:
                print(f"[safe_screenshot] Retrying in 5 seconds...")
                time.sleep(5)
    print("[safe_screenshot] All 10 attempts failed. Shutting down all Python processes.")
    subprocess.run(["taskkill", "/F", "/IM", "python.exe"], capture_output=True)
    subprocess.run(["taskkill", "/F", "/IM", "pythonw.exe"], capture_output=True)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def resolve_template_path(
    template_name: str,
    base_dir: Union[str, Path, None] = None,
) -> Path:
    """Resolve a template filename to an absolute path.

    Args:
        template_name: Filename (or relative path) of the template image.
        base_dir: Directory that contains templates.
                  *None* defaults to the directory of **this** file.
    """
    if base_dir is None:
        base_dir = Path(__file__).parent
    return Path(base_dir) / template_name


def load_template_gray(template_path: Union[str, Path]) -> Optional[np.ndarray]:
    """Load a template image file and return it as a grayscale numpy array.

    Returns *None* if the file cannot be read.
    """
    img = cv2.imread(str(template_path), cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    if len(img.shape) == 3:
        if img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
        else:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img


def prepare_screenshot_gray(
    screenshot: Union[Image.Image, np.ndarray, None] = None,
    region: Optional[Tuple[int, int, int, int]] = None,
    bgr: bool = False,
) -> Tuple[np.ndarray, int, int]:
    """Capture or crop a screenshot and convert to grayscale.

    Args:
        screenshot: Existing screenshot (PIL Image **or** numpy array), or
                    *None* to capture a fresh one via pyautogui.
        region: Optional crop region as *(x1, y1, x2, y2)*.
        bgr: Set *True* when *screenshot* is a **BGR** numpy array
             (e.g. from ``cv2``).  PIL images are always treated as RGB
             regardless of this flag.

    Returns:
        ``(grayscale_array, offset_x, offset_y)`` where offsets account
        for the crop region.
    """
    offset_x, offset_y = 0, 0
    is_pil = isinstance(screenshot, Image.Image)

    if region is not None:
        x1, y1, x2, y2 = region
        if screenshot is None:
            screenshot = safe_screenshot(region=(x1, y1, x2 - x1, y2 - y1))
            is_pil = True
        elif is_pil:
            screenshot = screenshot.crop((x1, y1, x2, y2))
        else:
            screenshot = screenshot[y1:y2, x1:x2]
        offset_x, offset_y = x1, y1
    elif screenshot is None:
        screenshot = safe_screenshot()
        is_pil = True

    arr = np.array(screenshot) if is_pil else screenshot

    if len(arr.shape) == 2:
        return arr, offset_x, offset_y

    # PIL images are always RGB; only honour *bgr* for raw numpy arrays.
    use_bgr = bgr and not is_pil

    if arr.shape[2] == 4:
        gray = cv2.cvtColor(arr, cv2.COLOR_BGRA2GRAY if use_bgr else cv2.COLOR_RGBA2GRAY)
    else:
        gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY if use_bgr else cv2.COLOR_RGB2GRAY)

    return gray, offset_x, offset_y


# ---------------------------------------------------------------------------
# High-level template matching
# ---------------------------------------------------------------------------

def find_template(
    template_path: Union[str, Path],
    threshold: float = 0.75,
    screenshot: Union[Image.Image, np.ndarray, None] = None,
    region: Optional[Tuple[int, int, int, int]] = None,
    find_mode: str = "best",
    bgr: bool = False,
) -> Tuple[Optional[Tuple[int, int]], float]:
    """Find a single template on screen using OpenCV template matching.

    Args:
        template_path: Path to the template image file.
        threshold: Match confidence threshold (0-1).
        screenshot: Pre-captured screenshot, or *None* to capture.
        region: Optional search region as *(x1, y1, x2, y2)*.
        find_mode: ``"best"`` (highest confidence), ``"rightmost"``, or
                   ``"leftmost"``.
        bgr: *True* if *screenshot* is a BGR numpy array.

    Returns:
        ``(coords, confidence)`` where *coords* is ``(x, y)`` or *None*,
        and *confidence* is the best match score.
    """
    template = load_template_gray(Path(template_path))
    if template is None:
        return None, 0.0

    gray, offset_x, offset_y = prepare_screenshot_gray(screenshot, region, bgr=bgr)
    result = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
    template_h, template_w = template.shape[:2]

    if find_mode in ("rightmost", "leftmost"):
        locations = np.where(result >= threshold)
        if len(locations[0]) == 0:
            return None, max_val
        matches = list(zip(locations[1], locations[0]))
        selected = (max if find_mode == "rightmost" else min)(
            matches, key=lambda m: m[0]
        )
        center_x = selected[0] + template_w // 2 + offset_x
        center_y = selected[1] + template_h // 2 + offset_y
        return (center_x, center_y), max_val

    # Default: best match
    if max_val >= threshold:
        center_x = max_loc[0] + template_w // 2 + offset_x
        center_y = max_loc[1] + template_h // 2 + offset_y
        return (center_x, center_y), max_val
    return None, max_val


def find_all_templates(
    template_path: Union[str, Path],
    threshold: float = 0.75,
    screenshot: Union[Image.Image, np.ndarray, None] = None,
    region: Optional[Tuple[int, int, int, int]] = None,
    min_separation: Optional[int] = None,
    bgr: bool = False,
) -> List[Tuple[int, int]]:
    """Find **all** instances of a template with overlap deduplication.

    Args:
        template_path: Path to the template image file.
        threshold: Match confidence threshold.
        screenshot: Pre-captured screenshot or *None*.
        region: Optional search region as *(x1, y1, x2, y2)*.
        min_separation: Min pixel distance between matches for dedup.
                        Defaults to half the smaller template dimension.
        bgr: *True* if *screenshot* is BGR.

    Returns:
        List of ``(x, y)`` centre coordinates, highest-confidence first.
    """
    template = load_template_gray(Path(template_path))
    if template is None:
        return []

    gray, offset_x, offset_y = prepare_screenshot_gray(screenshot, region, bgr=bgr)
    result_map = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
    template_h, template_w = template.shape[:2]

    ys, xs = np.where(result_map >= threshold)
    if len(xs) == 0:
        return []

    candidates = sorted(
        [
            (
                int(x + template_w // 2 + offset_x),
                int(y + template_h // 2 + offset_y),
                float(result_map[y, x]),
            )
            for x, y in zip(xs.tolist(), ys.tolist())
        ],
        key=lambda c: c[2],
        reverse=True,
    )

    if min_separation is None:
        min_separation = max(14, int(min(template_w, template_h) * 0.5))

    deduped: List[Tuple[int, int]] = []
    for cx, cy, _ in candidates:
        if not any(
            ((cx - ex) ** 2 + (cy - ey) ** 2) ** 0.5 < min_separation
            for ex, ey in deduped
        ):
            deduped.append((cx, cy))
    return deduped


def find_template_with_clusters(
    template_path: Union[str, Path],
    threshold: float = 0.75,
    screenshot: Union[Image.Image, np.ndarray, None] = None,
    region: Optional[Tuple[int, int, int, int]] = None,
    pick: str = "rightmost",
    cluster_threshold: int = 150,
    bgr: bool = False,
) -> Tuple[Optional[Tuple[int, int]], int, int]:
    """Find template matches, cluster them spatially, and pick one.

    Args:
        template_path: Path to the template image file.
        threshold: Match confidence threshold.
        screenshot: Pre-captured screenshot or *None*.
        region: Optional search region as *(x1, y1, x2, y2)*.
        pick: ``"rightmost"`` or ``"leftmost"`` match to select.
        cluster_threshold: Max x-distance (pixels) for same-cluster grouping.
        bgr: *True* if *screenshot* is BGR.

    Returns:
        ``(selected_coords, raw_match_count, distinct_cluster_count)``.
        *selected_coords* is *None* if no matches.
    """
    template = load_template_gray(Path(template_path))
    if template is None:
        return None, 0, 0

    gray, offset_x, offset_y = prepare_screenshot_gray(screenshot, region, bgr=bgr)
    result_map = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
    template_h, template_w = template.shape[:2]
    locations = np.where(result_map >= threshold)

    if len(locations[0]) == 0:
        return None, 0, 0

    matches = list(zip(locations[1], locations[0]))
    centres = [
        (x + template_w // 2 + offset_x, y + template_h // 2 + offset_y)
        for x, y in matches
    ]

    # Cluster by x-coordinate
    clusters: List[List[Tuple[int, int]]] = []
    for cx, cy in sorted(centres, key=lambda m: m[0]):
        assigned = False
        for cluster in clusters:
            if any(abs(cx - ex) < cluster_threshold for ex, _ in cluster):
                cluster.append((cx, cy))
                assigned = True
                break
        if not assigned:
            clusters.append([(cx, cy)])

    selected = (min if pick == "leftmost" else max)(centres, key=lambda m: m[0])
    return selected, len(matches), len(clusters)
