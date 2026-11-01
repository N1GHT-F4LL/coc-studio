"""Windows host-side input helpers.

The coc-studio backend runs on the SAME PC as the Memu emulator, and Memu
converts host mouse-wheel scrolls over the game view into pinch gestures —
the ONLY zoom path that works on this emulator (its touch driver ignores
injected multi-touch from inside the guest: sendevent / evdev writes are
silently discarded). These helpers drive the HOST mouse wheel so the bot can
zoom the game exactly like a human would.
"""
import ctypes
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
MOUSEEVENTF_WHEEL = 0x0800
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002

_cache = {"hwnd": 0}


def force_foreground(hwnd, attempts=3):
    """Force ``hwnd`` to the foreground. Windows blocks background processes
    from stealing focus; the simulated ALT tap unlocks SetForegroundWindow,
    plus the AttachThreadInput trick. Returns True when confirmed."""
    for _ in range(attempts):
        if user32.GetForegroundWindow() == hwnd:
            return True
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        fg_tid = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
        my_tid = ctypes.windll.kernel32.GetCurrentThreadId()
        attached = False
        if fg_tid and fg_tid != my_tid:
            attached = bool(user32.AttachThreadInput(my_tid, fg_tid, True))
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        if attached:
            user32.AttachThreadInput(my_tid, fg_tid, False)
        time.sleep(0.3)
    return user32.GetForegroundWindow() == hwnd


def window_at(x, y):
    return user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))


def is_child_or_self(parent, child):
    if not parent or not child:
        return False
    if parent == child:
        return True
    return bool(user32.IsChild(parent, child))


def find_game_window(title_substr="memu"):
    """HWND of the first visible top-level window whose title contains
    ``title_substr`` (case-insensitive). Cached — Memu's HWND is stable while
    it runs."""
    if _cache["hwnd"] and user32.IsWindowVisible(_cache["hwnd"]):
        return _cache["hwnd"]

    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 2)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if title_substr.lower() in buf.value.lower() and n > 0:
                found.append(hwnd)
                return False
        return True

    user32.EnumWindows(cb, 0)
    _cache["hwnd"] = found[0] if found else 0
    return _cache["hwnd"]


def game_view_point(hwnd, y_offset=40):
    """Screen coordinates of (roughly) the centre of the game view inside the
    Memu window (the client area includes Memu's own tab strip, so shift a
    little down)."""
    rect = wintypes.RECT()
    if not hwnd or not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    pt = wintypes.POINT((rect.right - rect.left) // 2,
                        (rect.bottom - rect.top) // 2 + y_offset)
    if not user32.ClientToScreen(hwnd, ctypes.byref(pt)):
        return None
    return pt.x, pt.y


def wheel_scroll_at(x, y, notches, delta=-120):
    """Scroll the host mouse wheel ``notches`` times with the cursor parked at
    screen point (x, y). Returns the previous cursor position so the caller
    can restore it."""
    old = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(old))
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.06)
    for _ in range(max(1, int(notches))):
        user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, int(delta), 0)
        time.sleep(0.15)
    return old.x, old.y


def restore_cursor(pos):
    if pos:
        user32.SetCursorPos(int(pos[0]), int(pos[1]))
