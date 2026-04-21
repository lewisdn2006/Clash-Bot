#!/usr/bin/env python3
"""
Typing Method Test Script
=========================
Tests three different methods for sending text input to the active window.

BEFORE running this script:
  - Open a plain text editor (e.g. Notepad) OR the in-game name-entry field
    in Clash of Clans.
  - Click inside the text field so it is focused.
  - Switch back to this terminal window and run the script.
  - You have 5 seconds to switch to the target window!

Each method will type the test string "DJBillGates30" with a 2-second gap
between them.  Watch the target window to see which method produces the
correct output.  Then update accountcreator.py to use the method that works.

Required packages (install with pip):
    pip install pyautogui pyperclip
"""

# pyperclip is optional — Test 2 is skipped with a warning if not installed.

import sys
import time

import pyautogui

# ---------------------------------------------------------------------------
# Test string
# ---------------------------------------------------------------------------
TEST_STRING = "DJBillGates30"

# ---------------------------------------------------------------------------
# Countdown
# ---------------------------------------------------------------------------
print()
print("=" * 60)
print("  Clash of Clans — Typing Method Test")
print("=" * 60)
print()
print("ACTION REQUIRED:")
print(f"  Open a text editor or the in-game name entry field,")
print(f"  click inside it to focus it, then switch back here.")
print()
print("WARNING: Switch to the target window within 5 seconds!")
print()

for count in range(5, 0, -1):
    print(f"  {count}...")
    time.sleep(1)

print("  GO!")
print()

# ---------------------------------------------------------------------------
# Test 1 — pyautogui.typewrite
# ---------------------------------------------------------------------------
print("-" * 60)
print("Test 1 — pyautogui.typewrite (standard method)")
print(f"  Typing: {TEST_STRING!r}")
print("  Note: Works in most applications; may fail in DirectInput games.")
pyautogui.typewrite(TEST_STRING, interval=0.05)
print("  Test 1 done.")
time.sleep(2)

# ---------------------------------------------------------------------------
# Test 2 — pyperclip clipboard paste
# ---------------------------------------------------------------------------
print()
print("-" * 60)
print("Test 2 — pyperclip clipboard paste (ctrl+v)")
print(f"  Typing: {TEST_STRING!r}")
print("  Note: Works in more game windows than typewrite.")
try:
    import pyperclip  # type: ignore
    pyperclip.copy(TEST_STRING)
    pyautogui.hotkey("ctrl", "v")
    print("  Test 2 done.")
except ImportError:
    print("  WARNING: pyperclip is not installed — skipping Test 2.")
    print("  Install with:  pip install pyperclip")
time.sleep(2)

# ---------------------------------------------------------------------------
# Test 3 — hotkey char-by-char (most compatible with DirectInput games)
# ---------------------------------------------------------------------------
print()
print("-" * 60)
print("Test 3 — hotkey char-by-char (DirectInput compatible)")
print(f"  Typing: {TEST_STRING!r}")
print("  Note: Most compatible method for games using DirectInput.")

for char in TEST_STRING:
    if char.isupper():
        # Uppercase letter — shift+letter
        pyautogui.hotkey("shift", char.lower())
    else:
        # Lowercase letter or digit — plain key press
        pyautogui.press(char)
    time.sleep(0.05)

print("  Test 3 done.")
time.sleep(2)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print()
print("=" * 60)
print("  All three tests complete!")
print()
print("  Look at the text that appeared in your target window:")
print()
print(f"  Expected output per test: {TEST_STRING!r}")
print()
print("  Which method(s) produced the correct output?")
print()
print("  Method 1 (typewrite)     — configure accountcreator.py to use")
print("                             pyautogui.typewrite(text, interval=0.05)")
print()
print("  Method 2 (clipboard)     — configure accountcreator.py to use")
print("                             pyperclip.copy(text) then")
print("                             pyautogui.hotkey('ctrl', 'v')")
print()
print("  Method 3 (char-by-char)  — configure accountcreator.py to use")
print("                             the hotkey loop (shift+char for uppercase,")
print("                             pyautogui.press(char) for lowercase/digits)")
print()
print("  Update the pyautogui.typewrite() calls in accountcreator.py to use")
print("  whichever method worked in the game window.")
print("=" * 60)
