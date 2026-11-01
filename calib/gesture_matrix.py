# -*- coding: utf-8 -*-
"""calib/gesture_matrix.py — find a zoom gesture that Memu's touch driver
actually honours. Sends several candidate gestures on the village and measures
each one's effect (content scale + pan delta) from before/after frames.
Run:  .venv/Scripts/python.exe calib/gesture_matrix.py"""
import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.normpath(os.path.join(HERE, "..", "backend"))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

import logging  # noqa: E402
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("matrix")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import urllib.request  # noqa: E402
try:
    req = urllib.request.Request("http://127.0.0.1:8000/api/run/stop", method="POST",
                                 data=b"{}", headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=3)
except Exception:
    pass
out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                     stdin=subprocess.DEVNULL).stdout
for pid in {l.split()[-1] for l in out.splitlines()
            if ":8000" in l and "LISTENING" in l.upper()}:
    subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True,
                   stdin=subprocess.DEVNULL)

import blocks  # noqa: F401,E402
from device_manager import manager, load_settings  # noqa: E402
from engine.context import RuntimeContext  # noqa: E402
from blocks.coc_blocks import EnsureHome  # noqa: E402

ok, reason = manager.connect()
print(f"[matrix] connect {ok} ({reason})")
if not ok:
    sys.exit("no device")
dev, ui = manager.device, manager.ui_manager
settings = load_settings()
ctx = RuntimeContext(device=dev, ui_manager=ui, vision=None,
                     ocr_read=lambda *a, **k: (None, 0.0), settings=settings,
                     logger=log, stop_event=threading.Event(), vars={}, emit=lambda ev: None)
if not EnsureHome().run(ctx, {"zoom_out": False, "timeout": 10})["home"]:
    sys.exit("no home")

EV_DEV, MAXX, MAXY = dev._find_touch_input_device()
SW, SH = dev.get_screen_size()


def send(codes):
    """codes: list of (type, code, value) -> one adb shell of sendevents."""
    parts = [f"sendevent {EV_DEV} {t} {c} {v}" for t, c, v in codes]
    dev._run_adb(["shell", " && ".join(parts)])


EV_ABS, EV_REL, EV_SYN, EV_KEY = 3, 2, 0, 1
SLOT, X, Y, MAJOR, ID = 0x2f, 0x35, 0x36, 0x30, 0x39
WHEEL = 0x08
BT = 0x14a


def pixel(x, y):
    return dev._pixel_to_event(x, y, MAXX, MAXY, SW, SH)


def pinch_b(split_down, btn_touch=False, ids=(0, 1)):
    """Two fingers from +-600 to +-120 (zoom out). split_down: emit the two
    finger-down frames separately (True) or in one SYN (False)."""
    cx, cy = 800, 450
    cmds = []
    se = lambda t, c, v: cmds.append(f"sendevent {EV_DEV} {t} {c} {v}")
    run = lambda: dev._run_adb(["shell", ";".join(cmds)])
    if btn_touch:
        se(EV_KEY, BT, 1)
    xa, ya = pixel(cx - 600, cy)
    xb, yb = pixel(cx + 600, cy)
    if split_down:
        se(EV_ABS, SLOT, 0); se(EV_ABS, X, xa); se(EV_ABS, Y, ya)
        se(EV_ABS, MAJOR, 10); se(EV_ABS, ID, ids[0]); se(EV_SYN, 0, 0)
        se(EV_ABS, SLOT, 1); se(EV_ABS, X, xb); se(EV_ABS, Y, yb)
        se(EV_ABS, MAJOR, 10); se(EV_ABS, ID, ids[1]); se(EV_SYN, 0, 0)
    else:
        se(EV_ABS, SLOT, 0); se(EV_ABS, X, xa); se(EV_ABS, Y, ya)
        se(EV_ABS, MAJOR, 10); se(EV_ABS, ID, ids[0])
        se(EV_ABS, SLOT, 1); se(EV_ABS, X, xb); se(EV_ABS, Y, yb)
        se(EV_ABS, MAJOR, 10); se(EV_ABS, ID, ids[1]); se(EV_SYN, 0, 0)
    for i in range(1, 16):
        d = int(600 + (120 - 600) * i / 15)
        xa, ya = pixel(cx - d, cy)
        xb, yb = pixel(cx + d, cy)
        se(EV_ABS, SLOT, 0); se(EV_ABS, X, xa); se(EV_ABS, Y, ya)
        se(EV_ABS, SLOT, 1); se(EV_ABS, X, xb); se(EV_ABS, Y, yb)
        se(EV_SYN, 0, 0)
    se(EV_ABS, SLOT, 0); se(EV_ABS, ID, -1)
    se(EV_ABS, SLOT, 1); se(EV_ABS, ID, -1)
    if btn_touch:
        se(EV_KEY, BT, 0)
    se(EV_SYN, 0, 0)
    run()


def wheel(steps, value=-1):
    parts = []
    for _ in range(steps):
        parts.append(f"sendevent {EV_DEV} {EV_REL} {WHEEL} {value}")
        parts.append(f"sendevent {EV_DEV} {EV_SYN} 0 0")
        parts.append("sleep 0.12")
    dev._run_adb(["shell", " && ".join(parts)])


def measure(tag, before, after):
    ga, gb = (cv2.cvtColor(x, cv2.COLOR_BGR2GRAY) for x in (before, after))
    patches = [(800, 450), (500, 300), (1100, 300), (500, 600), (1100, 600)]
    half = 70
    scales, deltas = [], []
    for (px, py) in patches:
        pa = ga[py-half:py+half, px-half:px+half]
        best = (0.0, 1.0, (0, 0))
        for s in (0.60, 0.70, 0.80, 0.90, 0.95, 1.00):
            t = cv2.resize(pa, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(gb, t, cv2.TM_CCOEFF_NORMED)
            _, mv, _, ml = cv2.minMaxLoc(res)
            if mv > best[0]:
                best = (mv, s, (ml[0] + half - px, ml[1] + half - py))
        if best[0] >= 0.70:
            scales.append(best[1])
            deltas.append(best[2])
    med_scale = float(np.median(scales)) if scales else 1.0
    med_d = (float(np.median([d[0] for d in deltas])) if deltas else 0.0,
             float(np.median([d[1] for d in deltas])) if deltas else 0.0)
    if med_scale <= 0.95:
        kind = "ZOOM"
    elif abs(med_d[0]) > 20 or abs(med_d[1]) > 20:
        kind = "PAN"
    else:
        kind = "NONE"
    print(f"  [{tag}] scale={med_scale:.2f} delta=({med_d[0]:.0f},{med_d[1]:.0f}) "
          f"scales={sorted(set(round(s, 2) for s in scales))} -> {kind}")
    return kind


print("[matrix] baseline captured; testing gesture variants (village view)")
before = ui.get_screen()
pinch_b(split_down=True)
time.sleep(1.2)
after = ui.get_screen()
measure("A: two down frames (current impl)", before, after)
before = after

pinch_b(split_down=False)
time.sleep(1.2)
after = ui.get_screen()
measure("B: both downs in one SYN", before, after)
before = after

pinch_b(split_down=False, btn_touch=True)
time.sleep(1.2)
after = ui.get_screen()
measure("C: B + BTN_TOUCH", before, after)
before = after

pinch_b(split_down=False, ids=(1, 2))
time.sleep(1.2)
after = ui.get_screen()
measure("D: B with tracking ids 1,2", before, after)
before = after

wheel(6, -1)
time.sleep(1.2)
after = ui.get_screen()
measure("W1: wheel -1 x6 (scroll down)", before, after)
before = after

wheel(12, +1)
time.sleep(1.2)
after = ui.get_screen()
measure("W2: wheel +1 x12 (scroll up)", before, after)

print("[matrix] done — pick the variant classified ZOOM with delta ~0")
