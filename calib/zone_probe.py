# -*- coding: utf-8 -*-
"""calib/zone_probe.py — validate the diff-based red deploy-zone detector live.

Enters one battle (nothing deployed), grabs a frame, SELECTS the balloon on
the bar (fill renders), grabs another frame, computes the fill mask from the
diff, prints the measured diamond corners, saves annotated images, then
surrenders out. Run:  .venv/Scripts/python.exe calib/zone_probe.py
"""
import os
import subprocess
import sys
import threading
import time

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


import logging  # noqa: E402
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("probe")

import blocks  # noqa: F401,E402
from device_manager import manager, load_settings  # noqa: E402
from engine.context import RuntimeContext  # noqa: E402
from blocks.coc_blocks import EnsureHome  # noqa: E402
from screens.attack_screen import AttackScreen  # noqa: E402
from screens.battle_screen import BattleScreen, SLOT_ICON_SCALES  # noqa: E402
from screens.home_screen import HomeScreen  # noqa: E402
from core.vision import vision  # noqa: E402

ok, reason = manager.connect()
print(f"[probe] connect {ok} ({reason})")
if not ok:
    sys.exit("no device")
dev, ui = manager.device, manager.ui_manager
settings = load_settings()

ctx = RuntimeContext(device=dev, ui_manager=ui, vision=None,
                     ocr_read=lambda *a, **k: (None, 0.0), settings=settings,
                     logger=log, stop_event=threading.Event(), vars={}, emit=lambda ev: None)
if not EnsureHome().run(ctx, {"zoom_out": True, "timeout": 10})["home"]:
    sys.exit("no home")
attack = AttackScreen(ui, {**settings,
                           "farm": {"min_gold": 0, "min_elixir": 0, "min_dark_elixir": 0},
                           "attack": {**settings.get("attack", {}), "scout_settle": 1.0}})
if not attack.find_match():
    sys.exit("no base")
battle = BattleScreen(ui)
if not battle.wait_until_entered(timeout=15):
    sys.exit("no battle")
dev.pinch("out", span_pixels=600, repeats=3)
ui._poll_sleep(1.5)

before = grab()
bar = [int(v) for v in settings.get("attack", {}).get("deploy", {}).get("troop_bar_region", [0, 730, 1600, 910])]
bar_gray = cv2.cvtColor(before[bar[1]:bar[3], bar[0]:bar[2]], cv2.COLOR_BGR2GRAY)
tpl = vision.cache.get("units/troops/balloon")
score, scaled, rmap = vision._find_best_scale(bar_gray, tpl, threshold=0.5, scales=SLOT_ICON_SCALES)
if rmap is None:
    battle.surrender(return_home=True)
    sys.exit("balloon slot not found")
_, _, _, ml = cv2.minMaxLoc(rmap)
th, tw = scaled.shape[:2]
slot = (ml[0] + tw // 2 + bar[0], ml[1] + th // 2 + bar[1])
print(f"[probe] selecting balloon at {slot} conf={score:.2f}")
ui.click(*slot)
ui._poll_sleep(0.8)
after = grab()

# --- diff-based fill mask ----------------------------------------------------
ra, ga, ba = (after[:, :, i].astype(int) for i in (2, 1, 0))
rb, gb, bb = (before[:, :, i].astype(int) for i in (2, 1, 0))
mask = ((ra - rb >= 14) & (ra - ga >= 18) & (ra - ba >= 18)).astype(np.uint8) * 255
mask[0:300, 0:380] = 0
mask[660:, :] = 0
mask[:60, 500:1150] = 0     # battle timer text
mask[600:, 1230:] = 0       # next button
mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
cv2.imwrite("_calib/zone_before.png", before)
cv2.imwrite("_calib/zone_after.png", after)
cv2.imwrite("_calib/zone_mask.png", mask)
print(f"[probe] fill px: {int((mask > 0).sum())}")

cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
if not cnts:
    battle.surrender(return_home=True)
    sys.exit("no fill detected — check zone_mask.png")
c = max(cnts, key=cv2.contourArea)
print(f"[probe] largest blob area={int(cv2.contourArea(c))} bbox={cv2.boundingRect(c)}")
if cv2.contourArea(c) < 30000:
    battle.surrender(return_home=True)
    sys.exit("fill blob too small — detector needs tuning (see zone_mask.png)")

hull = cv2.convexHull(c).reshape(-1, 2)
top = hull[hull[:, 1].argmin()]; bot = hull[hull[:, 1].argmax()]
left = hull[hull[:, 0].argmin()]; right = hull[hull[:, 0].argmax()]
print(f"[probe] extremes: top={tuple(top)} bottom={tuple(bot)} left={tuple(left)} right={tuple(right)}")
print(f"[probe] shape: w={right[0]-left[0]} h={bot[1]-top[1]} skewX={abs(int(top[0])-int(bot[0]))} skewY={abs(int(left[1])-int(right[1]))}")

img = after.copy()
cv2.drawContours(img, [hull], -1, (0, 255, 255), 3)
for name, p in (("12h", top), ("3h", right), ("6h", bot), ("9h", left)):
    cv2.circle(img, (int(p[0]), int(p[1])), 10, (0, 0, 255), 3)
    cv2.putText(img, name, (int(p[0]) + 12, int(p[1])), 0, 0.9, (0, 0, 255), 2)
cv2.imwrite("_calib/zone_annot.png", img)

for _ in range(3):
    try:
        battle.surrender(return_home=True)
        HomeScreen(ui).close_popups()
        if HomeScreen(ui).is_current_screen():
            break
    except Exception:
        pass
    ui._poll_sleep(1.0)
print("[probe] done — see _calib/zone_annot.png")
