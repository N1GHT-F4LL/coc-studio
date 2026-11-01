# -*- coding: utf-8 -*-
"""calib/scrcpy_zoom_test.py — live test: scrcpy multi-touch pinch on the
village, measured by frame diff. Run: .venv/Scripts/python.exe calib/scrcpy_zoom_test.py"""
import os
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.normpath(os.path.join(HERE, "..", "backend"))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

import logging  # noqa: E402
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("sctest")

import cv2  # noqa: E402

import urllib.request  # noqa: E402
try:
    req = urllib.request.Request("http://127.0.0.1:8000/api/run/stop", method="POST",
                                 data=b"{}", headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=3)
    print("[test] stopped running loop")
except Exception:
    print("[test] no run active")
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
from screens.battle_screen import _zoom_ratio  # noqa: E402
import scrcpy_input  # noqa: E402

ok, reason = manager.connect()
print(f"[test] connect {ok} ({reason})")
subprocess.run([ADB, "-s", SER, "shell", "pkill -f scrcpy_server"], capture_output=True)
if not ok:
    sys.exit("no device")
dev, ui = manager.device, manager.ui_manager
settings = load_settings()
ctx = RuntimeContext(device=dev, ui_manager=ui, vision=None,
                     ocr_read=lambda *a, **k: (None, 0.0), settings=settings,
                     logger=log, stop_event=threading.Event(), vars={}, emit=lambda ev: None)
if not EnsureHome().run(ctx, {"zoom_out": False, "timeout": 10})["home"]:
    sys.exit("no home")

client = scrcpy_input.get_client(dev.adb_path, dev.serial, log)

f0 = ui.get_screen()
print("[test] PINCH OUT (fingers close: zoom out)...")
client.pinch(800, 450, 300, 100, steps=10, interval=0.05)
import time  # noqa: E402
time.sleep(1.0)
f1 = ui.get_screen()
r1 = _zoom_ratio(f0, f1)
print(f"[test] after pinch 1: content scale {r1:.2f} "
      f"({'ZOOMED ✓' if r1 < 0.95 else 'no change'})")

client.pinch(800, 450, 300, 100, steps=10, interval=0.05)
time.sleep(1.0)
f2 = ui.get_screen()
r2 = _zoom_ratio(f1, f2)
print(f"[test] after pinch 2: content scale {r2:.2f} "
      f"({'ZOOMED ✓' if r2 < 0.95 else 'no change / clamped'})")

print(f"[test] total zoom across 2 pinches: {r1 * r2:.2f} (<1 = zoomed out)")
cv2.imwrite("_calib/scrcpy_zoom_final.png", f2)
print("[test] done — final view in _calib/scrcpy_zoom_final.png")
