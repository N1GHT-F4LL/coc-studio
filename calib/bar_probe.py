# -*- coding: utf-8 -*-
"""calib/bar_probe.py — measure how well every hero template matches the LIVE
battle deploy bar, and (optionally) re-capture stale hero cards.

Run:  .venv/Scripts/python.exe calib/bar_probe.py
Stops the backend if it is running (exclusive device use), enters one battle
(nothing is deployed), grabs a full-res frame, scans all 6 heroes, prints
confidences + positions, saves the frame to calib/bar_probe.png, then
surrenders out.
"""
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
log = logging.getLogger("barprobe")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

HEROES = ["units/heroes/barbarian_king", "units/heroes/archer_queen",
          "units/heroes/grand_warden", "units/heroes/royal_champion",
          "units/heroes/prince", "units/heroes/dragon_duke"]

# stop the running loop / backend so this probe owns the device
import urllib.request  # noqa: E402
try:
    req = urllib.request.Request("http://127.0.0.1:8000/api/run/stop", method="POST",
                                 data=b"{}", headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=3)
    print("[probe] stopped the running loop")
except Exception:
    print("[probe] no run active")
try:
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                         stdin=subprocess.DEVNULL).stdout
    for pid in {l.split()[-1] for l in out.splitlines()
                if ":8000" in l and "LISTENING" in l.upper()}:
        subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True,
                       stdin=subprocess.DEVNULL)
        print(f"[probe] killed backend pid {pid}")
except Exception:
    pass

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
battle = BattleScreen(ui)
entered_here = False
if not battle.is_current_screen():
    if not EnsureHome().run(ctx, {"zoom_out": True, "timeout": 10})["home"]:
        sys.exit("no home")
    attack = AttackScreen(ui, {**settings,
                               "farm": {"min_gold": 0, "min_elixir": 0, "min_dark_elixir": 0},
                               "attack": {**settings.get("attack", {}), "scout_settle": 1.0}})
    if not attack.find_match():
        sys.exit("no base")
    if not battle.wait_until_entered(timeout=15):
        sys.exit("no battle")
    entered_here = True

frame = ui.get_screen()
cv2.imwrite(os.path.join(HERE, "bar_probe.png"), frame)
bar_gray = cv2.cvtColor(frame[730:910, 0:1600], cv2.COLOR_BGR2GRAY)
print(f"[probe] frame saved; bar region 1600x180 grabbed. HEROES ON THE BAR NOW:")
results = {}
for key in HEROES:
    tpl = vision.cache.get(key)
    if tpl is None:
        print(f"  {key:34} MISSING TEMPLATE")
        continue
    best = (0.0, None, None)
    for s in SLOT_ICON_SCALES:
        t = cv2.resize(tpl, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        th, tw = t.shape[:2]
        if th >= bar_gray.shape[0] or tw >= bar_gray.shape[1]:
            continue
        res = cv2.matchTemplate(bar_gray, t, cv2.TM_CCOEFF_NORMED)
        _, mv, _, ml = cv2.minMaxLoc(res)
        if mv > best[0]:
            best = (mv, (ml[0] + tw // 2, ml[1] + th // 2 + 730), s)
    results[key] = best
    tag = "OK" if best[0] >= 0.62 else ("WEAK" if best[0] >= 0.45 else "FAIL")
    print(f"  {key:34} conf={best[0]:.2f} at {best[1]} scale={best[2]}  [{tag}]")

print(f"[probe] template sizes: " + ", ".join(
    f"{k.rsplit('/',1)[-1]}={vision.cache[k].shape}" for k in HEROES if k in vision.cache))

if entered_here:
    for _ in range(3):
        try:
            battle.surrender(return_home=True)
            HomeScreen(ui).close_popups()
            if HomeScreen(ui).is_current_screen():
                break
        except Exception:
            pass
        ui._poll_sleep(1.0)
print("[probe] done")
