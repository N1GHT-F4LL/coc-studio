# -*- coding: utf-8 -*-
"""calib/echo_test.py — decisive test: inject a two-finger pinch while
`getevent` listens on the same device, then compare what the kernel ECHOES
back against what we sent. If the echo shows both slots, the kernel accepted
the multi-contact stream (and the loss is elsewhere); if the echo shows only
one slot, the write path itself drops it. Run: .venv/Scripts/python.exe calib/echo_test.py"""
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
from device_manager import manager  # noqa: E402

ok, reason = manager.connect()
print(f"[echo] connect {ok} ({reason})")
subprocess.run([ADB, "-s", SER, "shell", "pkill -f getevent"], capture_output=True)
if not ok:
    sys.exit("no device")
dev = manager.device
EV_DEV, MAXX, MAXY = dev._find_touch_input_device()
SW, SH = dev.get_screen_size()
print(f"[echo] device {EV_DEV} max=({MAXX},{MAXY}) screen={SW}x{SH}")

ADB, SER = dev.adb_path, dev.serial

# 1) start the echo listener in the background
echo_path = os.path.join(HERE, "echo_out.txt")
echo_log = open(echo_path, "w", encoding="utf-8")
echo_proc = subprocess.Popen([ADB, "-s", SER, "shell", "getevent"],
                             stdout=echo_log, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL)
time.sleep(1.0)

# 2) build + inject a two-finger pinch (Protocol B, exactly as device.pinch)
cx, cy = SW // 2, SH // 2
cmds = []


def se(t, c, v):
    cmds.append(f"sendevent {EV_DEV} {t} {c} {v}")


SLOT, XA, YA, MA, ID = 0x2f, 0x35, 0x36, 0x30, 0x39


def px(x, y):
    return dev._pixel_to_event(x, y, MAXX, MAXY, SW, SH)


def frame(f0, f1):
    for slot, (x, y) in ((0, f0), (1, f1)):
        se(3, SLOT, slot)
        se(3, XA, x)
        se(3, YA, y)
        se(3, MA, 10)
    se(0, 0, 0)


def down(slot, x, y, tid):
    se(3, SLOT, slot)
    se(3, XA, x)
    se(3, YA, y)
    se(3, MA, 10)
    se(3, ID, tid)
    se(0, 0, 0)


x1, y1 = px(cx - 600, cy)
x2, y2 = px(cx + 600, cy)
down(0, x1, y1, 0)
down(1, x2, y2, 1)
sent_slots = {"s0": 0, "s1": 0}
for i in range(1, 16):
    d = int(600 + (120 - 600) * i / 15)
    x1, y1 = px(cx - d, cy)
    x2, y2 = px(cx + d, cy)
    frame((x1, y1), (x2, y2))
    sent_slots["s0"] += 1
    sent_slots["s1"] += 1
    cmds.append("sleep 1")
se(3, SLOT, 0)
se(3, ID, -1)
se(3, SLOT, 1)
se(3, ID, -1)
se(0, 0, 0)
script = " ; ".join(cmds)  # ';' so a failing sleep cannot cut the chain
time.sleep(0.5)
r = subprocess.run([ADB, "-s", SER, "shell", script], capture_output=True, text=True)
print(f"[echo] pinch injected rc={r.returncode}")
time.sleep(1.0)
echo_proc.terminate()
echo_log.close()

# 3) analyze the echo
sent_per_code = {}
echo_slots, echo_ids, echo_frames = [], [], 0
for line in open(echo_path, encoding="utf-8", errors="replace"):
    m = re.match(r"/dev/input/event6: (\S+) (\S+) (\S+)", line.strip())
    if not m:
        continue
    t, c, v = int(m.group(1), 16), int(m.group(2), 16), int(m.group(3), 16)
    if t == 3 and c == SLOT:
        echo_slots.append(v)
    if t == 3 and c == ID:
        echo_ids.append(v)
    if t == 0 and c == 0:
        echo_frames += 1
s0_echo = sum(1 for v in echo_slots if v == 0)
s1_echo = sum(1 for v in echo_slots if v == 1)
print(f"[echo] SENT: ~{16} frames x2 slots | ECHO: frames={echo_frames} "
      f"slot0_events={s0_echo} slot1_events={s1_echo} ids={sorted(set(echo_ids), key=lambda x: (x < 0, x))[:8]}")
verdict = ("KERNEL ACCEPTED BOTH FINGERS — the loss is above the kernel"
           if s0_echo > 5 and s1_echo > 5 else
           "KERNEL DROPS THE SECOND FINGER — sendevent write path is the blocker")
print(f"[echo] VERDICT: {verdict}")
print(f"[echo] raw echo saved: {echo_path}")
