# -*- coding: utf-8 -*-
"""calib/pinch_test.py — live test of the Protocol-B pinch: ensure home, grab a
frame, pinch out once (new implementation), grab again, measure the content
scale change. Run:  .venv/Scripts/python.exe calib/pinch_test.py"""
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
log = logging.getLogger("pinchtest")

import cv2  # noqa: E402

# exclusive device use
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
    print(f"[test] killed backend pid {pid}")

import blocks  # noqa: F401,E402
from device_manager import manager, load_settings  # noqa: E402
from engine.context import RuntimeContext  # noqa: E402
from blocks.coc_blocks import EnsureHome  # noqa: E402
from screens.battle_screen import _zoom_ratio  # noqa: E402

ok, reason = manager.connect()
print(f"[test] connect {ok} ({reason})")
if not ok:
    sys.exit("no device")
dev, ui = manager.device, manager.ui_manager
settings = load_settings()
ctx = RuntimeContext(device=dev, ui_manager=ui, vision=None,
                     ocr_read=lambda *a, **k: (None, 0.0), settings=settings,
                     logger=log, stop_event=threading.Event(), vars={}, emit=lambda ev: None)
if not EnsureHome().run(ctx, {"zoom_out": False, "timeout": 10})["home"]:
    sys.exit("no home (zoom disabled for a clean baseline)")

before = ui.get_screen()
cv2.imwrite("_calib/pinch_before.png", before)
print("[test] baseline captured; pinching ONCE with Protocol B...")
res = dev.pinch("out", span_pixels=600, steps=15, repeats=1)
print(f"[test] pinch returned {res}")
import time
time.sleep(1.0)
after = ui.get_screen()
cv2.imwrite("_calib/pinch_after.png", after)
ratio = _zoom_ratio(before, after)
print(f"[test] content scale after 1 pinch: {ratio:.2f} "
      f"({'ZOOMED — protocol B works' if ratio < 0.95 else 'NO CHANGE — still broken'})")

# a second + third pinch to show continued zoom
for i in (2, 3):
    dev.pinch("out", span_pixels=600, steps=15, repeats=1)
    import time
    time.sleep(1.0)
    nxt = ui.get_screen()
    r2 = _zoom_ratio(after, nxt)
    print(f"[test] pinch {i}: scale {r2:.2f} ({'clamped' if abs(r2-1.0) < 0.04 else 'zooming'})")
    after = nxt
cv2.imwrite("_calib/pinch_final.png", after)
print("[test] done — frames in _calib/pinch_*.png")
