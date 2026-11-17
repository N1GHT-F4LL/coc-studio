"""Release stuck keyboard modifiers (ALT etc.) — the coc-studio focus-steal
path presses ALT via keybd_event; a process killed between down and up leaves
the modifier held system-wide (keyboard appears dead). Sending one down+up
cycle per modifier clears the stuck state.
"""
import ctypes

user32 = ctypes.windll.user32
KEYEVENTF_KEYUP = 0x0002
MODS = {"ALT": 0x12, "CTRL": 0x11, "SHIFT": 0x10, "WIN": 0x5B}

# Async key state: high bit = currently down
for name, vk in MODS.items():
    state = user32.GetAsyncKeyState(vk)
    stuck = bool(state & 0x8000)
    # down+up cycle — harmless if not stuck, releases it if it is
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
    print(f"{name}: was_stuck={stuck} -> released")

print("DONE — try typing now.")
