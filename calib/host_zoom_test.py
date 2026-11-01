# -*- coding: utf-8 -*-
"""calib/host_zoom_test.py — live test of the HOST wheel zoom: ensure home,
run zoom_out_to_max_host (mouse wheel over the Memu window), print the per-
round content scale. The host cursor will move during the test.
Run:  .venv/Scripts/python.exe calib/host_zoom_test.py"""
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
log = logging.getLogger("hostzoom")

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
from screens.battle_screen import zoom_out_to_max_host, _zoom_ratio  # noqa: E402

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
    sys.exit("no home (baseline zoom untouched)")

print("[test] running zoom_out_to_max_host — the mouse cursor will move to Memu")
rounds = zoom_out_to_max_host(lambda: ui.get_screen(), log)
print(f"[test] rounds performed: {rounds}")
final = ui.get_screen()
import cv2  # noqa: E402
cv2.imwrite("_calib/host_zoom_final.png", final)
print("[test] done — final view saved to _calib/host_zoom_final.png (should be MAX zoomed out)")
