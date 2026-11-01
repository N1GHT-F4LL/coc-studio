# -*- coding: utf-8 -*-
"""calib/verify_probe.py — find the real 'N/M' army-count labels on the My
Army screen (one easyocr full-text pass), print their coordinates, and save an
annotated frame to backend/_calib/. Run while the game shows the army screen
(it will try to navigate there itself if not)."""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.normpath(os.path.join(HERE, "..", "backend"))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

ADB = r"E:\Applications\platform-tools\adb.exe"
SER = "127.0.0.1:21503"

import cv2  # noqa: E402
import numpy as np  # noqa: E402


def grab():
    p = subprocess.run([ADB, "-s", SER, "exec-out", "screencap", "-p"], capture_output=True)
    return cv2.imdecode(np.frombuffer(p.stdout, dtype=np.uint8), cv2.IMREAD_COLOR)


def army_screen(frame):
    from core.vision import vision
    if not vision.cache:
        vision.load_assets("assets")
    return bool(vision.find_all_matches(frame, "buttons/attack/btn_delete_troop",
                                         threshold=0.7))


frame = grab()
if frame is None:
    sys.exit("cannot grab frame — check Memu/adb")

if not army_screen(frame):
    print("[probe] not on the army screen — navigating there...")
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    import blocks  # noqa: F401
    import threading
    from device_manager import manager, load_settings
    from engine.context import RuntimeContext
    from blocks.coc_blocks import EnsureHome
    from screens.train_screen import TrainScreen
    ok, reason = manager.connect()
    print(f"[probe] connect {ok} ({reason})")
    if not ok:
        sys.exit("cannot connect")
    settings = load_settings()
    ctx = RuntimeContext(device=manager.device, ui_manager=manager.ui_manager, vision=None,
                         ocr_read=lambda *a, **k: (None, 0.0), settings=settings,
                         logger=logging.getLogger("probe"), stop_event=threading.Event(),
                         vars={}, emit=lambda ev: None)
    if not EnsureHome().run(ctx, {"zoom_out": True, "timeout": 10})["home"]:
        sys.exit("could not reach home")
    if not TrainScreen(manager.ui_manager).open():
        sys.exit("could not open army screen")
    frame = manager.ui_manager.get_screen()

cv2.imwrite(os.path.join("_calib", "army_verify_probe.png"), frame)
print(f"[probe] army frame {frame.shape[1]}x{frame.shape[0]} saved")

from core.ocr import _get_reader  # noqa: E402
reader = _get_reader()
rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
found = []
for box, text, conf in reader.readtext(rgb):
    t = str(text).replace(" ", "")
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    if re.fullmatch(r"\d+/\d+", t):
        found.append({"text": t, "cx": round(sum(xs) / len(xs)), "cy": round(sum(ys) / len(ys)),
                      "conf": round(float(conf), 2)})
        cv2.circle(frame, (round(sum(xs) / len(xs)), round(sum(ys) / len(ys))), 8, (0, 0, 255), 2)
        cv2.putText(frame, t, (round(sum(xs) / len(xs)) + 10, round(sum(ys) / len(ys))),
                    0, 0.7, (0, 0, 255), 2)
cv2.imwrite(os.path.join("_calib", "army_verify_probe_annot.png"), frame)
print("N/M labels:", json.dumps(found))
print("--- ALL texts (for section binding) ---")
for box, text, conf in reader.readtext(rgb):
    xs = [q[0] for q in box]; ys = [q[1] for q in box]
    cx, cy = round(sum(xs)/len(xs)), round(sum(ys)/len(ys))
    if 80 < cy < 730 and len(str(text).strip()) > 0:
        print(f"  ({cx:4d},{cy:3d}) conf={conf:.2f} {text!r}")
