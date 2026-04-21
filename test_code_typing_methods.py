#!/usr/bin/env python3
"""
Test numeric typing methods for game input fields.

Purpose
-------
Use this script to test different ways of typing a verification code (e.g. 647815)
into the currently focused input box. It runs each method with a countdown so you
can click into the target field first.

Usage
-----
python test_code_typing_methods.py --code 1
python test_code_typing_methods.py --code 1 --method all
python test_code_typing_methods.py --code 647815 --method ctrl_v

Notes
-----
- Keep the game/emulator window visible.
- Click the code input field during the countdown before each method.
- Press Ctrl+C to stop.
"""

from __future__ import annotations

import argparse
import ctypes
import time
from typing import Callable, Dict

import pyautogui


try:
    import pyperclip  # pip install pyperclip
    HAS_PYPERCLIP = True
except Exception:
    HAS_PYPERCLIP = False

try:
    import keyboard as kb  # pip install keyboard
    HAS_KEYBOARD_LIB = True
except Exception:
    HAS_KEYBOARD_LIB = False

try:
    from pynput.keyboard import Controller as PynputController  # pip install pynput
    HAS_PYNPUT = True
except Exception:
    HAS_PYNPUT = False

try:
    from pywinauto.keyboard import send_keys as pywinauto_send_keys  # type: ignore[import-not-found]  # pip install pywinauto
    HAS_PYWINAUTO = True
except Exception:
    HAS_PYWINAUTO = False


pyautogui.FAILSAFE = False

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
WM_PASTE = 0x0302
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_KEYUP = 0x0002


def _foreground_hwnd() -> int:
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if not hwnd:
        raise RuntimeError("No foreground window handle")
    return hwnd


def _digit_vk(ch: str) -> int:
    return 0x30 + int(ch)


def _countdown(seconds: int = 3) -> None:
    for i in range(seconds, 0, -1):
        print(f"  Starting in {i}...")
        time.sleep(1)


def _normalize_digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def method_typewrite(code: str) -> None:
    pyautogui.typewrite(code, interval=0.05)


def method_write(code: str) -> None:
    pyautogui.write(code, interval=0.03)


def method_press_keys(code: str) -> None:
    for ch in code:
        pyautogui.press(ch)
        time.sleep(0.03)


def method_wm_char(code: str) -> None:
    """Send characters via WM_CHAR to the current foreground window."""
    user32 = ctypes.windll.user32
    hwnd = _foreground_hwnd()
    for ch in code:
        user32.PostMessageW(hwnd, WM_CHAR, ord(ch), 1)
        time.sleep(0.03)


def method_wm_keydown_up(code: str) -> None:
    """Send digits with WM_KEYDOWN/WM_KEYUP to foreground window."""
    user32 = ctypes.windll.user32
    hwnd = _foreground_hwnd()
    for ch in code:
        vk = _digit_vk(ch)
        user32.PostMessageW(hwnd, WM_KEYDOWN, vk, 0)
        user32.PostMessageW(hwnd, WM_KEYUP, vk, 0)
        time.sleep(0.03)


def method_sendinput_vk(code: str) -> None:
    """Send virtual-key events through keybd_event."""
    user32 = ctypes.windll.user32
    for ch in code:
        vk = _digit_vk(ch)
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.03)


def method_sendinput_scancode(code: str) -> None:
    """Send scan-code key events via SendInput (often better for games)."""

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_uint),
            ("time", ctypes.c_uint),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [
            ("type", ctypes.c_uint),
            ("ki", KEYBDINPUT),
        ]

    user32 = ctypes.windll.user32
    map_vk = user32.MapVirtualKeyW
    send_input = user32.SendInput

    def send_key_scan(vk: int, key_up: bool = False) -> None:
        scan = map_vk(vk, 0)
        flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if key_up else 0)
        extra = ctypes.c_ulong(0)
        ki = KEYBDINPUT(0, scan, flags, 0, ctypes.pointer(extra))
        inp = INPUT(1, ki)
        sent = send_input(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        if sent != 1:
            raise RuntimeError("SendInput failed")

    for ch in code:
        vk = _digit_vk(ch)
        send_key_scan(vk, key_up=False)
        send_key_scan(vk, key_up=True)
        time.sleep(0.03)


def method_hotkey_shift_insert(code: str) -> None:
    if not HAS_PYPERCLIP:
        raise RuntimeError("pyperclip not installed")
    pyperclip.copy(code)
    pyautogui.hotkey("shift", "insert")


def method_hotkey_ctrl_v(code: str) -> None:
    if not HAS_PYPERCLIP:
        raise RuntimeError("pyperclip not installed")
    pyperclip.copy(code)
    pyautogui.hotkey("ctrl", "v")


def method_numpad_keys(code: str) -> None:
    # Some emulators listen differently to numpad events.
    for ch in code:
        pyautogui.press(f"num{ch}")
        time.sleep(0.03)


def method_keyboard_write(code: str) -> None:
    if not HAS_KEYBOARD_LIB:
        raise RuntimeError("keyboard not installed")
    kb.write(code, delay=0.03)


def method_pynput_type(code: str) -> None:
    if not HAS_PYNPUT:
        raise RuntimeError("pynput not installed")
    ctl = PynputController()
    ctl.type(code)


def method_pywinauto_send_keys(code: str) -> None:
    if not HAS_PYWINAUTO:
        raise RuntimeError("pywinauto not installed")
    pywinauto_send_keys(code, with_spaces=True, pause=0.03)


def method_wm_paste(code: str) -> None:
    """Paste text using WM_PASTE on foreground window."""
    if not HAS_PYPERCLIP:
        raise RuntimeError("pyperclip not installed")
    pyperclip.copy(code)
    hwnd = _foreground_hwnd()
    ctypes.windll.user32.PostMessageW(hwnd, WM_PASTE, 0, 0)


def run_method(name: str, fn: Callable[[str], None], code: str, prep_seconds: int) -> bool:
    print("\n" + "=" * 72)
    print(f"Method: {name}")
    print(f"Code:   {code}")
    print("Click the target input box now.")
    _countdown(prep_seconds)
    try:
        fn(code)
        print("Result: SENT")
        return True
    except Exception as exc:
        print(f"Result: FAILED ({exc})")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Test number typing methods for code entry fields")
    parser.add_argument("--code", default="1", help="Code to type (digits or spaced digits)")
    parser.add_argument(
        "--method",
        default="all",
        choices=[
            "all",
            "typewrite",
            "write",
            "press_keys",
            "wm_char",
            "wm_keydown_up",
            "sendinput_vk",
            "sendinput_scancode",
            "numpad_keys",
            "keyboard_write",
            "pynput_type",
            "pywinauto_send_keys",
            "ctrl_v",
            "shift_insert",
            "wm_paste",
        ],
        help="Method to run",
    )
    parser.add_argument("--prep-seconds", type=int, default=3, help="Countdown before each method")
    args = parser.parse_args()

    code_digits = _normalize_digits(args.code)
    if not code_digits:
        raise SystemExit("No digits found in --code")

    methods: Dict[str, Callable[[str], None]] = {
        "typewrite": method_typewrite,
        "write": method_write,
        "press_keys": method_press_keys,
        "wm_char": method_wm_char,
        "wm_keydown_up": method_wm_keydown_up,
        "sendinput_vk": method_sendinput_vk,
        "sendinput_scancode": method_sendinput_scancode,
        "numpad_keys": method_numpad_keys,
        "keyboard_write": method_keyboard_write,
        "pynput_type": method_pynput_type,
        "pywinauto_send_keys": method_pywinauto_send_keys,
        "ctrl_v": method_hotkey_ctrl_v,
        "shift_insert": method_hotkey_shift_insert,
        "wm_paste": method_wm_paste,
    }

    if args.method == "all":
        order = [
            "typewrite",
            "write",
            "press_keys",
            "wm_char",
            "wm_keydown_up",
            "sendinput_vk",
            "sendinput_scancode",
            "numpad_keys",
            "keyboard_write",
            "pynput_type",
            "pywinauto_send_keys",
            "ctrl_v",
            "shift_insert",
            "wm_paste",
        ]
    else:
        order = [args.method]

    print("Testing code entry methods...")
    print("Tip: Clear the input field between methods if needed.")

    results = {}
    for method_name in order:
        ok = run_method(method_name, methods[method_name], code_digits, args.prep_seconds)
        results[method_name] = ok
        if method_name != order[-1]:
            input("Press Enter for next method...")

    print("\n" + "=" * 72)
    print("Summary")
    for method_name in order:
        state = "OK" if results[method_name] else "FAILED"
        print(f"  {method_name:14s}: {state}")


if __name__ == "__main__":
    main()
