#!/usr/bin/env python3
"""
Clash of Clans Automation — PySide6 GUI Frontend
==================================================
Professional dark-themed GUI built on Qt6.  All automation logic lives in
``AutomationWorker.py``; this file contains **only** UI code and signal/slot
wiring — no direct calls to Autoclash / Autoclash_BB.

Pages (QStackedWidget)
----------------------
0  VillageSelectionPage   — Home / BB / Stats / Clan Games picker
1  HomeConfigPage         — start, fill, account config for Home Village
2  FillAccountsPage       — multi-select accounts for fill mode
3  AccountConfigPage      — per-account settings editor
4  HomeProgressPage       — live battle stats, loot, star bars
5  BBConfigPage           — BB start, BB fill option
6  BBFillAccountsPage     — multi-select for BB fill
7  BBProgressPage         — BB battle stats, star bars
8  StatsPage              — CSV-backed account stats table
9  ClanGamesProgressPage  — Clan Games cycler status & stop
10 ClanScouterProgressPage — Clan Scout status & stop
11 CycleAccountsPage      — multi-select accounts + attacks-per-account for cycling mode
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time 
from pathlib import Path
from typing import Dict, List, Optional

# Pre-set the *exact* DPI-awareness context that Qt 6 requests
# (PER_MONITOR_AWARE_V2 = -4) before PySide6 loads, so it never
# calls SetProcessDpiAwarenessContext() itself and the
# "Access is denied" warning disappears.
if sys.platform == "win32":
    try:
        from ctypes import windll, c_void_p
        windll.user32.SetProcessDpiAwarenessContext(c_void_p(-4))
    except Exception:
        pass

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QIcon
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Automation imports — unchanged modules
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent))

from Autoclash import CONFIG, APPROVED_ACCOUNTS, log
import Autoclash
import Autoclash_BB

from AutomationWorker import (
    HomeVillageWorker,
    FillAccountsWorker,
    CycleAccountsWorker,
    BuilderBaseWorker,
    BBFillAccountsWorker,
    ClanGamesWorker,
    ClanGamesMasterWorker,
    ClanScouterWorker,
    ClanCapitalWorker,
    UpgradeAccountsWorker,
    AccountCreationWorker,
    ALL_APPROVED_ACCOUNTS,
    UPGRADE_BEHAVIOUR_FILL,
    UPGRADE_BEHAVIOUR_UPGRADE,
    UPGRADE_BEHAVIOUR_RUSH,
    normalize_account_name,
)

# ---------------------------------------------------------------------------
# Dark-theme QSS
# ---------------------------------------------------------------------------
DARK_STYLE = """
QMainWindow, QWidget {
    background-color: #1a1a2e;
    color: #e0e0e0;
    font-family: 'Segoe UI', sans-serif;
    font-size: 13px;
}

QLabel#page_title {
    font-size: 20px;
    font-weight: bold;
    color: #ffffff;
    padding-bottom: 6px;
}

QLabel#subtitle {
    color: #888;
    font-size: 11px;
}

QLabel#stat_value {
    font-size: 13px;
    font-weight: bold;
}

QPushButton {
    background-color: #16213e;
    color: #e0e0e0;
    border: 1px solid #0f3460;
    border-radius: 6px;
    padding: 10px 20px;
    font-size: 13px;
}

QPushButton:hover {
    background-color: #0f3460;
}

QPushButton:pressed {
    background-color: #0a2540;
}

QPushButton#primary_btn {
    background-color: #e94560;
    border: none;
    font-weight: bold;
    color: #ffffff;
}

QPushButton#primary_btn:hover {
    background-color: #c93a52;
}

QPushButton#danger_btn {
    background-color: #c0392b;
    border: none;
    font-weight: bold;
    color: #ffffff;
}

QPushButton#danger_btn:hover {
    background-color: #a93226;
}

QComboBox, QSpinBox {
    background-color: #16213e;
    border: 1px solid #0f3460;
    border-radius: 4px;
    padding: 6px 10px;
    color: #e0e0e0;
    min-height: 24px;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox QAbstractItemView {
    background-color: #16213e;
    color: #e0e0e0;
    selection-background-color: #0f3460;
    border: 1px solid #0f3460;
}

QCheckBox {
    spacing: 8px;
    color: #e0e0e0;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 3px;
    border: 1px solid #0f3460;
    background-color: #16213e;
}

QCheckBox::indicator:checked {
    background-color: #e94560;
    border-color: #e94560;
}

QSlider::groove:horizontal {
    height: 6px;
    background: #0f3460;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: #e94560;
    width: 16px;
    margin: -5px 0;
    border-radius: 8px;
}

QProgressBar {
    background-color: #16213e;
    border: 1px solid #0f3460;
    border-radius: 4px;
    text-align: center;
    color: #e0e0e0;
    font-size: 11px;
    height: 20px;
}

QProgressBar::chunk {
    background-color: #4CAF50;
    border-radius: 3px;
}

QTableWidget {
    background-color: #16213e;
    color: #e0e0e0;
    gridline-color: #0f3460;
    border: 1px solid #0f3460;
    selection-background-color: #0f3460;
}

QHeaderView::section {
    background-color: #0f3460;
    color: #e0e0e0;
    padding: 6px;
    border: 1px solid #16213e;
    font-weight: bold;
}

QScrollBar:vertical {
    background: #16213e;
    width: 10px;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background: #0f3460;
    border-radius: 5px;
    min-height: 30px;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QFrame#separator {
    background-color: #0f3460;
    max-height: 1px;
    min-height: 1px;
}

QFrame#card {
    background-color: #16213e;
    border: 1px solid #0f3460;
    border-radius: 8px;
    padding: 12px;
}

QMessageBox {
    background-color: #1a1a2e;
}

QMessageBox QLabel {
    color: #e0e0e0;
}

QMessageBox QPushButton {
    min-width: 80px;
}
"""


# ═══════════════════════════════════════════════════════════════════════════
# Helper widgets
# ═══════════════════════════════════════════════════════════════════════════

def _separator() -> QFrame:
    sep = QFrame()
    sep.setObjectName("separator")
    sep.setFrameShape(QFrame.Shape.HLine)
    return sep


def _title(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("page_title")
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return lbl


def _subtitle(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("subtitle")
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setWordWrap(True)
    return lbl


def _load_pixmap(filename: str, size: int = 20) -> Optional[QPixmap]:
    path = Path(__file__).parent / filename
    if not path.exists():
        return None
    pm = QPixmap(str(path))
    if pm.isNull():
        return None
    return pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


def _icon_label(filename: str, size: int = 20) -> QLabel:
    lbl = QLabel()
    pm = _load_pixmap(filename, size)
    if pm:
        lbl.setPixmap(pm)
    return lbl


# ═══════════════════════════════════════════════════════════════════════════
# Session stats helper (same as old GUI)
# ═══════════════════════════════════════════════════════════════════════════

def _new_session_stats() -> dict:
    return {
        "total_gold": 0,
        "total_elixir": 0,
        "total_dark_elixir": 0,
        "battle_count": 0,
        "star_counts": {0: 0, 1: 0, 2: 0, 3: 0},
        "total_time_seconds": 0.0,
    }


HOME_SETTING_KEYS = (
    "min_loot_amount",
    "num_battle_points",
    "num_heroes",
    "troop_type",
    "max_spell_clicks",
    "auto_upgrade_walls",
    "auto_upgrade_storages",
    "event_active",
    "do_ranked",
    "siege_machine_active",
    "clan_games_enabled",
    "request_enabled",
    "time_before_ability",
    "gem_upgrades",
    "fill_army",
    "dynamic_loot",
)


def _get_default_home_settings() -> dict:
    return {key: CONFIG.get(key) for key in HOME_SETTING_KEYS}


# ═══════════════════════════════════════════════════════════════════════════
# Page 0 — Village Selection
# ═══════════════════════════════════════════════════════════════════════════

class VillageSelectionPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(16)

        layout.addWidget(_title("Clash of Clans Automation"))
        layout.addWidget(_subtitle("Select Village Type"))
        layout.addSpacing(20)

        btn_row = QHBoxLayout()
        self.home_btn = QPushButton("Home Village")
        self.home_btn.setFixedWidth(180)
        self.bb_btn = QPushButton("Builder Base")
        self.bb_btn.setFixedWidth(180)
        btn_row.addWidget(self.home_btn)
        btn_row.addWidget(self.bb_btn)
        layout.addLayout(btn_row)

        self.clan_games_btn = QPushButton("Clan Games")
        self.clan_games_btn.setFixedWidth(180)
        layout.addWidget(self.clan_games_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.clan_scout_btn = QPushButton("Clan Scout")
        self.clan_scout_btn.setFixedWidth(180)
        layout.addWidget(self.clan_scout_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.capital_raid_btn = QPushButton("Capital Raid")
        self.capital_raid_btn.setFixedWidth(180)
        layout.addWidget(self.capital_raid_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.stats_btn = QPushButton("Stats")
        self.stats_btn.setFixedWidth(180)
        layout.addWidget(self.stats_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        _page_lbl = QLabel("Page 0", self)
        _page_lbl.setStyleSheet("color: #555; font-size: 9px;")
        _page_lbl.adjustSize()
        _page_lbl.move(5, 5)
        _page_lbl.raise_()


# ═══════════════════════════════════════════════════════════════════════════
# Page 1 — Home Config
# ═══════════════════════════════════════════════════════════════════════════

class HomeConfigPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(14)

        layout.addWidget(_title("Home Village"))
        layout.addWidget(_subtitle(
            "Start automation and the bot will detect the current account automatically.\n"
            "Use 'Account Configuration' to edit and save settings per account."
        ))
        layout.addSpacing(10)

        self.config_btn = QPushButton("Account Configuration")
        self.config_btn.setFixedWidth(240)
        layout.addWidget(self.config_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.start_btn = QPushButton("Start Automation")
        self.start_btn.setObjectName("primary_btn")
        self.start_btn.setFixedWidth(240)
        layout.addWidget(self.start_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.fill_btn = QPushButton("Fill Accounts")
        self.fill_btn.setFixedWidth(240)
        layout.addWidget(self.fill_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.cycle_btn = QPushButton("Cycle Accounts")
        self.cycle_btn.setFixedWidth(240)
        layout.addWidget(self.cycle_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.upgrade_btn = QPushButton("Upgrade Accounts")
        self.upgrade_btn.setFixedWidth(240)
        layout.addWidget(self.upgrade_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.create_account_btn = QPushButton("Create Account")
        self.create_account_btn.setFixedWidth(240)
        layout.addWidget(self.create_account_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addSpacing(10)
        self.back_btn = QPushButton("Back")
        self.back_btn.setFixedWidth(240)
        layout.addWidget(self.back_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        _page_lbl = QLabel("Page 1", self)
        _page_lbl.setStyleSheet("color: #555; font-size: 9px;")
        _page_lbl.adjustSize()
        _page_lbl.move(5, 5)
        _page_lbl.raise_()


# ═══════════════════════════════════════════════════════════════════════════
# Page 2 — Fill Accounts selection
# ═══════════════════════════════════════════════════════════════════════════

class FillAccountsPage(QWidget):
    def __init__(self, accounts: list, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        layout.addWidget(_title("Fill Accounts"))
        layout.addWidget(_subtitle(
            "Select accounts to fill. The bot will switch accounts, farm until\n"
            "gold+elixir are full on each selected account, then stop."
        ))

        self.checkboxes: Dict[str, QCheckBox] = {}
        grid = QGridLayout()
        for i, name in enumerate(sorted(accounts)):
            cb = QCheckBox(name)
            self.checkboxes[name] = cb
            grid.addWidget(cb, i // 2, i % 2)
        layout.addLayout(grid)

        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.setFixedWidth(240)
        self.select_all_btn.clicked.connect(self._toggle_all)
        layout.addWidget(self.select_all_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.start_btn = QPushButton("Start Fill Accounts")
        self.start_btn.setObjectName("primary_btn")
        self.start_btn.setFixedWidth(240)
        layout.addWidget(self.start_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.back_btn = QPushButton("Back")
        self.back_btn.setFixedWidth(240)
        layout.addWidget(self.back_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        _page_lbl = QLabel("Page 2", self)
        _page_lbl.setStyleSheet("color: #555; font-size: 9px;")
        _page_lbl.adjustSize()
        _page_lbl.move(5, 5)
        _page_lbl.raise_()

    def _toggle_all(self):
        all_checked = all(cb.isChecked() for cb in self.checkboxes.values())
        for cb in self.checkboxes.values():
            cb.setChecked(not all_checked)
        self.select_all_btn.setText("Deselect All" if not all_checked else "Select All")

    def selected_accounts(self) -> List[str]:
        return [name for name, cb in self.checkboxes.items() if cb.isChecked()]


# ═══════════════════════════════════════════════════════════════════════════
# Page 11 — Cycle Accounts selection
# ═══════════════════════════════════════════════════════════════════════════

class CycleAccountsPage(QWidget):
    def __init__(self, accounts: list, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        layout.addWidget(_title("Cycle Accounts"))
        layout.addWidget(_subtitle(
            "Select accounts and set attacks per account.\n"
            "The bot will cycle through accounts indefinitely, doing N attacks on each."
        ))

        self.checkboxes: Dict[str, QCheckBox] = {}
        grid = QGridLayout()
        for i, name in enumerate(sorted(accounts)):
            cb = QCheckBox(name)
            self.checkboxes[name] = cb
            grid.addWidget(cb, i // 2, i % 2)
        layout.addLayout(grid)

        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.setFixedWidth(240)
        self.select_all_btn.clicked.connect(self._toggle_all)
        layout.addWidget(self.select_all_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        attacks_row = QHBoxLayout()
        attacks_row.setSpacing(10)
        attacks_row.addStretch()
        attacks_row.addWidget(QLabel("Attacks per account:"))
        self.attacks_spin = QSpinBox()
        self.attacks_spin.setMinimum(1)
        self.attacks_spin.setMaximum(99)
        self.attacks_spin.setValue(5)
        self.attacks_spin.setFixedWidth(80)
        attacks_row.addWidget(self.attacks_spin)
        attacks_row.addStretch()
        layout.addLayout(attacks_row)

        self.start_btn = QPushButton("Start Cycle Accounts")
        self.start_btn.setObjectName("primary_btn")
        self.start_btn.setFixedWidth(240)
        layout.addWidget(self.start_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.back_btn = QPushButton("Back")
        self.back_btn.setFixedWidth(240)
        layout.addWidget(self.back_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        _page_lbl = QLabel("Page 11", self)
        _page_lbl.setStyleSheet("color: #555; font-size: 9px;")
        _page_lbl.adjustSize()
        _page_lbl.move(5, 5)
        _page_lbl.raise_()

    def _toggle_all(self):
        all_checked = all(cb.isChecked() for cb in self.checkboxes.values())
        for cb in self.checkboxes.values():
            cb.setChecked(not all_checked)
        self.select_all_btn.setText("Deselect All" if not all_checked else "Select All")

    def selected_accounts(self) -> List[str]:
        return [name for name, cb in self.checkboxes.items() if cb.isChecked()]

    def attacks_per_account(self) -> int:
        return self.attacks_spin.value()


# ═══════════════════════════════════════════════════════════════════════════
# Page 14 — Upgrade Accounts selection (djbillgates accounts only)
# ═══════════════════════════════════════════════════════════════════════════

class UpgradeAccountsPage(QWidget):
    """Per-account upgrade configuration screen.

    Each approved account gets a row with:
      - a checkbox  (include / exclude this account from the cycle)
      - a label     (account name)
      - a dropdown  (upgrade behaviour for this account)

    Behaviour options match the UPGRADE_BEHAVIOUR_* constants in AutomationWorker.
    """

    _BEHAVIOUR_LABELS = [
        "Fill Storages",      # index 0 → UPGRADE_BEHAVIOUR_FILL   (1)
        "Upgrade Account",    # index 1 → UPGRADE_BEHAVIOUR_UPGRADE (2)
        "Rush Account",       # index 2 → UPGRADE_BEHAVIOUR_RUSH    (3)
    ]
    # Map combo index → behaviour constant
    _INDEX_TO_BEHAVIOUR = {
        0: UPGRADE_BEHAVIOUR_FILL,
        1: UPGRADE_BEHAVIOUR_UPGRADE,
        2: UPGRADE_BEHAVIOUR_RUSH,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setSpacing(10)

        outer.addWidget(_title("Upgrade Accounts"))
        outer.addWidget(_subtitle(
            "Tick the accounts to include in the upgrade cycle.\n"
            "Choose a behaviour for each account from the dropdown.\n"
            "Fill Storages: farm only.  Upgrade Account: all buildings (no TH).  "
            "Rush Account: storages → new buildings → Town Hall."
        ))

        # --- Scrollable account list ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        inner_widget = QWidget()
        inner_layout = QVBoxLayout(inner_widget)
        inner_layout.setSpacing(4)
        inner_layout.setContentsMargins(4, 4, 4, 4)

        self._checkboxes: Dict[str, QCheckBox] = {}
        self._combos: Dict[str, QComboBox] = {}

        for name in ALL_APPROVED_ACCOUNTS:
            row = QHBoxLayout()
            row.setSpacing(8)

            cb = QCheckBox()
            cb.setFixedWidth(20)
            self._checkboxes[name] = cb

            lbl = QLabel(name)
            lbl.setMinimumWidth(150)

            combo = QComboBox()
            combo.addItems(self._BEHAVIOUR_LABELS)
            combo.setCurrentIndex(1)          # default: Upgrade Account
            combo.setFixedWidth(160)
            self._combos[name] = combo

            row.addWidget(cb)
            row.addWidget(lbl)
            row.addWidget(combo)
            row.addStretch()
            inner_layout.addLayout(row)

        inner_layout.addStretch()
        scroll.setWidget(inner_widget)
        outer.addWidget(scroll, stretch=1)

        self.start_btn = QPushButton("Start Upgrade Accounts")
        self.start_btn.setObjectName("primary_btn")
        self.start_btn.setFixedWidth(240)
        outer.addWidget(self.start_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.back_btn = QPushButton("Back")
        self.back_btn.setFixedWidth(240)
        outer.addWidget(self.back_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        _page_lbl = QLabel("Page 14", self)
        _page_lbl.setStyleSheet("color: #555; font-size: 9px;")
        _page_lbl.adjustSize()
        _page_lbl.move(5, 5)
        _page_lbl.raise_()

    def account_behaviours(self) -> Dict[str, int]:
        """Return {account_name: behaviour_constant} for every ticked account."""
        result: Dict[str, int] = {}
        for name, cb in self._checkboxes.items():
            if cb.isChecked():
                combo_index = self._combos[name].currentIndex()
                result[name] = self._INDEX_TO_BEHAVIOUR.get(combo_index, UPGRADE_BEHAVIOUR_UPGRADE)
        return result


# ═══════════════════════════════════════════════════════════════════════════
# Page 3 — Account Configuration Editor
# ═══════════════════════════════════════════════════════════════════════════

class AccountConfigPage(QWidget):
    def __init__(self, account_names: list, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        layout.addWidget(_title("Account Configuration"))

        # Account selector
        row = QHBoxLayout()
        row.addWidget(QLabel("Account:"))
        self.account_combo = QComboBox()
        self.account_combo.addItems(account_names)
        self.account_combo.setMinimumWidth(180)
        row.addWidget(self.account_combo)
        row.addStretch()
        layout.addLayout(row)

        layout.addWidget(_separator())

        # --- Settings form in a scroll area for safety ---
        form_widget = QWidget()
        form = QGridLayout(form_widget)
        form.setSpacing(10)
        r = 0

        # Min Loot
        form.addWidget(QLabel("Minimum Loot Amount:"), r, 0)
        self.loot_combo = QComboBox()
        self.loot_combo.setEditable(True)
        loot_values = [f"{v:,}" for v in range(0, 1_000_001, 50_000)]
        self.loot_combo.addItems(loot_values)
        form.addWidget(self.loot_combo, r, 1)
        r += 1

        # Battle Points
        form.addWidget(QLabel("Number of Battle Points:"), r, 0)
        self.battle_points_combo = QComboBox()
        self.battle_points_combo.setEditable(True)
        self.battle_points_combo.addItems([str(v) for v in range(1, 17)])
        form.addWidget(self.battle_points_combo, r, 1)
        r += 1

        # Heroes
        form.addWidget(QLabel("Number of Heroes:"), r, 0)
        self.heroes_combo = QComboBox()
        self.heroes_combo.addItems([str(v) for v in range(0, 5)])
        form.addWidget(self.heroes_combo, r, 1)
        r += 1

        # Troop Type
        form.addWidget(QLabel("Troop Type:"), r, 0)
        self.troop_combo = QComboBox()
        self.troop_combo.addItems(["edrag", "drag", "azdrag", "barbarian"])
        form.addWidget(self.troop_combo, r, 1)
        r += 1

        # Spell Capacity
        form.addWidget(QLabel("Spell Capacity:"), r, 0)
        self.spell_combo = QComboBox()
        self.spell_combo.addItems([str(v) for v in range(0, 16)])
        form.addWidget(self.spell_combo, r, 1)
        r += 1

        # Checkboxes
        self.auto_upgrade_cb = QCheckBox("Auto Upgrade Walls (Phase 4)")
        form.addWidget(self.auto_upgrade_cb, r, 0, 1, 2); r += 1

        self.auto_upgrade_storages_cb = QCheckBox("Auto Upgrade Storages (Phase 5)")
        form.addWidget(self.auto_upgrade_storages_cb, r, 0, 1, 2); r += 1

        # Event active with icon
        event_row = QHBoxLayout()
        self.event_active_cb = QCheckBox("Event Active (Electro Dragon x30)")
        pm = _load_pixmap("edrag_button.png", 20)
        if pm:
            icon_lbl = QLabel()
            icon_lbl.setPixmap(pm)
            event_row.addWidget(icon_lbl)
        event_row.addWidget(self.event_active_cb)
        event_row.addStretch()
        form.addLayout(event_row, r, 0, 1, 2); r += 1

        self.do_ranked_cb = QCheckBox("Do Ranked")
        form.addWidget(self.do_ranked_cb, r, 0, 1, 2); r += 1

        self.siege_cb = QCheckBox("Siege Machine Active")
        form.addWidget(self.siege_cb, r, 0, 1, 2); r += 1

        self.clan_games_cb = QCheckBox("Clan Games Active")
        form.addWidget(self.clan_games_cb, r, 0, 1, 2); r += 1

        self.request_cb = QCheckBox("Request")
        form.addWidget(self.request_cb, r, 0, 1, 2); r += 1

        self.gem_upgrades_cb = QCheckBox("Gem Upgrades (use gems to speed up upgrades)")
        form.addWidget(self.gem_upgrades_cb, r, 0, 1, 2); r += 1

        self.fill_army_cb = QCheckBox("Fill Army (top up army before attacking if not full)")
        form.addWidget(self.fill_army_cb, r, 0, 1, 2); r += 1

        self.dynamic_loot_cb = QCheckBox("Auto Min Loot (set min loot to 50% of best attack gold)")
        form.addWidget(self.dynamic_loot_cb, r, 0, 1, 2); r += 1

        # Time Before Ability slider
        form.addWidget(QLabel("Time Before Ability (seconds):"), r, 0)
        slider_row = QHBoxLayout()
        self.ability_slider = QSlider(Qt.Orientation.Horizontal)
        self.ability_slider.setRange(0, 100)
        self.ability_slider.setValue(15)
        self.ability_slider.setFixedWidth(180)
        self.ability_value_label = QLabel("15s")
        self.ability_slider.valueChanged.connect(lambda v: self.ability_value_label.setText(f"{v}s"))
        slider_row.addWidget(self.ability_slider)
        slider_row.addWidget(self.ability_value_label)
        slider_row.addStretch()
        form.addLayout(slider_row, r, 1)
        r += 1

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_widget)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(scroll)

        layout.addWidget(_subtitle("Edit settings for this account and save. If automation is running, changes apply on the next battle."))

        self.save_btn = QPushButton("Save Account Settings")
        self.save_btn.setObjectName("primary_btn")
        self.save_btn.setFixedWidth(240)
        layout.addWidget(self.save_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.mass_config_btn = QPushButton("Mass Configure")
        self.mass_config_btn.setFixedWidth(240)
        layout.addWidget(self.mass_config_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.back_btn = QPushButton("Back")
        self.back_btn.setFixedWidth(240)
        layout.addWidget(self.back_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        _page_lbl = QLabel("Page 3", self)
        _page_lbl.setStyleSheet("color: #555; font-size: 9px;")
        _page_lbl.adjustSize()
        _page_lbl.move(5, 5)
        _page_lbl.raise_()

    # --- helpers to get / set values ---
    def populate(self, settings: dict):
        _set_combo(self.loot_combo, f"{int(settings.get('min_loot_amount', 0)):,}")
        _set_combo(self.battle_points_combo, str(int(settings.get("num_battle_points", 10))))
        _set_combo(self.heroes_combo, str(int(settings.get("num_heroes", 4))))
        _set_combo(self.troop_combo, str(settings.get("troop_type", "edrag")).lower())
        _set_combo(self.spell_combo, str(int(settings.get("max_spell_clicks", 15))))
        self.auto_upgrade_cb.setChecked(bool(settings.get("auto_upgrade_walls", True)))
        self.auto_upgrade_storages_cb.setChecked(bool(settings.get("auto_upgrade_storages", True)))
        self.event_active_cb.setChecked(bool(settings.get("event_active", False)))
        self.do_ranked_cb.setChecked(bool(settings.get("do_ranked", True)))
        self.siege_cb.setChecked(bool(settings.get("siege_machine_active", False)))
        self.clan_games_cb.setChecked(bool(settings.get("clan_games_enabled", False)))
        self.request_cb.setChecked(bool(settings.get("request_enabled", False)))
        self.gem_upgrades_cb.setChecked(bool(settings.get("gem_upgrades", False)))
        self.fill_army_cb.setChecked(bool(settings.get("fill_army", False)))
        self.dynamic_loot_cb.setChecked(bool(settings.get("dynamic_loot", False)))
        self.ability_slider.setValue(max(0, min(100, int(settings.get("time_before_ability", 15)))))

    def collect(self) -> dict:
        def _pint(text: str) -> int:
            return int(text.replace(",", "").strip())
        return {
            "min_loot_amount": _pint(self.loot_combo.currentText()),
            "num_battle_points": _pint(self.battle_points_combo.currentText()),
            "num_heroes": _pint(self.heroes_combo.currentText()),
            "troop_type": self.troop_combo.currentText().lower(),
            "max_spell_clicks": _pint(self.spell_combo.currentText()),
            "auto_upgrade_walls": self.auto_upgrade_cb.isChecked(),
            "auto_upgrade_storages": self.auto_upgrade_storages_cb.isChecked(),
            "event_active": self.event_active_cb.isChecked(),
            "do_ranked": self.do_ranked_cb.isChecked(),
            "siege_machine_active": self.siege_cb.isChecked(),
            "clan_games_enabled": self.clan_games_cb.isChecked(),
            "request_enabled": self.request_cb.isChecked(),
            "gem_upgrades": self.gem_upgrades_cb.isChecked(),
            "fill_army": self.fill_army_cb.isChecked(),
            "dynamic_loot": self.dynamic_loot_cb.isChecked(),
            "time_before_ability": self.ability_slider.value(),
        }


# ─── Setting definitions for Mass Configure ──────────────────────────────────
# Each entry: (display_name, config_key, widget_type, options_list_or_None)
#   widget_type: "bool" | "combo" | "loot"
_MASS_SETTINGS = [
    ("Minimum Loot Amount",    "min_loot_amount",      "loot",  None),
    ("Battle Points",          "num_battle_points",    "combo", [str(i) for i in range(1, 17)]),
    ("Number of Heroes",       "num_heroes",           "combo", [str(i) for i in range(0, 5)]),
    ("Troop Type",             "troop_type",           "combo", ["edrag", "drag", "azdrag", "barbarian"]),
    ("Spell Capacity",         "max_spell_clicks",     "combo", [str(i) for i in range(0, 16)]),
    ("Time Before Ability (s)","time_before_ability",  "combo", [str(i) for i in range(0, 101)]),
    ("Auto Upgrade Walls",     "auto_upgrade_walls",   "bool",  None),
    ("Auto Upgrade Storages",  "auto_upgrade_storages","bool",  None),
    ("Event Active",           "event_active",         "bool",  None),
    ("Do Ranked",              "do_ranked",            "bool",  None),
    ("Siege Machine Active",   "siege_machine_active", "bool",  None),
    ("Clan Games Active",      "clan_games_enabled",   "bool",  None),
    ("Request",                "request_enabled",      "bool",  None),
    ("Gem Upgrades",           "gem_upgrades",         "bool",  None),
    ("Fill Army",              "fill_army",            "bool",  None),
    ("Auto Min Loot",          "dynamic_loot",         "bool",  None),
]


# ═══════════════════════════════════════════════════════════════════════════
# Page 15 — Mass Configure
# ═══════════════════════════════════════════════════════════════════════════

class MassConfigurePage(QWidget):
    """Apply a single setting to many accounts at once."""
  
    def __init__(self, account_names: list, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        layout.addWidget(_title("Mass Configure"))
        layout.addWidget(_subtitle(
            "Choose a setting, set its value, tick the accounts to update, then Apply."
        ))
        layout.addWidget(_separator())

        # ── Setting selector ─────────────────────────────────────────────
        setting_row = QHBoxLayout()
        setting_row.addWidget(QLabel("Setting:"))
        self._setting_combo = QComboBox()
        self._setting_combo.setMinimumWidth(220)
        for display, _key, _wtype, _opts in _MASS_SETTINGS:
            self._setting_combo.addItem(display)
        setting_row.addWidget(self._setting_combo)
        setting_row.addStretch()
        layout.addLayout(setting_row)

        # ── Value widget (switches based on setting type) ─────────────────
        value_row = QHBoxLayout()
        value_row.addWidget(QLabel("Value:"))

        self._value_stack = QStackedWidget()
        self._value_stack.setFixedHeight(36)

        # Page 0 – boolean
        bool_widget = QWidget()
        bool_layout = QHBoxLayout(bool_widget)
        bool_layout.setContentsMargins(0, 0, 0, 0)
        self._bool_cb = QCheckBox("Enabled")
        bool_layout.addWidget(self._bool_cb)
        bool_layout.addStretch()
        self._value_stack.addWidget(bool_widget)

        # Page 1 – generic combo
        self._choice_combo = QComboBox()
        self._value_stack.addWidget(self._choice_combo)

        # Page 2 – loot combo (editable, 0-1 000 000 in 50k steps)
        self._loot_combo = QComboBox()
        self._loot_combo.setEditable(True)
        loot_values = [f"{v:,}" for v in range(0, 1_000_001, 50_000)]
        self._loot_combo.addItems(loot_values)
        self._value_stack.addWidget(self._loot_combo)

        value_row.addWidget(self._value_stack)
        value_row.addStretch()
        layout.addLayout(value_row)

        layout.addWidget(_separator())

        # ── Account list ─────────────────────────────────────────────────
        layout.addWidget(QLabel("Apply to accounts:"))

        sel_row = QHBoxLayout()
        self._sel_all_btn = QPushButton("Select All")
        self._sel_all_btn.setFixedWidth(100)
        self._sel_none_btn = QPushButton("Select None")
        self._sel_none_btn.setFixedWidth(100)
        sel_row.addWidget(self._sel_all_btn)
        sel_row.addWidget(self._sel_none_btn)
        sel_row.addStretch()
        layout.addLayout(sel_row)

        self._account_list = QListWidget()
        self._account_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        layout.addWidget(self._account_list, stretch=1)

        layout.addWidget(_separator())

        # ── Buttons ──────────────────────────────────────────────────────
        self.apply_btn = QPushButton("Apply to 0 Accounts")
        self.apply_btn.setObjectName("primary_btn")
        self.apply_btn.setFixedWidth(240)
        layout.addWidget(self.apply_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.back_btn = QPushButton("Back")
        self.back_btn.setFixedWidth(240)
        layout.addWidget(self.back_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # ── Init state ───────────────────────────────────────────────────
        self.refresh_accounts(account_names)
        self._on_setting_changed(0)

        # Connections
        self._setting_combo.currentIndexChanged.connect(self._on_setting_changed)
        self._sel_all_btn.clicked.connect(self._select_all)
        self._sel_none_btn.clicked.connect(self._select_none)
        self._account_list.itemChanged.connect(self._update_apply_label)

    # ── Helpers ──────────────────────────────────────────────────────────

    def refresh_accounts(self, account_names: list):
        self._account_list.blockSignals(True)
        self._account_list.clear()
        for name in sorted(account_names):
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self._account_list.addItem(item)
        self._account_list.blockSignals(False)
        self._update_apply_label()

    def _on_setting_changed(self, index: int):
        _display, _key, wtype, opts = _MASS_SETTINGS[index]
        if wtype == "bool":
            self._value_stack.setCurrentIndex(0)
        elif wtype == "loot":
            self._value_stack.setCurrentIndex(2)
        else:  # "combo"
            self._choice_combo.blockSignals(True)
            self._choice_combo.clear()
            self._choice_combo.addItems(opts or [])
            self._choice_combo.blockSignals(False)
            self._value_stack.setCurrentIndex(1)

    def _select_all(self):
        self._account_list.blockSignals(True)
        for i in range(self._account_list.count()):
            self._account_list.item(i).setCheckState(Qt.CheckState.Checked)
        self._account_list.blockSignals(False)
        self._update_apply_label()

    def _select_none(self):
        self._account_list.blockSignals(True)
        for i in range(self._account_list.count()):
            self._account_list.item(i).setCheckState(Qt.CheckState.Unchecked)
        self._account_list.blockSignals(False)
        self._update_apply_label()

    def _update_apply_label(self):
        n = len(self.selected_accounts())
        self.apply_btn.setText(f"Apply to {n} Account{'s' if n != 1 else ''}")

    def selected_accounts(self) -> list:
        result = []
        for i in range(self._account_list.count()):
            item = self._account_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                result.append(item.text())
        return result

    def current_setting(self):
        """Return (config_key, value) for the currently chosen setting and value."""
        idx = self._setting_combo.currentIndex()
        _display, key, wtype, _opts = _MASS_SETTINGS[idx]
        if wtype == "bool":
            value = self._bool_cb.isChecked()
        elif wtype == "loot":
            try:
                value = int(self._loot_combo.currentText().replace(",", "").strip())
            except ValueError:
                value = 0
        else:
            value = self._choice_combo.currentText().strip()
            # Cast to int where appropriate
            try:
                value = int(value)
            except ValueError:
                pass
        return key, value


def _set_combo(combo: QComboBox, text: str):
    idx = combo.findText(text)
    if idx >= 0:
        combo.setCurrentIndex(idx)
    elif combo.isEditable():
        combo.setCurrentText(text)
    else:
        combo.setCurrentIndex(0)


# ═══════════════════════════════════════════════════════════════════════════
# Page 4 — Home Progress
# ═══════════════════════════════════════════════════════════════════════════

class HomeProgressPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        layout.addWidget(_title("Automation Running"))

        # Top stats row
        top = QHBoxLayout()
        top.addWidget(QLabel("Battles:"))
        self.battles_label = QLabel("0")
        self.battles_label.setObjectName("stat_value")
        self.battles_label.setStyleSheet("color: #4CAF50;")
        top.addWidget(self.battles_label)
        top.addSpacing(20)

        top.addWidget(QLabel("Stats View:"))
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("Total Stats")
        self.scope_combo.setMinimumWidth(160)
        top.addWidget(self.scope_combo)
        top.addStretch()
        layout.addLayout(top)

        # Action
        self.action_label = QLabel("Initializing...")
        self.action_label.setStyleSheet("color: #5dade2;")
        self.action_label.setWordWrap(True)
        layout.addWidget(self.action_label)

        layout.addWidget(_separator())

        # Star bars (3→0)
        layout.addWidget(QLabel("Star Statistics:"))
        self.star_bars: Dict[int, QProgressBar] = {}
        self.star_pct_labels: Dict[int, QLabel] = {}
        for star in (3, 2, 1, 0):
            row = QHBoxLayout()
            emoji = "\u2605" * star + "\u2606" * (3 - star)
            row.addWidget(QLabel(emoji))
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(0)
            bar.setTextVisible(False)
            bar.setFixedHeight(18)
            row.addWidget(bar, 1)
            pct = QLabel("0.0%")
            pct.setFixedWidth(50)
            row.addWidget(pct)
            self.star_bars[star] = bar
            self.star_pct_labels[star] = pct
            layout.addLayout(row)

        layout.addWidget(_separator())

        # Loot row with icons
        layout.addWidget(QLabel("Loot Statistics:"))
        loot_row = QHBoxLayout()
        loot_row.addWidget(_icon_label("gold_logo.jpg"))
        self.gold_label = QLabel("0")
        self.gold_label.setStyleSheet("color: #FFD700; font-weight: bold;")
        loot_row.addWidget(self.gold_label)
        loot_row.addSpacing(16)
        loot_row.addWidget(_icon_label("elixir_logo.jpg"))
        self.elixir_label = QLabel("0")
        self.elixir_label.setStyleSheet("color: #FF1493; font-weight: bold;")
        loot_row.addWidget(self.elixir_label)
        loot_row.addSpacing(16)
        loot_row.addWidget(_icon_label("dark_logo.jpg"))
        self.dark_label = QLabel("0")
        self.dark_label.setStyleSheet("color: #8B008B; font-weight: bold;")
        loot_row.addWidget(self.dark_label)
        loot_row.addStretch()
        layout.addLayout(loot_row)

        # Per hour
        layout.addWidget(QLabel("Per Hour:"))
        self.gold_ph = QLabel("Gold/hr: 0")
        self.gold_ph.setStyleSheet("color: #FFD700;")
        self.elixir_ph = QLabel("Elixir/hr: 0")
        self.elixir_ph.setStyleSheet("color: #FF1493;")
        self.dark_ph = QLabel("Dark/hr: 0")
        self.dark_ph.setStyleSheet("color: #8B008B;")
        layout.addWidget(self.gold_ph)
        layout.addWidget(self.elixir_ph)
        layout.addWidget(self.dark_ph)

        # Avg per attack
        layout.addWidget(QLabel("Avg per Attack:"))
        self.avg_gold = QLabel("Gold: 0")
        self.avg_gold.setStyleSheet("color: #FFD700;")
        self.avg_elixir = QLabel("Elixir: 0")
        self.avg_elixir.setStyleSheet("color: #FF1493;")
        self.avg_dark = QLabel("Dark: 0")
        self.avg_dark.setStyleSheet("color: #8B008B;")
        layout.addWidget(self.avg_gold)
        layout.addWidget(self.avg_elixir)
        layout.addWidget(self.avg_dark)

        self.time_label = QLabel("Runtime: 0.0 min")
        self.time_label.setStyleSheet("color: #888;")
        layout.addWidget(self.time_label)

        layout.addWidget(_separator())

        # Buttons
        btn_row = QHBoxLayout()
        self.config_btn = QPushButton("Configure Settings")
        self.config_btn.setFixedWidth(180)
        btn_row.addWidget(self.config_btn)
        self.stop_btn = QPushButton("Stop Automation")
        self.stop_btn.setObjectName("danger_btn")
        self.stop_btn.setFixedWidth(180)
        btn_row.addWidget(self.stop_btn)
        layout.addLayout(btn_row)

        _page_lbl = QLabel("Page 4", self)
        _page_lbl.setStyleSheet("color: #555; font-size: 9px;")
        _page_lbl.adjustSize()
        _page_lbl.move(5, 5)
        _page_lbl.raise_()


# ═══════════════════════════════════════════════════════════════════════════
# Page 5 — BB Config
# ═══════════════════════════════════════════════════════════════════════════

class BBConfigPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(16)

        layout.addWidget(_title("Builder Base Automation Setup"))
        layout.addWidget(_subtitle("Click 'Start Automation' to begin."))
        layout.addSpacing(10)

        self.start_btn = QPushButton("Start Automation")
        self.start_btn.setObjectName("primary_btn")
        self.start_btn.setFixedWidth(240)
        layout.addWidget(self.start_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.fill_btn = QPushButton("Fill Accounts")
        self.fill_btn.setFixedWidth(240)
        layout.addWidget(self.fill_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.back_btn = QPushButton("Back")
        self.back_btn.setFixedWidth(240)
        layout.addWidget(self.back_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        _page_lbl = QLabel("Page 5", self)
        _page_lbl.setStyleSheet("color: #555; font-size: 9px;")
        _page_lbl.adjustSize()
        _page_lbl.move(5, 5)
        _page_lbl.raise_()


# ═══════════════════════════════════════════════════════════════════════════
# Page 6 — BB Fill Accounts
# ═══════════════════════════════════════════════════════════════════════════

class BBFillAccountsPage(QWidget):
    def __init__(self, accounts: list, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        layout.addWidget(_title("Builder Base Fill Accounts"))
        layout.addWidget(_subtitle(
            "Select accounts to fill in Builder Base mode.\n"
            "The bot switches accounts and battles until storage-full checks pass."
        ))

        self.checkboxes: Dict[str, QCheckBox] = {}
        grid = QGridLayout()
        for i, name in enumerate(sorted(accounts)):
            cb = QCheckBox(name)
            self.checkboxes[name] = cb
            grid.addWidget(cb, i // 2, i % 2)
        layout.addLayout(grid)

        self.start_btn = QPushButton("Start BB Fill Accounts")
        self.start_btn.setObjectName("primary_btn")
        self.start_btn.setFixedWidth(240)
        layout.addWidget(self.start_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.back_btn = QPushButton("Back")
        self.back_btn.setFixedWidth(240)
        layout.addWidget(self.back_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        _page_lbl = QLabel("Page 6", self)
        _page_lbl.setStyleSheet("color: #555; font-size: 9px;")
        _page_lbl.adjustSize()
        _page_lbl.move(5, 5)
        _page_lbl.raise_()

    def selected_accounts(self) -> List[str]:
        return [name for name, cb in self.checkboxes.items() if cb.isChecked()]


# ═══════════════════════════════════════════════════════════════════════════
# Page 7 — BB Progress
# ═══════════════════════════════════════════════════════════════════════════

class BBProgressPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        layout.addWidget(_title("Builder Base Automation Running"))

        top = QHBoxLayout()
        top.addWidget(QLabel("Battles:"))
        self.battles_label = QLabel("0")
        self.battles_label.setObjectName("stat_value")
        self.battles_label.setStyleSheet("color: #4CAF50;")
        top.addWidget(self.battles_label)
        top.addStretch()
        layout.addLayout(top)

        self.action_label = QLabel("Initializing...")
        self.action_label.setStyleSheet("color: #5dade2;")
        self.action_label.setWordWrap(True)
        layout.addWidget(self.action_label)

        layout.addWidget(_separator())

        # Totals
        stats_row = QHBoxLayout()
        stats_row.addWidget(QLabel("Total Stars:"))
        self.total_stars_label = QLabel("0")
        self.total_stars_label.setStyleSheet("color: orange; font-weight: bold;")
        stats_row.addWidget(self.total_stars_label)
        stats_row.addSpacing(24)
        stats_row.addWidget(QLabel("Avg Stars/Battle:"))
        self.avg_stars_label = QLabel("0.00")
        self.avg_stars_label.setStyleSheet("color: orange; font-weight: bold;")
        stats_row.addWidget(self.avg_stars_label)
        stats_row.addSpacing(24)
        stats_row.addWidget(QLabel("Avg Time/Battle:"))
        self.avg_time_label = QLabel("0:00")
        stats_row.addWidget(self.avg_time_label)
        stats_row.addStretch()
        layout.addLayout(stats_row)

        layout.addWidget(_separator())

        # Star bars (6→0)
        layout.addWidget(QLabel("Star Breakdown:"))
        self.star_bars: Dict[int, QProgressBar] = {}
        self.star_pct_labels: Dict[int, QLabel] = {}
        for star in (6, 5, 4, 3, 2, 1, 0):
            row = QHBoxLayout()
            emoji = "\u2605" * star + "\u2606" * (6 - star)
            row.addWidget(QLabel(emoji))
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(0)
            bar.setTextVisible(False)
            bar.setFixedHeight(18)
            row.addWidget(bar, 1)
            pct = QLabel("0.0%")
            pct.setFixedWidth(50)
            row.addWidget(pct)
            self.star_bars[star] = bar
            self.star_pct_labels[star] = pct
            layout.addLayout(row)

        self.time_label = QLabel("Runtime: 0.0 min")
        self.time_label.setStyleSheet("color: #888;")
        layout.addWidget(self.time_label)

        layout.addWidget(_separator())

        btn_row = QHBoxLayout()
        self.stop_btn = QPushButton("Stop Automation")
        self.stop_btn.setObjectName("danger_btn")
        self.stop_btn.setFixedWidth(180)
        btn_row.addWidget(self.stop_btn)
        self.back_btn = QPushButton("Back")
        self.back_btn.setFixedWidth(180)
        btn_row.addWidget(self.back_btn)
        layout.addLayout(btn_row)

        _page_lbl = QLabel("Page 7", self)
        _page_lbl.setStyleSheet("color: #555; font-size: 9px;")
        _page_lbl.adjustSize()
        _page_lbl.move(5, 5)
        _page_lbl.raise_()


# ═══════════════════════════════════════════════════════════════════════════
# Page 8 — Stats Dashboard (QWebEngineView + Chart.js)
# ═══════════════════════════════════════════════════════════════════════════

class StatsPage(QWidget):
    """Rich HTML/Chart.js dashboard rendered inside a QWebEngineView."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.view = QWebEngineView()
        layout.addWidget(self.view, 1)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(10, 6, 10, 6)
        self.back_btn = QPushButton("Back")
        self.back_btn.setFixedWidth(120)
        btn_row.addWidget(self.back_btn)
        btn_row.addStretch()
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setFixedWidth(120)
        btn_row.addWidget(self.refresh_btn)
        layout.addLayout(btn_row)

        _page_lbl = QLabel("Page 8", self)
        _page_lbl.setStyleSheet("color: #555; font-size: 9px;")
        _page_lbl.adjustSize()
        _page_lbl.move(5, 5)
        _page_lbl.raise_()

    def refresh(self):
        """Read account_stats.csv, inject as JSON into the HTML template, render."""
        stats_path = Path(__file__).parent / CONFIG.get("stats_csv", "account_stats.csv")
        rows: List[dict] = []

        if stats_path.exists():
            try:
                with stats_path.open(newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        def _pf(v):
                            try:
                                return float(v)
                            except Exception:
                                return 0.0

                        rows.append({
                            "name":         row.get("account", "Unknown"),
                            "time":         _format_seconds(_pf(row.get("total_time_seconds", 0))),
                            "time_seconds": _pf(row.get("total_time_seconds", 0)),
                            "gold":         int(_pf(row.get("total_gold", 0))),
                            "elixir":       int(_pf(row.get("total_elixir", 0))),
                            "dark":         int(_pf(row.get("total_dark_elixir", 0))),
                            "s0":           int(_pf(row.get("stars_0", 0))),
                            "s1":           int(_pf(row.get("stars_1", 0))),
                            "s2":           int(_pf(row.get("stars_2", 0))),
                            "s3":           int(_pf(row.get("stars_3", 0))),
                            "attacks":      int(_pf(row.get("attacks", 0))),
                            "walls":        int(_pf(row.get("walls_upgraded", 0))),
                        })
            except Exception as exc:
                print(f"Stats load error: {exc}")

        html_path = Path(__file__).parent / "stats_dashboard.html"
        if not html_path.exists():
            self.view.setHtml(
                "<h2 style='color:white;font-family:sans-serif;padding:30px'>"
                "stats_dashboard.html not found</h2>"
            )
            return

        html = html_path.read_text(encoding="utf-8")
        html = html.replace("__STATS_DATA__", json.dumps(rows))

        # Write a temp file so Chart.js CDN fetch works (setHtml blocks remote).
        tmp = Path(__file__).parent / "_stats_tmp.html"
        tmp.write_text(html, encoding="utf-8")
        from PySide6.QtCore import QUrl
        self.view.load(QUrl.fromLocalFile(str(tmp)))


def _format_seconds(seconds: float) -> str:
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


# ═══════════════════════════════════════════════════════════════════════════
# Page 16 — Clan Games Account Selection
# ═══════════════════════════════════════════════════════════════════════════

class ClanGamesAccountSelectPage(QWidget):
    def __init__(self, accounts: list, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        layout.addWidget(_title("Clan Games"))
        layout.addWidget(_subtitle(
            "Select accounts to include in the Clan Games Master Bot.\n"
            "The bot will attack and complete challenges on each selected account."
        ))

        self.checkboxes: Dict[str, QCheckBox] = {}
        grid = QGridLayout()
        for i, name in enumerate(sorted(accounts)):
            cb = QCheckBox(name)
            self.checkboxes[name] = cb
            grid.addWidget(cb, i // 2, i % 2)
        layout.addLayout(grid)

        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.setFixedWidth(240)
        self.select_all_btn.clicked.connect(self._toggle_all)
        layout.addWidget(self.select_all_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.start_btn = QPushButton("Start Clan Games")
        self.start_btn.setObjectName("primary_btn")
        self.start_btn.setFixedWidth(240)
        layout.addWidget(self.start_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.back_btn = QPushButton("Back")
        self.back_btn.setFixedWidth(240)
        layout.addWidget(self.back_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        _page_lbl = QLabel("Page 16", self)
        _page_lbl.setStyleSheet("color: #555; font-size: 9px;")
        _page_lbl.adjustSize()
        _page_lbl.move(5, 5)
        _page_lbl.raise_()

    def _toggle_all(self):
        all_checked = all(cb.isChecked() for cb in self.checkboxes.values())
        for cb in self.checkboxes.values():
            cb.setChecked(not all_checked)
        self.select_all_btn.setText("Deselect All" if not all_checked else "Select All")

    def selected_accounts(self) -> List[str]:
        return [name for name, cb in self.checkboxes.items() if cb.isChecked()]


# ═══════════════════════════════════════════════════════════════════════════
# Page 9 — Clan Games Progress
# ═══════════════════════════════════════════════════════════════════════════

class ClanGamesProgressPage(QWidget):
    """Live status page while the Clan Games Master Bot is running."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(14)

        layout.addWidget(_title("Clan Games Master"))
        layout.addWidget(_subtitle(
            "Attacks and completes challenges on each account,\n"
            "cycling through to trash invalid challenges when needed."
        ))
        layout.addSpacing(10)

        # Mode row
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode:"))
        self.mode_label = QLabel("—")
        self.mode_label.setStyleSheet("color: #f0a500; font-weight: bold;")
        mode_row.addWidget(self.mode_label, 1)
        layout.addLayout(mode_row)

        # Current account row
        acc_row = QHBoxLayout()
        acc_row.addWidget(QLabel("Account:"))
        self.account_label = QLabel("—")
        self.account_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        acc_row.addWidget(self.account_label, 1)
        layout.addLayout(acc_row)

        # Completed accounts row
        done_row = QHBoxLayout()
        done_row.addWidget(QLabel("Completed:"))
        self.completed_label = QLabel("none")
        self.completed_label.setStyleSheet("color: #888;")
        self.completed_label.setWordWrap(True)
        done_row.addWidget(self.completed_label, 1)
        layout.addLayout(done_row)

        layout.addWidget(_separator())

        # Status message
        self.status_label = QLabel("Starting…")
        self.status_label.setStyleSheet("color: #5dade2;")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        layout.addStretch()
        layout.addWidget(_separator())

        # Stop button
        self.stop_btn = QPushButton("Stop Clan Games")
        self.stop_btn.setObjectName("danger_btn")
        self.stop_btn.setFixedWidth(240)
        layout.addWidget(self.stop_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        _page_lbl = QLabel("Page 9", self)
        _page_lbl.setStyleSheet("color: #555; font-size: 9px;")
        _page_lbl.adjustSize()
        _page_lbl.move(5, 5)
        _page_lbl.raise_()


# ═══════════════════════════════════════════════════════════════════════════
# Page 10 — Clan Scout Progress
# ═══════════════════════════════════════════════════════════════════════════

class ClanScouterProgressPage(QWidget):
    """Live status page while the Clan Scouter is running."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(14)

        layout.addWidget(_title("Clan Scouter"))
        layout.addWidget(_subtitle(
            "Searching for Capital Hall 10 open clans on lewis3.\n"
            "Press Space or click Stop to halt immediately."
        ))
        layout.addSpacing(10)

        # Status message
        self.status_label = QLabel("Starting…")
        self.status_label.setStyleSheet("color: #5dade2;")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # Bookmark counter
        self.bookmark_label = QLabel("Bookmarks: 0 / 100")
        self.bookmark_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        layout.addWidget(self.bookmark_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        layout.addStretch()
        layout.addWidget(_separator())

        self.stop_btn = QPushButton("Stop Scouter")
        self.stop_btn.setObjectName("danger_btn")
        self.stop_btn.setFixedWidth(240)
        layout.addWidget(self.stop_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        _page_lbl = QLabel("Page 10", self)
        _page_lbl.setStyleSheet("color: #555; font-size: 9px;")
        _page_lbl.adjustSize()
        _page_lbl.move(5, 5)
        _page_lbl.raise_()


# ═══════════════════════════════════════════════════════════════════════════
# Page 12 — Capital Raid Config
# ═══════════════════════════════════════════════════════════════════════════

class ClanCapitalConfigPage(QWidget):
    """Account selection page for the Capital Raider."""

    def __init__(self, accounts: list, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        layout.addWidget(_title("Capital Raid"))
        layout.addWidget(_subtitle(
            "Select accounts to raid. The bot will switch to each account,\n"
            "navigate to the Clan Capital, and attack all available districts."
        ))

        self.checkboxes: Dict[str, QCheckBox] = {}
        grid = QGridLayout()
        _excluded = {"lewis", "williamleeming"}
        for i, name in enumerate(sorted(a for a in accounts if a not in _excluded)):
            cb = QCheckBox(name)
            self.checkboxes[name] = cb
            grid.addWidget(cb, i // 2, i % 2)
        layout.addLayout(grid)

        layout.addWidget(_separator())

        self.return_clan_cb = QCheckBox("Return to main clan after raids")
        self.return_clan_cb.setChecked(False)
        layout.addWidget(self.return_clan_cb, alignment=Qt.AlignmentFlag.AlignLeft)

        self.start_btn = QPushButton("Start Capital Raid")
        self.start_btn.setObjectName("primary_btn")
        self.start_btn.setFixedWidth(240)
        layout.addWidget(self.start_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.back_btn = QPushButton("Back")
        self.back_btn.setFixedWidth(240)
        layout.addWidget(self.back_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        _page_lbl = QLabel("Page 12", self)
        _page_lbl.setStyleSheet("color: #555; font-size: 9px;")
        _page_lbl.adjustSize()
        _page_lbl.move(5, 5)
        _page_lbl.raise_()

    def selected_accounts(self) -> List[str]:
        return [name for name, cb in self.checkboxes.items() if cb.isChecked()]

    def return_to_main_clan_enabled(self) -> bool:
        return self.return_clan_cb.isChecked()


# ═══════════════════════════════════════════════════════════════════════════
# Page 13 — Capital Raid Progress
# ═══════════════════════════════════════════════════════════════════════════

class ClanCapitalProgressPage(QWidget):
    """Live status page while the Capital Raider is running."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(14)

        layout.addWidget(_title("Capital Raid"))
        layout.addWidget(_subtitle(
            "The bot is attacking Clan Capital districts on selected accounts."
        ))
        layout.addSpacing(10)

        acc_row = QHBoxLayout()
        acc_row.addWidget(QLabel("Account:"))
        self.account_label = QLabel("—")
        self.account_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        acc_row.addWidget(self.account_label, 1)
        layout.addLayout(acc_row)

        layout.addWidget(_separator())

        self.status_label = QLabel("Starting…")
        self.status_label.setStyleSheet("color: #5dade2;")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        layout.addStretch()
        layout.addWidget(_separator())

        self.stop_btn = QPushButton("Stop Capital Raid")
        self.stop_btn.setObjectName("danger_btn")
        self.stop_btn.setFixedWidth(240)
        layout.addWidget(self.stop_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        _page_lbl = QLabel("Page 13", self)
        _page_lbl.setStyleSheet("color: #555; font-size: 9px;")
        _page_lbl.adjustSize()
        _page_lbl.move(5, 5)
        _page_lbl.raise_()


# ═══════════════════════════════════════════════════════════════════════════
# Qt Overlay Widget — replaces tkinter OverlayWindow
# ═══════════════════════════════════════════════════════════════════════════

class QtOverlayWidget(QWidget):
    """Frameless, transparent, always-on-top overlay that draws detection
    rectangles and circles on screen.  Lives on the main thread and is
    driven by signals from the ClanGamesWorker.
    """

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        import pyautogui
        sw, sh = pyautogui.size()
        self.setGeometry(0, 0, sw, sh)

        self._detections: list = []
        self._title_text: str = ""

        # Auto-clear timer: hides the overlay a short time after the last detection
        self._auto_clear_timer = QTimer(self)
        self._auto_clear_timer.setSingleShot(True)
        self._auto_clear_timer.timeout.connect(self.clear)

    # -- public slots --

    @Slot(list, str)
    def draw(self, detections: list, title: str):
        self._detections = detections
        self._title_text = title
        if detections:
            self.update()
            if not self.isVisible():
                self.show()
            # Restart the auto-clear countdown on every new detection
            self._auto_clear_timer.start(800)

    @Slot()
    def clear(self):
        self._auto_clear_timer.stop()
        self._detections = []
        self._title_text = ""
        self.update()
        self.hide()

    # -- screenshot helpers (called from background threads via BlockingQueuedConnection) --

    @Slot()
    def hide_for_screenshot(self):
        """Hide overlay before a screenshot so it doesn't pollute CV captures."""
        self._screenshot_was_visible = self.isVisible()
        if self._screenshot_was_visible:
            self.hide()

    @Slot()
    def restore_after_screenshot(self):
        """Restore overlay visibility after a screenshot."""
        if getattr(self, "_screenshot_was_visible", False):
            self.show()
            self._screenshot_was_visible = False

    # -- painting --

    def paintEvent(self, _event):
        if not self._detections:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # pyautogui captures at physical pixels but Qt paints in logical pixels;
        # dividing by devicePixelRatioF maps physical → logical coordinates.
        dpr = self.devicePixelRatioF()

        def _s(v):
            """Scale a physical-pixel coordinate to a logical-pixel coordinate."""
            return int(round(v / dpr))

        for det in self._detections:
            shape = det.get("shape", "rect")
            label = det.get("label", "")
            score = float(det.get("score", 0.0))

            if shape == "circle":
                cx, cy = _s(det["center"][0]), _s(det["center"][1])
                radius = max(1, _s(int(det.get("radius", 12))))
                painter.setPen(QPen(QColor("#00ffff"), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(cx - radius, cy - radius, radius * 2, radius * 2)
                # Label background
                painter.setBrush(QColor("#002233"))
                painter.drawRect(cx + 10, cy - 20, 140, 20)
                painter.setPen(QPen(QColor("#00ffff")))
                painter.setFont(QFont("Arial", 10, QFont.Weight.Bold))
                painter.drawText(cx + 14, cy - 4, label)
            else:
                x1, y1, x2, y2 = _s(det["bbox"][0]), _s(det["bbox"][1]), _s(det["bbox"][2]), _s(det["bbox"][3])
                painter.setPen(QPen(QColor("#00ff00"), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(x1, y1, x2 - x1, y2 - y1)
                # Label background
                painter.setBrush(QColor("#001a00"))
                painter.drawRect(x1, y1 - 20, 170, 20)
                painter.setPen(QPen(QColor("#00ff00")))
                painter.setFont(QFont("Arial", 10, QFont.Weight.Bold))
                painter.drawText(x1 + 4, y1 - 4, f"{label} ({score:.3f})")

        painter.end()


# ═══════════════════════════════════════════════════════════════════════════
# Main Window — wires everything together
# ═══════════════════════════════════════════════════════════════════════════

class AutoclashGUI(QMainWindow):
    """Central window hosting a QStackedWidget of all pages."""

    PAGE_VILLAGE_SEL = 0
    PAGE_HOME_CONFIG = 1
    PAGE_FILL_ACCOUNTS = 2
    PAGE_ACCOUNT_CONFIG = 3
    PAGE_HOME_PROGRESS = 4
    PAGE_BB_CONFIG = 5
    PAGE_BB_FILL = 6
    PAGE_BB_PROGRESS = 7
    PAGE_STATS = 8
    PAGE_CLAN_GAMES = 9
    PAGE_CLAN_SCOUT = 10
    PAGE_CYCLE_ACCOUNTS = 11
    PAGE_CAPITAL_CONFIG   = 12
    PAGE_CAPITAL_PROGRESS = 13
    PAGE_UPGRADE_ACCOUNTS = 14
    PAGE_MASS_CONFIG      = 15
    PAGE_CLAN_GAMES_SELECT = 16

    # Default sizes per page (w, h)
    PAGE_SIZE = {
        PAGE_VILLAGE_SEL: (700, 500),
        PAGE_HOME_CONFIG: (700, 500),
        PAGE_FILL_ACCOUNTS: (700, 600),
        PAGE_ACCOUNT_CONFIG: (700, 900),
        PAGE_HOME_PROGRESS: (900, 780),
        PAGE_BB_CONFIG: (700, 500),
        PAGE_BB_FILL: (700, 600),
        PAGE_BB_PROGRESS: (900, 780),
        PAGE_STATS: (1200, 900),
        PAGE_CLAN_GAMES: (700, 420),
        PAGE_CLAN_SCOUT: (700, 460),
        PAGE_CYCLE_ACCOUNTS: (700, 620),
        PAGE_CAPITAL_CONFIG:   (700, 600),
        PAGE_CAPITAL_PROGRESS: (700, 460),
        PAGE_UPGRADE_ACCOUNTS: (700, 500),
        PAGE_MASS_CONFIG:      (700, 750),
        PAGE_CLAN_GAMES_SELECT: (700, 600),
    }

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Clash of Clans Automation")
        self.resize(700, 500)

        # --- State ---
        self.worker: Optional[HomeVillageWorker | FillAccountsWorker | CycleAccountsWorker | BuilderBaseWorker | BBFillAccountsWorker | ClanGamesWorker | ClanGamesMasterWorker | ClanScouterWorker | ClanCapitalWorker | UpgradeAccountsWorker | AccountCreationWorker] = None
        self.current_detected_account: Optional[str] = None
        self.session_total_stats = _new_session_stats()
        self.session_account_stats: Dict[str, dict] = {}
        self._nav_history: list = []
        self._star_cache: dict = {}
        self._cgm_completed: list = []
        self._scout_bookmark_count: int = 0
        self._create_account_had_error: bool = False

        # Account settings persistence
        self.config_file = Path(__file__).parent / "account_configs.json"
        self.account_settings: Dict[str, dict] = {}
        self.default_account: str = ""
        self._load_account_settings()

        # --- Pages ---
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        account_list = sorted(APPROVED_ACCOUNTS)

        self.pg_village_sel = VillageSelectionPage()
        self.pg_home_config = HomeConfigPage()
        self.pg_fill_accounts = FillAccountsPage(account_list)
        self.pg_account_config = AccountConfigPage(self._account_names())
        self.pg_home_progress = HomeProgressPage()
        self.pg_bb_config = BBConfigPage()
        self.pg_bb_fill = BBFillAccountsPage(account_list)
        self.pg_bb_progress = BBProgressPage()
        self.pg_stats = StatsPage()
        self.pg_clan_games = ClanGamesProgressPage()
        self.pg_clan_scout = ClanScouterProgressPage()
        self.pg_cycle_accounts = CycleAccountsPage(account_list)
        self.pg_capital_config   = ClanCapitalConfigPage(account_list)
        self.pg_capital_progress = ClanCapitalProgressPage()
        self.pg_upgrade_accounts = UpgradeAccountsPage()
        self.pg_mass_config = MassConfigurePage(self._account_names())
        self.pg_clan_games_select = ClanGamesAccountSelectPage(account_list)

        # Overlay widget (separate top-level window, not in the stack)
        self._overlay = QtOverlayWidget()
        self._install_screenshot_patch()

        for pg in (
            self.pg_village_sel,
            self.pg_home_config,
            self.pg_fill_accounts,
            self.pg_account_config,
            self.pg_home_progress,
            self.pg_bb_config,
            self.pg_bb_fill,
            self.pg_bb_progress,
            self.pg_stats,
            self.pg_clan_games,
            self.pg_clan_scout,
            self.pg_cycle_accounts,
            self.pg_capital_config,
            self.pg_capital_progress,
            self.pg_upgrade_accounts,
            self.pg_mass_config,
            self.pg_clan_games_select,
        ):
            self.stack.addWidget(pg)

        # --- Wire navigation ---
        # Village selection
        self.pg_village_sel.home_btn.clicked.connect(lambda: self._navigate(self.PAGE_HOME_CONFIG))
        self.pg_village_sel.bb_btn.clicked.connect(lambda: self._navigate(self.PAGE_BB_CONFIG))
        self.pg_village_sel.clan_games_btn.clicked.connect(lambda: self._navigate(self.PAGE_CLAN_GAMES_SELECT))
        self.pg_village_sel.clan_scout_btn.clicked.connect(self._start_clan_scouter)
        self.pg_village_sel.capital_raid_btn.clicked.connect(lambda: self._navigate(self.PAGE_CAPITAL_CONFIG))
        self.pg_village_sel.stats_btn.clicked.connect(self._show_stats)

        # Home config
        self.pg_home_config.config_btn.clicked.connect(self._open_account_config)
        self.pg_home_config.start_btn.clicked.connect(self._start_home_automation)
        self.pg_home_config.fill_btn.clicked.connect(lambda: self._navigate(self.PAGE_FILL_ACCOUNTS))
        self.pg_home_config.cycle_btn.clicked.connect(lambda: self._navigate(self.PAGE_CYCLE_ACCOUNTS))
        self.pg_home_config.upgrade_btn.clicked.connect(lambda: self._navigate(self.PAGE_UPGRADE_ACCOUNTS))
        self.pg_home_config.create_account_btn.clicked.connect(self._start_create_account)
        self.pg_home_config.back_btn.clicked.connect(self._go_back)

        # Fill accounts
        self.pg_fill_accounts.start_btn.clicked.connect(self._start_fill_accounts)
        self.pg_fill_accounts.back_btn.clicked.connect(self._go_back)

        # Cycle accounts
        self.pg_cycle_accounts.start_btn.clicked.connect(self._start_cycle_accounts)
        self.pg_cycle_accounts.back_btn.clicked.connect(self._go_back)

        # Upgrade accounts
        self.pg_upgrade_accounts.start_btn.clicked.connect(self._start_upgrade_accounts)
        self.pg_upgrade_accounts.back_btn.clicked.connect(self._go_back)

        # Account config
        self.pg_account_config.account_combo.currentTextChanged.connect(self._on_account_combo_changed)
        self.pg_account_config.save_btn.clicked.connect(self._save_account_settings)
        self.pg_account_config.mass_config_btn.clicked.connect(self._open_mass_config)
        self.pg_account_config.back_btn.clicked.connect(self._go_back)

        # Mass configure
        self.pg_mass_config.apply_btn.clicked.connect(self._apply_mass_config)
        self.pg_mass_config.back_btn.clicked.connect(self._go_back)

        # Home progress
        self.pg_home_progress.config_btn.clicked.connect(self._open_account_config_from_progress)
        self.pg_home_progress.stop_btn.clicked.connect(self._stop_home)
        self.pg_home_progress.scope_combo.currentTextChanged.connect(self._on_scope_changed)

        # BB config
        self.pg_bb_config.start_btn.clicked.connect(self._start_bb_automation)
        self.pg_bb_config.fill_btn.clicked.connect(lambda: self._navigate(self.PAGE_BB_FILL))
        self.pg_bb_config.back_btn.clicked.connect(self._go_back)

        # BB fill
        self.pg_bb_fill.start_btn.clicked.connect(self._start_bb_fill)
        self.pg_bb_fill.back_btn.clicked.connect(self._go_back)

        # BB progress
        self.pg_bb_progress.stop_btn.clicked.connect(self._stop_bb)
        self.pg_bb_progress.back_btn.clicked.connect(self._go_back)

        # Stats
        self.pg_stats.back_btn.clicked.connect(self._go_back)
        self.pg_stats.refresh_btn.clicked.connect(self.pg_stats.refresh)

        # Clan Games account selection
        self.pg_clan_games_select.start_btn.clicked.connect(self._start_clan_games)
        self.pg_clan_games_select.back_btn.clicked.connect(self._go_back)

        # Clan Games progress
        self.pg_clan_games.stop_btn.clicked.connect(self._stop_clan_games)

        # Clan Scout progress
        self.pg_clan_scout.stop_btn.clicked.connect(self._stop_clan_scouter)

        # Capital Raid config + progress
        self.pg_capital_config.start_btn.clicked.connect(self._start_capital_raid)
        self.pg_capital_config.back_btn.clicked.connect(self._go_back)
        self.pg_capital_progress.stop_btn.clicked.connect(self._stop_capital_raid)

        # --- Timer for periodic UI refresh ---
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._periodic_refresh)
        self._refresh_timer.start(500)

        # Start on village selection
        self.stack.setCurrentIndex(self.PAGE_VILLAGE_SEL)

        # Populate account editor with default
        self.pg_account_config.account_combo.clear()
        self.pg_account_config.account_combo.addItems(self._account_names())
        self.pg_account_config.account_combo.setCurrentText(self.default_account)
        self.pg_account_config.populate(self._get_account_settings(self.default_account))

    # ------------------------------------------------------------------
    # Screenshot patch — keeps overlay out of CV captures
    # ------------------------------------------------------------------

    def _install_screenshot_patch(self):
        """Monkey-patch pyautogui.screenshot so the overlay is hidden for the
        duration of every screen capture, then restored.  Called from background
        QThreads via BlockingQueuedConnection which is thread-safe."""
        import pyautogui as _pyautogui
        from PySide6.QtCore import QMetaObject, Qt as _Qt

        _orig = _pyautogui.screenshot
        _ov = self._overlay

        def _patched(*args, **kwargs):
            QMetaObject.invokeMethod(
                _ov, "hide_for_screenshot",
                _Qt.ConnectionType.BlockingQueuedConnection,
            )
            try:
                return _orig(*args, **kwargs)
            finally:
                QMetaObject.invokeMethod(
                    _ov, "restore_after_screenshot",
                    _Qt.ConnectionType.BlockingQueuedConnection,
                )

        _pyautogui.screenshot = _patched

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _navigate(self, page_idx: int, remember: bool = True):
        if remember:
            self._nav_history.append(self.stack.currentIndex())
        w, h = self.PAGE_SIZE.get(page_idx, (700, 500))
        # Clamp to available screen geometry so the window always fits
        screen = self.screen()
        if screen:
            avail = screen.availableGeometry()
            w = min(w, avail.width() - 20)
            h = min(h, avail.height() - 40)
        self.resize(w, h)
        self.stack.setCurrentIndex(page_idx)

    def _go_back(self):
        if self._nav_history:
            idx = self._nav_history.pop()
            self._navigate(idx, remember=False)

    def _show_stats(self):
        self._navigate(self.PAGE_STATS)
        self.pg_stats.refresh()

    # ------------------------------------------------------------------
    # Account settings persistence
    # ------------------------------------------------------------------

    def _account_names(self) -> List[str]:
        names = sorted(self.account_settings.keys())
        return names if names else ["default"]

    def _load_account_settings(self):
        defaults = _get_default_home_settings()
        stored: Dict[str, dict] = {}
        stored_default = ""

        if self.config_file.exists():
            try:
                payload = json.loads(self.config_file.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    stored_default = normalize_account_name(payload.get("default_account", ""))
                    raw = payload.get("accounts", {})
                    if isinstance(raw, dict):
                        for name, cfg in raw.items():
                            norm = normalize_account_name(name)
                            if not norm or not isinstance(cfg, dict):
                                continue
                            merged = defaults.copy()
                            for key in HOME_SETTING_KEYS:
                                if key in cfg:
                                    merged[key] = cfg[key]
                            stored[norm] = merged
            except Exception as exc:
                log(f"GUI: Failed to read account configs: {exc}")

        for acct in sorted(APPROVED_ACCOUNTS):
            norm = normalize_account_name(acct)
            if norm not in stored:
                stored[norm] = defaults.copy()

        if not stored:
            stored["default"] = defaults.copy()

        self.account_settings = stored
        if stored_default and stored_default in self.account_settings:
            self.default_account = stored_default
        else:
            self.default_account = sorted(self.account_settings.keys())[0]

        self._save_account_settings_file()

    def _save_account_settings_file(self):
        payload = {
            "default_account": self.default_account,
            "accounts": self.account_settings,
        }
        try:
            self.config_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:
            log(f"GUI: Failed to save account configs: {exc}")

    def _get_account_settings(self, account: str) -> dict:
        norm = normalize_account_name(account)
        defaults = _get_default_home_settings()
        # Re-read from disk so any runtime changes (e.g. fill_army updating num_battle_points) are picked up
        try:
            fresh = json.loads(self.config_file.read_text(encoding="utf-8"))
            acct_cfg = fresh.get("accounts", {}).get(norm, {})
            self.account_settings[norm] = acct_cfg  # keep in-memory dict in sync
        except Exception:
            acct_cfg = self.account_settings.get(norm, {})
        merged = defaults.copy()
        for key in HOME_SETTING_KEYS:
            if key in acct_cfg:
                merged[key] = acct_cfg[key]
        return merged

    def _apply_settings_to_runtime(self, settings: dict):
        for key in HOME_SETTING_KEYS:
            if key in settings:
                CONFIG[key] = settings[key]

    def _refresh_account_combo(self):
        names = self._account_names()
        self.pg_account_config.account_combo.blockSignals(True)
        self.pg_account_config.account_combo.clear()
        self.pg_account_config.account_combo.addItems(names)
        self.pg_account_config.account_combo.blockSignals(False)

    # ------------------------------------------------------------------
    # Account config page handlers
    # ------------------------------------------------------------------

    def _open_account_config(self):
        selected = normalize_account_name(self.default_account)
        self._refresh_account_combo()
        self.pg_account_config.account_combo.setCurrentText(selected)
        self.pg_account_config.populate(self._get_account_settings(selected))
        self._navigate(self.PAGE_ACCOUNT_CONFIG)

    def _open_account_config_from_progress(self):
        selected = normalize_account_name(
            self.current_detected_account or self.default_account or ""
        )
        if not selected:
            QMessageBox.warning(self, "No Account", "No active account is selected")
            return
        self._refresh_account_combo()
        self.pg_account_config.account_combo.setCurrentText(selected)
        self.pg_account_config.populate(self._get_account_settings(selected))
        self._navigate(self.PAGE_ACCOUNT_CONFIG)

    @Slot(str)
    def _on_account_combo_changed(self, text: str):
        norm = normalize_account_name(text)
        if norm:
            self.pg_account_config.populate(self._get_account_settings(norm))

    def _save_account_settings(self):
        selected = normalize_account_name(self.pg_account_config.account_combo.currentText())
        if not selected:
            QMessageBox.warning(self, "No Account", "Please select an account")
            return
        try:
            settings = self.pg_account_config.collect()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Input", str(exc))
            return

        self.account_settings[selected] = settings.copy()
        self.default_account = selected
        self._save_account_settings_file()
        self._refresh_account_combo()
        log(f"GUI: Saved account settings for '{selected}'")
        QMessageBox.information(self, "Saved", f"Settings saved for account '{selected}'")
        self._go_back()

    def _open_mass_config(self):
        self.pg_mass_config.refresh_accounts(self._account_names())
        self._navigate(self.PAGE_MASS_CONFIG)

    def _apply_mass_config(self):
        key, value = self.pg_mass_config.current_setting()
        accounts = self.pg_mass_config.selected_accounts()
        if not accounts:
            QMessageBox.warning(self, "No Accounts", "Please select at least one account.")
            return
        for acct in accounts:
            norm = normalize_account_name(acct)
            if not norm:
                continue
            cfg = self.account_settings.setdefault(norm, _get_default_home_settings())
            cfg[key] = value
        self._save_account_settings_file()
        # Apply immediately to CONFIG if the bot is running and this is the current account
        if key in HOME_SETTING_KEYS:
            norm_current = normalize_account_name(self.current_detected_account or "")
            if norm_current and norm_current in [normalize_account_name(a) for a in accounts]:
                CONFIG[key] = value
        n = len(accounts)
        log(f"GUI: Mass configure — '{key}' = {value!r} applied to {n} account(s): {accounts}")
        QMessageBox.information(
            self, "Applied",
            f"'{key}' set to {value!r} for {n} account{'s' if n != 1 else ''}."
        )

    # ------------------------------------------------------------------
    # Session stats tracking (Home Village)
    # ------------------------------------------------------------------

    def _reset_home_session(self):
        self.session_total_stats = _new_session_stats()
        self.session_account_stats.clear()
        self._star_cache.pop("home", None)
        self.pg_home_progress.scope_combo.blockSignals(True)
        self.pg_home_progress.scope_combo.clear()
        self.pg_home_progress.scope_combo.addItem("Total Stats")
        self.pg_home_progress.scope_combo.blockSignals(False)

    def _record_home_battle(self, account: str, snapshot: dict, duration: float, _walls: int):
        norm = normalize_account_name(account)
        if not norm or not snapshot:
            return

        if norm not in self.session_account_stats:
            self.session_account_stats[norm] = _new_session_stats()
            # Refresh scope combo
            vals = ["Total Stats"] + sorted(self.session_account_stats.keys())
            self.pg_home_progress.scope_combo.blockSignals(True)
            self.pg_home_progress.scope_combo.clear()
            self.pg_home_progress.scope_combo.addItems(vals)
            self.pg_home_progress.scope_combo.blockSignals(False)

        gold = int(snapshot.get("gold", 0) + snapshot.get("add_gold", 0))
        elixir = int(snapshot.get("elixir", 0) + snapshot.get("add_elixir", 0))
        dark = int(snapshot.get("dark_elixir", 0) + snapshot.get("add_dark", 0))
        stars = int(snapshot.get("stars", 0))
        if stars not in (0, 1, 2, 3):
            stars = 0

        for bucket in (self.session_total_stats, self.session_account_stats[norm]):
            bucket["total_gold"] += gold
            bucket["total_elixir"] += elixir
            bucket["total_dark_elixir"] += dark
            bucket["battle_count"] += 1
            bucket["total_time_seconds"] += float(duration)
            bucket["star_counts"][stars] += 1

        # Auto Min Loot: update min_loot_amount to 50% of the best gold attack so far
        acct_cfg = self.account_settings.setdefault(norm, _get_default_home_settings())
        if acct_cfg.get("dynamic_loot", False) and gold > 0:
            peak = int(acct_cfg.get("dynamic_loot_peak", 0))
            if gold > peak:
                peak = gold
                acct_cfg["dynamic_loot_peak"] = peak
                new_min = peak // 2
                acct_cfg["min_loot_amount"] = new_min
                CONFIG["min_loot_amount"] = new_min
                self._save_account_settings_file()
                log(f"GUI: Auto Min Loot — new peak {peak:,} gold for '{norm}', min loot set to {new_min:,}")

    def _selected_home_stats(self) -> dict:
        scope = self.pg_home_progress.scope_combo.currentText()
        if scope == "Total Stats":
            return self.session_total_stats
        norm = normalize_account_name(scope)
        return self.session_account_stats.get(norm, _new_session_stats())

    # ------------------------------------------------------------------
    # Start Home Village automation
    # ------------------------------------------------------------------

    def _start_home_automation(self):
        self.current_detected_account = None
        Autoclash._default_session.current_account_name = None
        Autoclash._default_session.stop_requested = False
        self._reset_home_session()

        self._save_account_settings_file()
        log("GUI: Starting Home Village automation with auto account detection")

        self.worker = HomeVillageWorker(
            account_settings_getter=self._get_account_settings,
            apply_settings_fn=self._apply_settings_to_runtime,
        )
        self.worker.status_update.connect(self._on_status_update)
        self.worker.battle_completed.connect(self._record_home_battle)
        self.worker.account_detected.connect(self._on_account_detected)
        self.worker.gem_upgrades_disabled.connect(self._on_gem_upgrades_disabled)
        self.worker.overlay_draw.connect(self._overlay.draw)
        self.worker.overlay_clear.connect(self._overlay.clear)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

        self._navigate(self.PAGE_HOME_PROGRESS)

    # ------------------------------------------------------------------
    # Start Fill Accounts
    # ------------------------------------------------------------------

    def _start_fill_accounts(self):
        selected = [
            normalize_account_name(n) for n in self.pg_fill_accounts.selected_accounts()
            if normalize_account_name(n) in APPROVED_ACCOUNTS
        ]
        if not selected:
            QMessageBox.warning(self, "No Accounts", "Select at least one account for Fill Accounts mode")
            return

        self.current_detected_account = None
        Autoclash._default_session.current_account_name = None
        Autoclash._default_session.stop_requested = False
        self._reset_home_session()

        self.worker = FillAccountsWorker(
            selected_accounts=sorted(set(selected)),
            account_settings_getter=self._get_account_settings,
            apply_settings_fn=self._apply_settings_to_runtime,
        )
        self.worker.status_update.connect(self._on_status_update)
        self.worker.battle_completed.connect(self._record_home_battle)
        self.worker.account_detected.connect(self._on_account_detected)
        self.worker.overlay_draw.connect(self._overlay.draw)
        self.worker.overlay_clear.connect(self._overlay.clear)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

        self._navigate(self.PAGE_HOME_PROGRESS)

    # ------------------------------------------------------------------
    # Start Cycle Accounts
    # ------------------------------------------------------------------

    def _start_cycle_accounts(self):
        selected = [
            normalize_account_name(n) for n in self.pg_cycle_accounts.selected_accounts()
            if normalize_account_name(n) in APPROVED_ACCOUNTS
        ]
        if not selected:
            QMessageBox.warning(self, "No Accounts", "Select at least one account for Cycle Accounts mode")
            return

        attacks = self.pg_cycle_accounts.attacks_per_account()

        self.current_detected_account = None
        Autoclash._default_session.current_account_name = None
        Autoclash._default_session.stop_requested = False
        self._reset_home_session()

        self.worker = CycleAccountsWorker(
            selected_accounts=sorted(set(selected)),
            attacks_per_account=attacks,
            account_settings_getter=self._get_account_settings,
            apply_settings_fn=self._apply_settings_to_runtime,
        )
        self.worker.status_update.connect(self._on_status_update)
        self.worker.battle_completed.connect(self._record_home_battle)
        self.worker.account_detected.connect(self._on_account_detected)
        self.worker.overlay_draw.connect(self._overlay.draw)
        self.worker.overlay_clear.connect(self._overlay.clear)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

        self._navigate(self.PAGE_HOME_PROGRESS)

    # ------------------------------------------------------------------
    # Start Upgrade Accounts
    # ------------------------------------------------------------------

    def _start_upgrade_accounts(self):
        raw_behaviours = self.pg_upgrade_accounts.account_behaviours()
        if not raw_behaviours:
            QMessageBox.warning(self, "No Accounts", "Select at least one account for Upgrade Accounts mode")
            return

        # Normalise account names to canonical form
        account_behaviours = {
            normalize_account_name(n): b for n, b in raw_behaviours.items()
        }

        self.current_detected_account = None
        Autoclash._default_session.current_account_name = None
        Autoclash._default_session.stop_requested = False
        self._reset_home_session()

        self.worker = UpgradeAccountsWorker(
            account_behaviours=account_behaviours,
            account_settings_getter=self._get_account_settings,
            apply_settings_fn=self._apply_settings_to_runtime,
        )
        self.worker.status_update.connect(self._on_status_update)
        self.worker.battle_completed.connect(self._record_home_battle)
        self.worker.account_detected.connect(self._on_account_detected)
        self.worker.gem_upgrades_disabled.connect(self._on_gem_upgrades_disabled)
        self.worker.overlay_draw.connect(self._overlay.draw)
        self.worker.overlay_clear.connect(self._overlay.clear)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

        self._navigate(self.PAGE_HOME_PROGRESS)

    # ------------------------------------------------------------------
    # Start Account Creation
    # ------------------------------------------------------------------

    def _start_create_account(self):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.warning(
                self, "Busy",
                "Another automation is already running. Stop it before creating an account."
            )
            return

        reply = QMessageBox.question(
            self, "Create Account",
            "This will automate the full account creation flow in Clash of Clans.\n"
            "Make sure the game window is focused and visible.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        log("GUI: Starting Account Creation worker")
        self._create_account_had_error = False

        # Disable the button while running so it cannot be double-started
        self.pg_home_config.create_account_btn.setEnabled(False)

        self.worker = AccountCreationWorker()
        self.worker.log_message.connect(self._on_create_account_log)
        self.worker.finished.connect(self._on_create_account_finished)
        self.worker.error.connect(self._on_create_account_error)
        self.worker.start()

    @Slot(str)
    def _on_create_account_log(self, message: str):
        log(f"GUI CreateAccount: {message}")

    @Slot()
    def _on_create_account_finished(self):
        if self._create_account_had_error:
            log("GUI: Account Creation worker finished after error")
            self.pg_home_config.create_account_btn.setEnabled(True)
            self.worker = None
            return

        log("GUI: Account Creation worker finished successfully")
        self.pg_home_config.create_account_btn.setEnabled(True)
        self.worker = None
        QMessageBox.information(
            self, "Account Created",
            "Account creation completed successfully!\n"
            "The new account has been saved to created_accounts.json\n"
            "and added to APPROVED_ACCOUNTS in Autoclash.py."
        )

    @Slot(str)
    def _on_create_account_error(self, message: str):
        log(f"GUI: Account Creation error — {message}")
        self._create_account_had_error = True
        self.pg_home_config.create_account_btn.setEnabled(True)
        self.worker = None
        QMessageBox.critical(
            self, "Account Creation Failed",
            f"Account creation failed with error:\n\n{message}"
        )

    # ------------------------------------------------------------------
    # Start BB automation
    # ------------------------------------------------------------------

    def _start_bb_automation(self):
        log("GUI: Starting Builder Base automation")
        Autoclash_BB._default_session.shutdown_requested = False

        self.worker = BuilderBaseWorker()
        self.worker.status_update.connect(self._on_status_update)
        self.worker.battle_completed.connect(self._on_bb_battle_completed)
        self.worker.overlay_draw.connect(self._overlay.draw)
        self.worker.overlay_clear.connect(self._overlay.clear)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

        # Reset BB stats display
        self.pg_bb_progress.battles_label.setText("0")
        self.pg_bb_progress.total_stars_label.setText("0")
        self.pg_bb_progress.avg_stars_label.setText("0.00")
        self.pg_bb_progress.avg_time_label.setText("0:00")
        self.pg_bb_progress.action_label.setText("Starting...")

        Autoclash_BB.stats["start_time"] = time.time()

        self._navigate(self.PAGE_BB_PROGRESS)

    # ------------------------------------------------------------------
    # Start BB Fill
    # ------------------------------------------------------------------

    def _start_bb_fill(self):
        selected = [
            normalize_account_name(n) for n in self.pg_bb_fill.selected_accounts()
            if normalize_account_name(n) in APPROVED_ACCOUNTS
        ]
        if not selected:
            QMessageBox.warning(self, "No Accounts", "Select at least one account for BB Fill mode")
            return

        Autoclash_BB._default_session.shutdown_requested = False
        Autoclash_BB.stats["battles_completed"] = 0
        Autoclash_BB.stats["total_stars"] = 0
        Autoclash_BB.stats["last_battle_stars"] = 0
        Autoclash_BB.stats["star_counts"] = {i: 0 for i in range(7)}
        Autoclash_BB.stats["start_time"] = time.time()

        self.worker = BBFillAccountsWorker(sorted(set(selected)))
        self.worker.status_update.connect(self._on_status_update)
        self.worker.battle_completed.connect(self._on_bb_battle_completed)
        self.worker.account_detected.connect(self._on_account_detected)
        self.worker.overlay_draw.connect(self._overlay.draw)
        self.worker.overlay_clear.connect(self._overlay.clear)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

        self.pg_bb_progress.battles_label.setText("0")
        self.pg_bb_progress.action_label.setText("Starting BB Fill Accounts...")
        self._navigate(self.PAGE_BB_PROGRESS)

    # ------------------------------------------------------------------
    # Stop handlers
    # ------------------------------------------------------------------

    def _stop_home(self):
        reply = QMessageBox.question(
            self, "Confirm Stop", "Are you sure you want to stop the automation?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        if self.worker:
            self.worker.stop()
            self.worker.wait(5000)
        log("GUI: Stop requested by user")

        battles = int(self.session_total_stats.get("battle_count", 0))
        QMessageBox.information(self, "Stopped", f"Automation stopped. Battles completed: {battles}")
        self._full_reset()

    def _stop_bb(self):
        reply = QMessageBox.question(
            self, "Confirm Stop", "Are you sure you want to stop the automation?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        if self.worker:
            self.worker.stop()
            self.worker.wait(5000)
        log("GUI: BB Stop requested by user")

        battles = Autoclash_BB.stats.get("battles_completed", 0)
        QMessageBox.information(self, "Stopped", f"BB automation stopped. Battles: {battles}")
        Autoclash_BB._default_session.shutdown_requested = False
        self._full_reset()

    # ------------------------------------------------------------------
    # Start / Stop Clan Games
    # ------------------------------------------------------------------

    def _start_clan_games(self):
        selected = self.pg_clan_games_select.selected_accounts()
        if not selected:
            QMessageBox.warning(self, "No Accounts Selected", "Please select at least one account.")
            return
        log(f"GUI: Starting Clan Games Master Bot — accounts: {', '.join(selected)}")
        self._cgm_completed: list = []
        self.pg_clan_games.mode_label.setText("—")
        self.pg_clan_games.account_label.setText("—")
        self.pg_clan_games.completed_label.setText("none")
        self.pg_clan_games.status_label.setText("Starting…")

        self.worker = ClanGamesMasterWorker(
            account_settings_getter=self._get_account_settings,
            apply_settings_fn=self._apply_settings_to_runtime,
            selected_accounts=selected,
        )
        self.worker.status_update.connect(self._on_cg_status)
        self.worker.mode_changed.connect(self._on_cg_mode_changed)
        self.worker.account_changed.connect(self._on_cg_account_changed)
        self.worker.account_completed.connect(self._on_cg_account_completed)
        self.worker.overlay_draw.connect(self._overlay.draw)
        self.worker.overlay_clear.connect(self._overlay.clear)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.finished.connect(self._on_cg_finished)
        self.worker.start()

        self._navigate(self.PAGE_CLAN_GAMES)

    def _stop_clan_games(self):
        reply = QMessageBox.question(
            self, "Confirm Stop", "Stop the Clan Games Master Bot?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        if self.worker:
            self.worker.stop()
            self.worker.wait(5000)
        self._overlay.clear()
        log("GUI: Clan Games Master stopped by user")
        completed = getattr(self, "_cgm_completed", [])
        msg = f"Stopped. Completed accounts: {', '.join(completed) if completed else 'none'}"
        QMessageBox.information(self, "Stopped", msg)
        self._full_reset()

    @Slot(str, str)
    def _on_cg_status(self, phase: str, message: str):
        log(f"GUI CG: {phase} - {message}")
        self.pg_clan_games.status_label.setText(message)

    @Slot(str)
    def _on_cg_mode_changed(self, mode: str):
        self.pg_clan_games.mode_label.setText(mode)

    @Slot(str)
    def _on_cg_account_changed(self, account_name: str):
        self.pg_clan_games.account_label.setText(account_name)

    @Slot(str)
    def _on_cg_account_completed(self, account_name: str):
        completed = getattr(self, "_cgm_completed", [])
        if account_name not in completed:
            completed.append(account_name)
        self._cgm_completed = completed
        self.pg_clan_games.completed_label.setText(", ".join(completed))

    @Slot()
    def _on_cg_finished(self):
        log("GUI: Clan Games Master worker finished")
        self._overlay.clear()

    # ------------------------------------------------------------------
    # Clan Scouter
    # ------------------------------------------------------------------

    def _start_clan_scouter(self):
        log("GUI: Starting Clan Scouter")
        self._scout_bookmark_count = 0
        self.pg_clan_scout.status_label.setText("Starting…")
        self.pg_clan_scout.bookmark_label.setText("Bookmarks: 0 / 100")
        self.pg_clan_scout.progress_bar.setValue(0)

        self.worker = ClanScouterWorker()
        self.worker.status_update.connect(self._on_scout_status)
        self.worker.bookmark_changed.connect(self._on_scout_bookmark_changed)
        self.worker.overlay_draw.connect(self._overlay.draw)
        self.worker.overlay_clear.connect(self._overlay.clear)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.finished.connect(self._on_scout_finished)
        self.worker.start()

        self._navigate(self.PAGE_CLAN_SCOUT)

    # ------------------------------------------------------------------
    # Start Capital Raid
    # ------------------------------------------------------------------

    def _start_capital_raid(self):
        selected = [
            normalize_account_name(n) for n in self.pg_capital_config.selected_accounts()
            if normalize_account_name(n) in APPROVED_ACCOUNTS
        ]
        if not selected:
            QMessageBox.warning(self, "No Accounts", "Select at least one account for Capital Raid")
            return

        Autoclash._default_session.current_account_name = None
        Autoclash._default_session.stop_requested = False

        self.worker = ClanCapitalWorker(
            selected_accounts=sorted(set(selected)),
            account_settings_getter=self._get_account_settings,
            apply_settings_fn=self._apply_settings_to_runtime,
            return_to_main_clan=self.pg_capital_config.return_to_main_clan_enabled(),
        )
        self.worker.status_update.connect(self._on_capital_status)
        self.worker.overlay_draw.connect(self._overlay.draw)
        self.worker.overlay_clear.connect(self._overlay.clear)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

        self._navigate(self.PAGE_CAPITAL_PROGRESS)

    @Slot(str, str)
    def _on_capital_status(self, phase: str, message: str):
        log(f"GUI Capital: {phase} — {message}")
        self.pg_capital_progress.status_label.setText(message)
        if phase == "Switching":
            # Extract account name from the message and update label
            parts = message.split("'")
            if len(parts) >= 2:
                self.pg_capital_progress.account_label.setText(parts[1])

    def _stop_capital_raid(self):
        reply = QMessageBox.question(
            self, "Confirm Stop", "Stop the Capital Raid?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        if self.worker:
            self.worker.stop()
            self.worker.wait(5000)
        log("GUI: Capital Raid stopped by user")
        self._full_reset()

    def _stop_clan_scouter(self):
        reply = QMessageBox.question(
            self, "Confirm Stop", "Stop the Clan Scouter?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        if self.worker:
            self.worker.stop()
            self.worker.wait(5000)
        log("GUI: Clan Scouter stopped by user")
        QMessageBox.information(
            self, "Stopped",
            f"Clan Scouter stopped. Bookmarks made: {self._scout_bookmark_count}",
        )
        self._full_reset()

    @Slot(str, str)
    def _on_scout_status(self, phase: str, message: str):
        log(f"GUI Scout: {phase} — {message}")
        self.pg_clan_scout.status_label.setText(message)

    @Slot(int)
    def _on_scout_bookmark_changed(self, count: int):
        self._scout_bookmark_count = count
        self.pg_clan_scout.bookmark_label.setText(f"Bookmarks: {count} / 100")
        self.pg_clan_scout.progress_bar.setValue(count)

    @Slot()
    def _on_scout_finished(self):
        log("GUI: Clan Scouter worker finished")
        QMessageBox.information(
            self, "Done",
            f"Clan Scouter finished. Bookmarks made: {self._scout_bookmark_count}",
        )
        self._full_reset()

    def _full_reset(self):
        self._overlay.clear()
        self.worker = None
        self.current_detected_account = None
        self._nav_history.clear()
        self._navigate(self.PAGE_VILLAGE_SEL, remember=False)

    # ------------------------------------------------------------------
    # Slots connected to workers
    # ------------------------------------------------------------------

    @Slot(str, str)
    def _on_status_update(self, phase: str, message: str):
        log(f"GUI: {phase} - {message}")

        # Update visible progress page
        current = self.stack.currentIndex()
        if current == self.PAGE_HOME_PROGRESS:
            self.pg_home_progress.action_label.setText(message)
        elif current == self.PAGE_BB_PROGRESS:
            self.pg_bb_progress.action_label.setText(message)

    @Slot(str)
    def _on_account_detected(self, account: str):
        self.current_detected_account = account
        # Ensure account exists in settings
        norm = normalize_account_name(account)
        if norm and norm not in self.account_settings:
            self.account_settings[norm] = _get_default_home_settings()
            self._save_account_settings_file()

    @Slot(str)
    def _on_gem_upgrades_disabled(self, account: str):
        """Called when no_gems.png is detected — disable gem_upgrades for that account and save."""
        norm = normalize_account_name(account)
        if not norm:
            return
        if norm not in self.account_settings:
            self.account_settings[norm] = _get_default_home_settings()
        self.account_settings[norm]["gem_upgrades"] = False
        self._save_account_settings_file()
        log(f"GUI: Gem upgrades disabled for account '{norm}' (no gems remaining) and saved")

    @Slot(int, int)
    def _on_bb_battle_completed(self, count: int, stars: int):
        """Update BB progress labels after each battle."""
        # The actual BB stats dict is already updated by the worker
        pass  # Periodic refresh timer handles display updates

    @Slot(str)
    def _on_error(self, message: str):
        log(f"GUI: Worker error - {message}")

    @Slot()
    def _on_worker_finished(self):
        log("GUI: Worker finished")
        self._overlay.clear()
        # Don't auto-navigate — user may be reading stats

    @Slot(str)
    def _on_scope_changed(self, _text: str):
        self._star_cache.pop("home", None)
        self._refresh_home_progress()

    # ------------------------------------------------------------------
    # Periodic UI refresh (replaces old poll_status_queue)
    # ------------------------------------------------------------------

    def _periodic_refresh(self):
        current = self.stack.currentIndex()
        if current == self.PAGE_HOME_PROGRESS:
            self._refresh_home_progress()
        elif current == self.PAGE_BB_PROGRESS:
            self._refresh_bb_progress()

    def _refresh_home_progress(self):
        stats = self._selected_home_stats()
        count = int(stats.get("battle_count", 0))
        self.pg_home_progress.battles_label.setText(str(count))

        # Stars
        star_counts = stats.get("star_counts", {0: 0, 1: 0, 2: 0, 3: 0})
        total_b = sum(star_counts.values())
        for star in (3, 2, 1, 0):
            c = star_counts.get(star, 0)
            pct = (c / max(total_b, 1)) * 100 if total_b > 0 else 0.0
            self.pg_home_progress.star_bars[star].setValue(int(pct * 10))
            self.pg_home_progress.star_pct_labels[star].setText(f"{pct:.1f}%")

        # Loot
        gold = int(stats.get("total_gold", 0))
        elixir = int(stats.get("total_elixir", 0))
        dark = int(stats.get("total_dark_elixir", 0))
        self.pg_home_progress.gold_label.setText(f"{gold:,}")
        self.pg_home_progress.elixir_label.setText(f"{elixir:,}")
        self.pg_home_progress.dark_label.setText(f"{dark:,}")

        total_time = float(stats.get("total_time_seconds", 0.0))
        hours = max(total_time / 3600.0, 1e-9)
        if total_time > 0:
            self.pg_home_progress.gold_ph.setText(f"Gold/hr: {gold / hours:,.0f}")
            self.pg_home_progress.elixir_ph.setText(f"Elixir/hr: {elixir / hours:,.0f}")
            self.pg_home_progress.dark_ph.setText(f"Dark/hr: {dark / hours:,.0f}")
        else:
            self.pg_home_progress.gold_ph.setText("Gold/hr: 0")
            self.pg_home_progress.elixir_ph.setText("Elixir/hr: 0")
            self.pg_home_progress.dark_ph.setText("Dark/hr: 0")

        safe = max(count, 1)
        if count > 0:
            self.pg_home_progress.avg_gold.setText(f"Gold: {gold / safe:,.0f}")
            self.pg_home_progress.avg_elixir.setText(f"Elixir: {elixir / safe:,.0f}")
            self.pg_home_progress.avg_dark.setText(f"Dark: {dark / safe:,.0f}")
        else:
            self.pg_home_progress.avg_gold.setText("Gold: 0")
            self.pg_home_progress.avg_elixir.setText("Elixir: 0")
            self.pg_home_progress.avg_dark.setText("Dark: 0")

        self.pg_home_progress.time_label.setText(f"Runtime: {total_time / 60.0:.1f} min")

    def _refresh_bb_progress(self):
        try:
            bb = Autoclash_BB.stats
            battles = max(bb.get("battles_completed", 0), 1)
            total_stars = bb.get("total_stars", 0)

            self.pg_bb_progress.battles_label.setText(str(bb.get("battles_completed", 0)))
            self.pg_bb_progress.total_stars_label.setText(str(total_stars))
            self.pg_bb_progress.avg_stars_label.setText(f"{total_stars / battles:.2f}")

            start_time = bb.get("start_time", time.time())
            elapsed = int(time.time() - start_time)
            avg_sec = elapsed / max(battles, 1)
            m, s = divmod(int(avg_sec), 60)
            self.pg_bb_progress.avg_time_label.setText(f"{m}:{s:02d}")

            star_counts = bb.get("star_counts", {i: 0 for i in range(7)})
            total_b = sum(star_counts.values())
            for star in (6, 5, 4, 3, 2, 1, 0):
                c = star_counts.get(star, 0)
                pct = (c / max(total_b, 1)) * 100 if total_b > 0 else 0.0
                self.pg_bb_progress.star_bars[star].setValue(int(pct * 10))
                self.pg_bb_progress.star_pct_labels[star].setText(f"{pct:.1f}%")

            elapsed_min = elapsed / 60.0
            self.pg_bb_progress.time_label.setText(f"Runtime: {elapsed_min:.1f} min")
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════

def main():
    """Main entry point for the GUI application."""
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLE)

    # Set a default font with a valid point-size so Qt internals never
    # encounter pointSize() == -1  (the QSS uses px which leaves it unset).
    default_font = QFont("Segoe UI", 10)
    app.setFont(default_font)

    window = AutoclashGUI()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
