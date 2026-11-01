# -*- coding: utf-8 -*-
"""calib/replay_test.py — A/B: replay the CAPTURED Memu wheel-pinch stream vs
my synthetic pinch stream, and measure each one's effect on the map."""
import os
import re
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
log = logging.getLogger("replay")

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
print(f"[replay] connect {ok} ({reason})")
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

# build the replay script from the captured stream (hex -> decimal)
L = r"E:\Temp\zcode-bash-HdQXZ1\session_1bbe32ba88028a1862a91a062e0af54e\call_3415b39112e647639d8638b2-stdout.log"
lines = []
frame_events = []
for line in open(L, encoding="utf-8", errors="replace"):
    m = re.match(r"/dev/input/event6: (\S+) (\S+) (\S+)", line.strip())
    if not m:
        continue
    t, c, v = int(m.group(1), 16), int(m.group(2), 16), int(m.group(3), 16)
    frame_events.append(f"sendevent /dev/input/event6 {t} {c} {v}")
    if t == 0 and c == 0:
        lines.extend(frame_events)
        frame_events = []
if frame_events:  # trailing partial frame (stream cut): add explicit lift
    lines.extend(["sendevent /dev/input/event6 3 47 0",
                  "sendevent /dev/input/event6 3 57 -1",
                  "sendevent /dev/input/event6 3 47 1",
                  "sendevent /dev/input/event6 3 57 -1",
                  "sendevent /dev/input/event6 0 0 0"])
replay_path = os.path.join(HERE, "pinch_replay.sh")
open(replay_path, "w", encoding="ascii").write("\n".join(lines) + "\n")
subprocess.run([ADB, "-s", SER, "push", replay_path, "/data/local/tmp/pinch_replay.sh"],
               capture_output=True)
print(f"[replay] pushed {len(lines)} lines")

# my synthetic stream (Protocol B, both downs one SYN, horizontal pinch)
def synth_script():
    cmds = []
    S, XA, YA, MA, ID = 0x2f, 0x35, 0x36, 0x30, 0x39

    def frame(f0, f1):
        for slot, (x, y) in ((0, f0), (1, f1)):
            cmds.append(f"sendevent /dev/input/event6 3 47 {slot}")
            cmds.append(f"sendevent /dev/input/event6 3 53 {x}")
            cmds.append(f"sendevent /dev/input/event6 3 54 {y}")
            cmds.append(f"sendevent /dev/input/event6 3 48 {MA}")
        cmds.append("sendevent /dev/input/event6 0 0 0")
    def px(x, y):
        return dev._pixel_to_event(x, y, 1600, 900, 1600, 900)
    x1, y1 = px(200, 450)
    x2, y2 = px(1400, 450)
    frame((x1, y1), (x2, y2))
    for i in range(1, 16):
        d = int(600 + (120 - 600) * i / 15)
        x1, y1 = px(800 - d, 450)
        x2, y2 = px(800 + d, 450)
        frame((x1, y1), (x2, y2))
    cmds.append(f"sendevent /dev/input/event6 3 47 0")
    cmds.append(f"sendevent /dev/input/event6 3 57 -1")
    cmds.append(f"sendevent /dev/input/event6 3 47 1")
    cmds.append(f"sendevent /dev/input/event6 3 57 -1")
    cmds.append(f"sendevent /dev/input/event6 0 0 0")
    return "\n".join(cmds) + "\n"

synth_path = os.path.join(HERE, "pinch_synth.sh")
open(synth_path, "w", encoding="ascii").write(synth_script())
subprocess.run([ADB, "-s", SER, "push", synth_path, "/data/local/tmp/pinch_synth.sh"],
               capture_output=True)
print("[replay] pushed synthetic script")


def measure(tag, before, after):
    ga, gb = (cv2.cvtColor(x, cv2.COLOR_BGR2GRAY) for x in (before, after))
    patches = [(800, 450), (500, 300), (1100, 300), (500, 600), (1100, 600)]
    half = 70
    scales, deltas = [], []
    for (px, py) in patches:
        pa = ga[py-half:py+half, px-half:px+half]
        best = (0.0, 1.0, (0, 0))
        for s in (0.60, 0.70, 0.80, 0.90, 1.00, 1.10, 1.20, 1.30):
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


def snap():
    return ui.get_screen()


f0 = snap()
print("[replay] REPLAYING captured Memu stream...")
r = subprocess.run([ADB, "-s", SER, "shell", "sh /data/local/tmp/pinch_replay.sh"],
                   capture_output=True, text=True)
print(f"[replay]   sh rc={r.returncode} {r.stderr[:200]}")
time.sleep(1.0)
f1 = snap()
measure("replay captured stream", f0, f1)

print("[replay] MY synthetic stream...")
r = subprocess.run([ADB, "-s", SER, "shell", "sh /data/local/tmp/pinch_synth.sh"],
                   capture_output=True, text=True)
print(f"[replay]   sh rc={r.returncode} {r.stderr[:200]}")
time.sleep(1.0)
f2 = snap()
measure("synthetic stream", f1, f2)

cv2.imwrite("_calib/replay_f0.png", f0)
cv2.imwrite("_calib/replay_f1.png", f1)
cv2.imwrite("_calib/replay_f2.png", f2)
print("[replay] done — frames in _calib/replay_*.png")
