"""PASSIVE diagnosis of the '[TRAIN] could not reach Train Troops' warning.

Runs alongside the LIVE bot (screencap only — ZERO taps, zero interference)
and waits for the bot to pass through the attack screen during its next cycle.
Measures the template confidence of buttons/home/btn_train_troops.png on the
real frame, dumps the frame + numbers, so the mismatch is judged on evidence.
"""
import sys, time
sys.path.insert(0, r"C:\Users\antoinenguyen_09\Downloads\coc-studio\backend")
import cv2
import numpy as np
from core.vision import vision
from device_manager import manager

ok, reason = manager.connect()
print("connect:", ok, reason)
if not ok:
    sys.exit(1)

TRAIN = "buttons/home/btn_train_troops"
ATTACK = "buttons/home/btn_attack"
FIND = "buttons/attack/btn_find_a_match"

deadline = time.time() + 480   # up to 8 minutes
home_seen = False
dumped = False
print("passive monitoring (no taps, 0.35s poll) — waiting for the attack screen...")
while time.time() < deadline and not dumped:
    frame = manager.ui_manager.get_screen()
    if frame is None:
        time.sleep(0.35); continue
    a_loc = vision.find_template(frame, ATTACK, threshold=0.7, use_orb_fallback=False)
    if a_loc is not None:
        home_seen = True
    elif home_seen:
        # home disappeared: the bot tapped Attack — hunt the short attack-screen
        # window (Find a Match visible = we ARE on the attack screen)
        f_loc = vision.find_template(frame, FIND, threshold=0.7, use_orb_fallback=False)
        t_loc = vision.find_template(frame, TRAIN, threshold=0.7, use_orb_fallback=False)
        tpl = vision.cache.get(TRAIN)
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        if tpl is not None:
            tgray = tpl if tpl.ndim == 2 else cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
            res = cv2.matchTemplate(g, tgray, cv2.TM_CCOEFF_NORMED)
            _, best, _, ml = cv2.minMaxLoc(res)
        else:
            best, ml = -1, (-1, -1)
        if f_loc is not None or t_loc is not None:
            print(f"ATTACK SCREEN captured: train conf raw={best:.3f} at {ml} | thr-match={'YES' if t_loc else 'no'}")
            cv2.imwrite(r"C:\Users\antoinenguyen_09\Downloads\coc-studio\calib\train_diag_attack_frame.png", frame)
            dumped = True
            break
    time.sleep(0.35)

if not dumped:
    print("no attack-screen frame captured within the window (bot timing) — rerun.")
else:
    print("frame saved: calib/train_diag_attack_frame.png")
