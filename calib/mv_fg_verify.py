"""Verify the MEmu window is foreground + its content matches the adb frame."""
import ctypes
import os
import subprocess
import sys
import time

ctypes.windll.user32.SetProcessDPIAware()
import ctypes.wintypes as wt
import cv2
import mss
import numpy as np

BACKEND = r'C:\Users\antoinenguyen_09\Downloads\coc-studio\backend'
sys.path.insert(0, BACKEND)
from core.vision import vision  # noqa: E402

vision.load_assets(os.path.join(BACKEND, 'assets'))


def adb_frame():
    p = subprocess.run(['adb', '-s', '127.0.0.1:21503', 'exec-out', 'screencap', '-p'],
                       capture_output=True, stdin=subprocess.DEVNULL, timeout=30)
    return cv2.imdecode(np.frombuffer(p.stdout, np.uint8), cv2.IMREAD_COLOR)


user32 = ctypes.windll.user32
hwnd = None


@ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
def cb(h, _):
    global hwnd
    if user32.IsWindowVisible(h):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(h, buf, 256)
        if buf.value == 'MEmu':
            hwnd = h
    return True


user32.EnumWindows(cb, 0)
assert hwnd, 'MEmu window not found'
if user32.IsIconic(hwnd):
    user32.ShowWindow(hwnd, 9)
    time.sleep(0.8)
user32.SetForegroundWindow(hwnd)
time.sleep(1.0)
rect = wt.RECT()
user32.GetWindowRect(hwnd, ctypes.byref(rect))
print(f'rect: ({rect.left},{rect.top})-({rect.right},{rect.bottom})')

mon = {'left': rect.left, 'top': rect.top,
       'width': rect.right - rect.left, 'height': rect.bottom - rect.top}
with mss.mss() as sct:
    cap = np.array(sct.grab(mon))[:, :, :3]
cv2.imwrite(r'C:\Users\antoinenguyen_09\Downloads\coc-studio\calib\mv_fg_check.png', cap)

adb = adb_frame()
ag = cv2.cvtColor(adb, cv2.COLOR_BGR2GRAY)
g = cv2.cvtColor(cap, cv2.COLOR_BGR2GRAY)
best = None
for i in range(61):
    s = round(0.9 + 0.002 * i, 3)
    t = cv2.resize(ag, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    th, tw = t.shape[:2]
    if th >= g.shape[0] or tw >= g.shape[1]:
        continue
    r = cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED)
    _, c, _, ml = cv2.minMaxLoc(r)
    if best is None or c > best[0]:
        best = (c, ml, s)
print(f'MEmu content vs adb frame: conf {best[0]:.3f} at {best[1]} scale {best[2]:.3f} '
      f'({">= 0.9: the capture shows the real MEmu window" if best[0] >= 0.9 else "< 0.9: still covered — bring MEmu to front manually"})')
