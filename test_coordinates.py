#!/usr/bin/env python3
"""
test_coordinates.py — Overlay tool for verifying hardcoded screen coordinates.

Controls:
  SPACE  → next coordinate
  B      → previous coordinate
  Escape → quit

Draws a visual marker on screen for each coordinate:
  Point  (red)  — crosshair + circle
  Region (green) — filled rectangle + centre dot
  Drag   (cyan)  — arrow from start to end with labels

Note: Run as Administrator if the keyboard module fails to capture hotkeys.
"""

import sys
import math

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt, Signal, QObject, QPoint, QRect
from PySide6.QtGui import QPainter, QPen, QColor, QFont, QBrush

try:
    import keyboard
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False
    print("WARNING: 'keyboard' module not available — install with: pip install keyboard")


# ─────────────────────────────────────────────────────────────────────────────
# Thread-safe signal bridge (keyboard callbacks run in a background thread)
# ─────────────────────────────────────────────────────────────────────────────

class _Bridge(QObject):
    next_sig = Signal()
    prev_sig = Signal()
    quit_sig = Signal()

_bridge = _Bridge()


# ─────────────────────────────────────────────────────────────────────────────
# Coordinate data
# ─────────────────────────────────────────────────────────────────────────────

ENTRIES = []   # list of dicts: {file, name, desc, type, value}

def _pt(file, name, desc, value):
    """Add a single point (x, y)."""
    ENTRIES.append({"file": file, "name": name, "desc": desc, "type": "point", "value": value})

def _reg(file, name, desc, value):
    """Add a region (x1, y1, x2, y2)."""
    ENTRIES.append({"file": file, "name": name, "desc": desc, "type": "region", "value": value})

def _drag(file, name, desc, value):
    """Add a drag ((x1,y1), (x2,y2))."""
    ENTRIES.append({"file": file, "name": name, "desc": desc, "type": "drag", "value": value})

def _pts(file, name, desc, points):
    """Expand a list of points into individual entries."""
    n = len(points)
    for i, pt in enumerate(points):
        _pt(file, f"{name} [{i+1}/{n}]", desc, pt)


# ══════════════════════════════════════════════════════════════════════════════
# Autoclash.py
# ══════════════════════════════════════════════════════════════════════════════

_reg("Autoclash.py", "search_region",
     "Air defense template region (Phase 2B)",
     (289, 36, 1566, 902))

_reg("Autoclash.py", "clan_games_challenge_region",
     "Clan games challenge scan region",
     (622, 180, 1732, 847))

_pts("Autoclash.py", "ten_battle_points",
     "Dragon/troop deployment points",
     [(490, 768), (403, 694), (188, 530), (241, 442), (421, 312),
      (583, 188), (748, 74), (1228, 109), (1340, 193), (1477, 304)])

_pt("Autoclash.py", "abilities_click_coord",
    "Hero ability keys click target",
    (641, 144))

_reg("Autoclash.py", "more_box",
     "Phase 4 'More' button search region",
     (505, 893, 1288, 958))

_reg("Autoclash.py", "add_box",
     "Phase 4 'Add' button search region",
     (733, 880, 955, 936))

_reg("Autoclash.py", "remove_box",
     "Phase 4 'Remove' button search region",
     (500, 880, 707, 930))

_reg("Autoclash.py", "upgrade_box_gold",
     "Phase 4 gold upgrade button region",
     (977, 880, 1188, 936))

_reg("Autoclash.py", "upgrade_box_elixir",
     "Phase 4 elixir upgrade button region",
     (1133, 880, 1344, 936))

_reg("Autoclash.py", "upgrade_box_gold_alt",
     "Phase 4 gold upgrade (alt) region",
     (977, 891, 1188, 936))

_reg("Autoclash.py", "upgrade_box_elixir_alt",
     "Phase 4 elixir upgrade (alt) region",
     (1133, 891, 1344, 936))

_pts("Autoclash.py", "gold_pixel_set",
     "Gold upgrade trigger pixels",
     [(1075, 816), (1057, 816), (1075, 821), (1154, 816), (1155, 821)])

_pts("Autoclash.py", "elixir_pixel_set",
     "Elixir upgrade trigger pixels",
     [(1233, 816), (1215, 816), (1233, 821), (1312, 816), (1313, 821)])

_pts("Autoclash.py", "alternate_pixel_set",
     "Alternate upgrade trigger pixels",
     [(758, 900), (763, 908), (778, 907), (838, 900), (842, 909), (874, 908)])

_reg("Autoclash.py", "gold_region",
     "End-battle gold OCR region",
     (754, 448, 986, 503))

_reg("Autoclash.py", "elixir_region",
     "End-battle elixir OCR region",
     (754, 521, 986, 577))

_reg("Autoclash.py", "dark_elixir_region",
     "End-battle dark elixir OCR region",
     (816, 590, 986, 646))

_reg("Autoclash.py", "additional_gold_region",
     "Star-bonus gold OCR region",
     (1252, 539, 1404, 584))

_reg("Autoclash.py", "additional_elixir_region",
     "Star-bonus elixir OCR region",
     (1249, 593, 1405, 644))

_reg("Autoclash.py", "additional_dark_elixir_region",
     "Star-bonus dark elixir OCR region",
     (1283, 648, 1404, 697))

_pts("Autoclash.py", "loot_tracker.star_pixels",
     "End-screen star count pixels",
     [(767, 247), (1002, 230), (1144, 279)])

_reg("Autoclash.py", "ACCOUNT_NAME_BOX",
     "Account name OCR region (top-left)",
     (111, 13, 289, 41))

_pts("Autoclash.py", "gold_pixels",
     "Gold storage full check pixels",
     [(1605, 67), (1823, 67), (1763, 67), (1732, 67)])

_pts("Autoclash.py", "elixir_pixels",
     "Elixir storage full check pixels",
     [(1605, 152), (1823, 152), (1763, 152), (1732, 152)])

_drag("Autoclash.py", "map_drag_CG",
      "Map drag before CG stand",
      ((733, 291), (1177, 958)))

_pt("Autoclash.py", "active_challenge_pixel",
    "Active challenge indicator pixel",
    (513, 978))

_pt("Autoclash.py", "CG_exit_button",
    "Clan Games menu exit button",
    (1704, 79))

_pt("Autoclash.py", "CG_active_pixel",
    "Active challenge pixel (exit check)",
    (890, 459))

_pt("Autoclash.py", "CG_fallback_click",
    "Fallback: click challenge area",
    (797, 280))

_pt("Autoclash.py", "CG_confirm_click",
    "Clan Games challenge confirmation",
    (1120, 667))

_pt("Autoclash.py", "CG_scroll_center",
    "Scroll center (2nd challenge page)",
    (1177, 513))

_pt("Autoclash.py", "open_upgrade_menu_p4",
    "Open upgrade menu (Phase 4)",
    (907, 44))

_reg("Autoclash.py", "upgrade_list_region",
     "Upgrade list OCR / wall search region",
     (744, 134, 1210, 684))

_drag("Autoclash.py", "upgrade_list_scroll",
      "Scroll upgrade list drag",
      ((866, 458), (866, 258)))

_reg("Autoclash.py", "phase5_upgrade_list",
     "Phase 5 upgrade list search region",
     (771, 149, 1045, 667))

_reg("Autoclash.py", "nobuilders_search_box",
     "No-builders icon search region",
     (835, 2, 1094, 129))

_pt("Autoclash.py", "open_upgrade_menu_p5",
    "Open upgrade menu (Phase 5)",
    (907, 50))

_pt("Autoclash.py", "exit_layout_editor",
    "Exit layout editor button",
    (1843, 69))

_drag("Autoclash.py", "troop_scroll_drag",
      "Scroll troop/request panel",
      ((1288, 586), (733, 586)))

_pt("Autoclash.py", "spell_confirm",
    "Spell selection confirmation",
    (1335, 861))

_pt("Autoclash.py", "post_enter_confirm",
    "Post-enter-battle confirmation",
    (1122, 680))

_reg("Autoclash.py", "loot_ocr_region",
     "Battle preview loot OCR region",
     (78, 121, 208, 152))

_pt("Autoclash.py", "emergency_attack",
    "Emergency low-gold attack click",
    (955, 658))

_pt("Autoclash.py", "skip_next_button",
    "Skip/next when loot below threshold",
    (1788, 819))

_pts("Autoclash.py", "base_hero_coords",
     "Hero icon bar positions (y=991)",
     [(511, 991), (622, 991), (733, 991), (844, 991)])

_pt("Autoclash.py", "post_league_reward",
    "Click after claiming league reward",
    (955, 902))

_pt("Autoclash.py", "upgrade_confirm_p4",
    "Upgrade confirm button (Phase 4)",
    (1075, 867))

_pt("Autoclash.py", "final_confirm_p4",
    "Final confirmation click (Phase 4)",
    (1288, 958))


# ══════════════════════════════════════════════════════════════════════════════
# Autoclash_BB.py
# ══════════════════════════════════════════════════════════════════════════════

_pts("Autoclash_BB.py", "DEPLOY_SEQUENCE",
     "First-half troop deployment points",
     [(16, 319), (542, 694), (998, 380), (124, 408), (775, 560), (1309, 156)])

_pts("Autoclash_BB.py", "HERO_DEPLOY",
     "Hero icon then hero placement",
     [(324, 982), (788, 536)])

_pts("Autoclash_BB.py", "FIRST_HALF_PIXELS",
     "First-half victory pixels (orange)",
     [(1677, 856), (1719, 856), (1762, 856)])

_pts("Autoclash_BB.py", "STAR_PIXELS",
     "First-half star count pixels",
     [(752, 329), (966, 254), (1182, 343)])

_pt("Autoclash_BB.py", "IN_BATTLE_PIXEL",
    "Battle started indicator pixel",
    (479, 931))

_pt("Autoclash_BB.py", "HERO_ABILITY_PIXEL",
    "Hero ability available pixel",
    (350, 874))

_pts("Autoclash_BB.py", "SECOND_HALF_STAR_PIXELS",
     "Second-half blue star pixels",
     [(754, 339), (966, 260), (1178, 337)])

_drag("Autoclash_BB.py", "SECOND_HALF_DRAG",
      "Second-half deployment drag",
      ((600, 258), (1044, 724)))

_pts("Autoclash_BB.py", "SECOND_HALF_DEPLOY_POINTS",
     "Second-half troop deploy points",
     [(787, 858), (877, 791), (983, 724), (1252, 527),
      (1469, 503), (1548, 563), (1634, 629), (1763, 727)])

_pt("Autoclash_BB.py", "HERO_ICON_PIXEL",
    "Second-half hero icon click",
    (324, 982))

_pt("Autoclash_BB.py", "HERO_SECOND_CLICK",
    "Second-half hero placement",
    (1031, 668))

_drag("Autoclash_BB.py", "initial_deploy_drag",
      "Initial view drag (zoom out)",
      ((1122, 891), (622, 69)))

_pt("Autoclash_BB.py", "first_click_after_drag",
    "First click after initial drag",
    (455, 986))

_pt("Autoclash_BB.py", "hero_ability_click",
    "Hero ability activation click",
    (324, 982))

_pt("Autoclash_BB.py", "backup_button_pixel",
    "Backup mode button pixel (gray check)",
    (1684, 819))

_drag("Autoclash_BB.py", "end_gesture_1",
      "End-battle gesture 1 drag",
      ((1089, 112), (1012, 363)))

_pt("Autoclash_BB.py", "end_gesture_2",
    "End-battle gesture 2",
    (1247, 124))

_pt("Autoclash_BB.py", "end_gesture_3",
    "End-battle gesture 3",
    (1399, 913))

_pt("Autoclash_BB.py", "end_gesture_4",
    "End-battle gesture 4",
    (1621, 102))


# ══════════════════════════════════════════════════════════════════════════════
# AutomationWorker.py
# ══════════════════════════════════════════════════════════════════════════════

_pt("AutomationWorker.py", "SETTINGS_MENU_COORD",
    "Settings/gear icon",
    (1852, 841))

_pt("AutomationWorker.py", "ACCOUNT_SWITCH_MENU_COORD",
    "Switch account menu option",
    (1245, 244))

_reg("AutomationWorker.py", "ACCOUNT_SWITCH_BOX",
     "Account list panel (OCR + scroll)",
     (1321, 496, 1917, 1080))

_drag("AutomationWorker.py", "drag_pair_1",
      "BB boat search drag (right→left)",
      ((1288, 513), (289, 624)))

_drag("AutomationWorker.py", "drag_pair_2",
      "BB boat search drag (left→right)",
      ((289, 624), (1288, 513)))

_drag("AutomationWorker.py", "BB_prep_drag",
      "Reposition BB view drag",
      ((777, 752), (1011, 291)))

_pt("AutomationWorker.py", "BB_prep_click",
    "Confirm BB view position",
    (511, 752))

_reg("AutomationWorker.py", "nobuilders_search_box",
     "No-builders check region (worker)",
     (835, 2, 1095, 129))


# ══════════════════════════════════════════════════════════════════════════════
# clangamescycler.py
# ══════════════════════════════════════════════════════════════════════════════

_pts("clangamescycler.py", "GRID_COORDS",
     "Clan games slot centres (4×2 grid)",
     [(793, 311), (1047, 311), (1295, 311), (1548, 311),
      (793, 624), (1047, 624), (1295, 624), (1548, 624)])

_pt("clangamescycler.py", "SETTINGS_MENU_COORD",
    "Settings/gear icon",
    (1852, 841))

_pt("clangamescycler.py", "ACCOUNT_SWITCH_MENU_COORD",
    "Switch account menu option",
    (1245, 244))

_reg("clangamescycler.py", "ACCOUNT_SWITCH_BOX",
     "Account list panel",
     (1321, 496, 1917, 1080))

_pt("clangamescycler.py", "active_challenge_pixel",
    "Active challenge indicator pixel",
    (890, 459))

_drag("clangamescycler.py", "stand_drag",
      "Map drag to reveal CG stand",
      ((733, 291), (1177, 958)))

_pt("clangamescycler.py", "CG_exit_button",
    "Clan Games menu close button",
    (1704, 79))

_pt("clangamescycler.py", "CG_confirm_click",
    "Challenge trash confirmation",
    (1120, 667))

_pt("clangamescycler.py", "CG_exit_worker",
    "Menu exit (ClanGamesWorker variant)",
    (1674, 109))


# ══════════════════════════════════════════════════════════════════════════════
# clanscouter.py
# ══════════════════════════════════════════════════════════════════════════════

_reg("clanscouter.py", "CLANS_BOX",
     "Clan search results list region",
     (223, 451, 1310, 1036))

_pt("clanscouter.py", "CLANS_BOX_CENTER",
    "Clan list scroll target",
    (766, 743))

_reg("clanscouter.py", "CAPITAL_HALL_REGION",
     "Capital Hall level indicator region",
     (1044, 542, 1132, 582))

_pts("clanscouter.py", "OPEN_SEARCH_SEQUENCE",
     "Navigate to clan search screen",
     [(67, 58), (1166, 80), (955, 213), (1077, 354)])

_pt("clanscouter.py", "SETTINGS_MENU_COORD",
    "Settings/gear icon",
    (1852, 841))

_pt("clanscouter.py", "ACCOUNT_SWITCH_MENU_COORD",
    "Switch account menu option",
    (1245, 244))

_reg("clanscouter.py", "ACCOUNT_SWITCH_BOX",
     "Account list panel",
     (1321, 496, 1917, 1080))

_pt("clanscouter.py", "EXIT_CLAN_SEARCH_COORD",
    "Back from clan search list",
    (91, 362))

_pt("clanscouter.py", "EXIT_CLAN_SCREEN_COORD",
    "Back from clan profile",
    (278, 91))

_pt("clanscouter.py", "CLAN_STATS_COORD",
    "Open clan stats/info",
    (300, 569))

_pt("clanscouter.py", "search_input_click",
    "Click search input field",
    (777, 354))

_pt("clanscouter.py", "deselect_search_bar",
    "Deselect search bar after load",
    (222, 634))


# ══════════════════════════════════════════════════════════════════════════════
# capitalraider.py
# ══════════════════════════════════════════════════════════════════════════════

for _name, _coord in [
    ("Goblin Mines",       (1217, 1012)),
    ("Skeleton Park",      (870,  1029)),
    ("Golem Quarry",       (552,   983)),
    ("Dragon Cliffs",      (1286,  791)),
    ("Builder's Workshop", (1068,  869)),
    ("Balloon Lagoon",     (742,   833)),
    ("Wizard Valley",      (932,   658)),
    ("Barbarian Camp",     (1146,  586)),
    ("Capital Peak",       (917,   380)),
]:
    _pt("capitalraider.py", f"DISTRICT: {_name}",
        "Capital district click target",
        _coord)

_pt("capitalraider.py", "DIAMOND center (CX, CY)",
    "Diamond deployment zone center",
    (639, 436))

_pt("capitalraider.py", "TROOP_BUTTON",
    "Troop selection button",
    (344, 1000))

_pts("capitalraider.py", "SPELL_BUTTONS",
     "Spell selection buttons",
     [(484, 1000), (622, 1000)])

_pt("capitalraider.py", "DESELECT_COORD",
    "Deselect district tap",
    (1621, 624))

_drag("capitalraider.py", "nav_drag",
      "Navigation/zoom-out drag",
      ((900, 791), (677, 347)))

_pt("capitalraider.py", "PROFILE_TAB_COORD",
    "Profile tab button",
    (67, 52))

_pt("capitalraider.py", "SOCIAL_TAB_COORD",
    "Social tab in profile",
    (1510, 91))

_pt("capitalraider.py", "EXIT_PROFILE_COORD",
    "Back from player profile",
    (67, 358))

_pt("capitalraider.py", "back_button",
    "Back/exit (no active raid)",
    (100, 980))

_pt("capitalraider.py", "social_scroll_target",
    "Scroll target in social tab",
    (874, 593))

_reg("capitalraider.py", "enter_battle_search",
     "Enter Battle button search region",
     (400, 300, 1700, 750))


# ─────────────────────────────────────────────────────────────────────────────
# Overlay widget
# ─────────────────────────────────────────────────────────────────────────────

# Colour scheme
COL_POINT  = QColor(255,  60,  60)   # red
COL_REGION = QColor( 60, 220,  60)   # green
COL_DRAG   = QColor( 60, 180, 255)   # cyan
COL_PANEL  = QColor(  0,   0,   0, 190)
COL_TEXT   = QColor(255, 255, 255, 230)
COL_HEAD   = QColor(255, 220,  60, 255)   # yellow — index/controls line


class CoordOverlay(QWidget):

    def __init__(self):
        super().__init__()
        self.index = 0

        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool |
            Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)

        screen_obj = QApplication.primaryScreen()
        screen_geo = screen_obj.geometry()

        # Qt paints in logical (device-independent) pixels; most automation
        # tools report physical pixels. Convert coordinates when DPI scaling
        # is active so markers line up with the real screen.
        self.dpr = float(screen_obj.devicePixelRatio()) if screen_obj else 1.0
        self.coord_scale = (1.0 / self.dpr) if self.dpr > 1.0 else 1.0

        self.setGeometry(screen_geo)

        _bridge.next_sig.connect(self._next)
        _bridge.prev_sig.connect(self._prev)
        _bridge.quit_sig.connect(QApplication.quit)

    # ── navigation ────────────────────────────────────────────────────────────

    def _next(self):
        self.index = (self.index + 1) % len(ENTRIES)
        self.update()

    def _prev(self):
        self.index = (self.index - 1) % len(ENTRIES)
        self.update()

    def current(self):
        return ENTRIES[self.index % len(ENTRIES)] if ENTRIES else None

    # ── coordinate conversion ────────────────────────────────────────────────

    def _to_logical_scalar(self, value):
        return int(round(value * self.coord_scale))

    def _to_logical_point(self, pt):
        x, y = pt
        return self._to_logical_scalar(x), self._to_logical_scalar(y)

    def _to_logical_region(self, reg):
        x1, y1, x2, y2 = reg
        return (
            self._to_logical_scalar(x1),
            self._to_logical_scalar(y1),
            self._to_logical_scalar(x2),
            self._to_logical_scalar(y2),
        )

    def _to_logical_drag(self, drag):
        (x1, y1), (x2, y2) = drag
        return (
            self._to_logical_point((x1, y1)),
            self._to_logical_point((x2, y2)),
        )

    # ── painting ──────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        entry = self.current()
        if not entry:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        t = entry["type"]
        if t == "point":
            self._draw_point(p, self._to_logical_point(entry["value"]))
        elif t == "region":
            self._draw_region(p, self._to_logical_region(entry["value"]))
        elif t == "drag":
            self._draw_drag(p, self._to_logical_drag(entry["value"]))

        self._draw_panel(p, entry)
        p.end()

    # ── point ─────────────────────────────────────────────────────────────────

    def _draw_point(self, p, pt):
        x, y = pt
        R, ARM = 18, 38

        # crosshair
        pen = QPen(COL_POINT, 2)
        p.setPen(pen)
        p.drawLine(x - ARM, y, x + ARM, y)
        p.drawLine(x, y - ARM, x, y + ARM)

        # circle
        pen = QPen(COL_POINT, 2)
        p.setPen(pen)
        fill = QColor(COL_POINT)
        fill.setAlpha(45)
        p.setBrush(QBrush(fill))
        p.drawEllipse(QPoint(x, y), R, R)

        # coord label above
        p.setPen(QPen(COL_POINT, 1))
        p.setFont(QFont("Consolas", 9, QFont.Bold))
        p.drawText(x + R + 4, y - 4, f"({x}, {y})")

    # ── region ────────────────────────────────────────────────────────────────

    def _draw_region(self, p, reg):
        x1, y1, x2, y2 = reg
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

        pen = QPen(COL_REGION, 2)
        p.setPen(pen)
        fill = QColor(COL_REGION)
        fill.setAlpha(35)
        p.setBrush(QBrush(fill))
        p.drawRect(x1, y1, x2 - x1, y2 - y1)

        # centre dot
        p.setBrush(QBrush(COL_REGION))
        p.drawEllipse(QPoint(cx, cy), 5, 5)

        # corner labels
        p.setPen(QPen(COL_REGION, 1))
        p.setFont(QFont("Consolas", 8, QFont.Bold))
        p.drawText(x1 + 3, y1 - 3, f"({x1},{y1})")
        p.drawText(x2 - 80, y2 + 12, f"({x2},{y2})")

    # ── drag ──────────────────────────────────────────────────────────────────

    def _draw_drag(self, p, drag):
        (x1, y1), (x2, y2) = drag

        # line
        pen = QPen(COL_DRAG, 2)
        p.setPen(pen)
        p.drawLine(x1, y1, x2, y2)

        # arrowhead
        angle = math.atan2(y2 - y1, x2 - x1)
        HL = 14
        for a in (angle + 2.5, angle - 2.5):
            p.drawLine(x2, y2, int(x2 + HL * math.cos(a)), int(y2 + HL * math.sin(a)))

        # start/end circles
        fill = QColor(COL_DRAG)
        fill.setAlpha(55)
        p.setBrush(QBrush(fill))
        p.setPen(QPen(COL_DRAG, 2))
        p.drawEllipse(QPoint(x1, y1), 14, 14)
        p.drawEllipse(QPoint(x2, y2), 14, 14)

        # labels
        p.setPen(QPen(COL_DRAG, 1))
        p.setFont(QFont("Consolas", 9, QFont.Bold))
        p.drawText(x1 + 18, y1 - 5, f"START ({x1},{y1})")
        p.drawText(x2 + 18, y2 - 5, f"END ({x2},{y2})")

    # ── info panel ────────────────────────────────────────────────────────────

    def _draw_panel(self, p, entry):
        t = entry["type"]
        v = entry["value"]
        val_str = str(v)

        lines = [
            (COL_HEAD,  f"[{self.index + 1} / {len(ENTRIES)}]   SPACE = next   B = back   Esc = quit"),
            (COL_TEXT,  f"File : {entry['file']}"),
            (COL_TEXT,  f"Name : {entry['name']}"),
            (COL_TEXT,  f"Desc : {entry['desc']}"),
            (COL_TEXT,  f"Type : {t}   |   Value : {val_str}"),
        ]

        font = QFont("Consolas", 10)
        p.setFont(font)

        LH      = 22
        PAD     = 10
        W       = min(self.width() - 20, 900)
        H       = len(lines) * LH + PAD * 2
        PX, PY  = 10, self.height() - H - 10

        # background
        p.setBrush(QBrush(COL_PANEL))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(PX, PY, W, H, 8, 8)

        # border matching type colour
        border_col = {"point": COL_POINT, "region": COL_REGION, "drag": COL_DRAG}.get(t, COL_TEXT)
        p.setPen(QPen(border_col, 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(PX, PY, W, H, 8, 8)

        # text lines
        for i, (col, txt) in enumerate(lines):
            p.setPen(QPen(col))
            p.drawText(PX + PAD, PY + PAD + (i + 1) * LH - 4, txt)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)

    overlay = CoordOverlay()
    overlay.show()

    print(
        f"Overlay logical size: {overlay.width()}x{overlay.height()} | "
        f"DPR: {overlay.dpr:.2f} | coord scale: {overlay.coord_scale:.3f}"
    )
    if overlay.coord_scale != 1.0:
        print("Windows DPI scaling detected: converting physical coords to logical pixels.")

    if HAS_KEYBOARD:
        keyboard.add_hotkey("space",  _bridge.next_sig.emit, suppress=False)
        keyboard.add_hotkey("b",      _bridge.prev_sig.emit, suppress=False)
        keyboard.add_hotkey("escape", _bridge.quit_sig.emit, suppress=False)
        print(f"Loaded {len(ENTRIES)} coordinate entries.")
        print("SPACE = next   |   B = back   |   Escape = quit")
    else:
        print("'keyboard' module not found — install with:  pip install keyboard")
        print("Without it you cannot cycle through coordinates.")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
