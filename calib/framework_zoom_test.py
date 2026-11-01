# -*- coding: utf-8 -*-
"""calib/framework_zoom_test.py — try FRAMEWORK-path two-finger zoom:
E1: two concurrent `input swipe` (single-pointer each, interleaved)
E2: `input motionevent` sequence (DOWN/MOVE/UP), if the Android version has it
Run:  .venv/Scripts/python.exe calib/framework_zoom_test.py"""
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
log = logging.getLogger("fwtest")

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
print(f"[fw] connect {ok} ({reason})")
if not ok:
    sys.exit("no device")
dev, ui = manager.device, manager.ui_manager
settings = load_settings()
ctx = RuntimeContext(device=dev, ui_manager=ui, vision=None,
                     ocr_read=lambda *a, **k: (None, 0.0), settings=settings,
                     logger=log, stop_event=threading.Event(), vars={}, emit=lambda ev: None)
if not EnsureHome().run(ctx, {"zoom_out": False, "timeout": 10})["home"]:
    sys.exit("no home")

ADB = dev.adb_path
SER = dev.serial


def measure(tag, before, after):
    ga, gb = (cv2.cvtColor(x, cv2.COLOR_BGR2GRAY) for x in (before, after))
    patches = [(800, 450), (500, 300), (1100, 300), (500, 600), (1100, 600)]
    half = 70
    scales, deltas = [], []
    for (px, py) in patches:
        pa = ga[py-half:py+half, px-half:px+half]
        best = (0.0, 1.0, (0, 0))
        for s in (0.60, 0.70, 0.80, 0.90, 1.00):
            t = cv2.resize(pa, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(gb, t, cv2.TM_CCOEFF_NORMED)
            _, mv, _, ml = cv2.minMaxLoc(res)
            if mv > best[0]:
                best = (mv, s, (ml[0] + half - px, ml[1] + half - py))
        if best[0] >= 0.70:
            scales.append(best[1])
            deltas.append(best[2])
    ms = float(np.median(scales)) if scales else 1.0
    md = (float(np.median([d[0] for d in deltas])) if deltas else 0.0,
          float(np.median([d[1] for d in deltas])) if deltas else 0.0)
    kind = "ZOOM" if ms <= 0.95 else ("PAN" if abs(md[0]) > 20 or abs(md[1]) > 20 else "NONE")
    print(f"  [{tag}] scale={ms:.2f} delta=({md[0]:.0f},{md[1]:.0f}) -> {kind}")
    return kind


print("[fw] E1: two CONCURRENT input swipes (framework path)")
f0 = ui.get_screen()
r = subprocess.run([ADB, "-s", SER, "shell",
                    "input swipe 200 450 680 450 900 & input swipe 1400 450 920 450 900"],
                   capture_output=True, text=True)
time.sleep(1.0)
f1 = ui.get_screen()
measure("E1 concurrent swipes", f0, f1)

print("[fw] checking `input motionevent` availability...")
usage = subprocess.run([ADB, "-s", SER, "shell", "input"], capture_output=True, text=True)
has_me = "motionevent" in (usage.stdout + usage.stderr)
print(f"[fw] motionevent available: {has_me}")
if has_me:
    print("[fw] E2: input motionevent two-finger sequence (zoom out: fingers close->apart)")
    f0 = ui.get_screen()

    def me(action, x, y):
        subprocess.run([ADB, "-s", SER, "shell", f"input motionevent {action} {x} {y}"],
                       capture_output=True)

    # finger 1 down at (200,450), finger 2 down at (1400,450), then 8 move
    # steps spreading apart, then ups — zoom IN direction... use CLOSE->FAR
    # = zoom out? fingers APART = zoom in on CoC. We want zoom OUT = fingers
    # FAR -> CLOSE. down far, move inward.
    me("DOWN", 200, 450)
    time.sleep(0.15)
    me("DOWN", 1400, 450)
    time.sleep(0.15)
    for i in range(1, 9):
        d = int(600 + (120 - 600) * i / 8)
        me("MOVE", 800 - d, 450)
        me("MOVE", 800 + d, 450)
        time.sleep(0.12)
    me("UP", 680, 450)
    me("UP", 920, 450)
    time.sleep(1.0)
    f1 = ui.get_screen()
    measure("E2 motionevent", f0, f1)

print("[fw] done")
