# -*- coding: utf-8 -*-
"""calib/recapture_heroes.py — re-capture the stale prince/dragon_duke bar
cards from the saved bar_probe frame (offline, no device), with grid snapping
and self-validation. Backs up the old templates into calib/."""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.normpath(os.path.join(HERE, "..", "backend"))
sys.path.insert(0, BACKEND)

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from core.vision import vision  # noqa: E402
vision.load_assets(os.path.join(BACKEND, "assets"))

frame = cv2.imread(os.path.join(HERE, "bar_probe.png"))
if frame is None:
    sys.exit("calib/bar_probe.png missing — run bar_probe.py first")
g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

ANCHORS = [("units/heroes/archer_queen", 684), ("units/heroes/barbarian_king", 803),
           ("units/heroes/grand_warden", 924), ("units/heroes/royal_champion", 1045)]
BAR_Y = 815

# 1) re-derive the slot pitch from the strong anchors
pos = []
for key, approx in ANCHORS:
    tpl = vision.cache[key]
    res = cv2.matchTemplate(g[:, max(0, approx - 60):approx + 60],
                            tpl, cv2.TM_CCOEFF_NORMED)
    _, mv, _, ml = cv2.minMaxLoc(res)
    pos.append(max(0, approx - 60) + ml[0] + tpl.shape[1] // 2)
    print(f"[recap] anchor {key.rsplit('/',1)[-1]}: x={pos[-1]} conf={mv:.2f}")
pitch = (pos[-1] - pos[0]) / (len(pos) - 1)
print(f"[recap] slot pitch = {pitch:.1f}px")

# 2) the two remaining slots to the right hold prince + duke (unknown order)
s5 = int(round(pos[-1] + pitch))
s6 = int(round(pos[-1] + 2 * pitch))
CARD_W, CARD_H = 116, 130


def crop_card(cx):
    x1, y1 = cx - CARD_W // 2, BAR_Y - CARD_H // 2
    return g[y1:y1 + CARD_H, x1:x1 + CARD_W], x1, y1


c5, _, _ = crop_card(s5)
c6, _, _ = crop_card(s6)

# 3) assign slots to heroes via the OLD templates (best-sum pairing)
old = {k: vision.cache[k] for k in ("units/heroes/prince", "units/heroes/dragon_duke")}


def score(crop, tpl):
    t = tpl if tpl.shape[0] <= crop.shape[0] and tpl.shape[1] <= crop.shape[1] else \
        cv2.resize(tpl, (crop.shape[1], crop.shape[0]))
    res = cv2.matchTemplate(crop, t, cv2.TM_CCOEFF_NORMED)
    return float(res.max())


direct = score(c5, old["units/heroes/prince"]) + score(c6, old["units/heroes/dragon_duke"])
swapped = score(c5, old["units/heroes/dragon_duke"]) + score(c6, old["units/heroes/prince"])
print(f"[recap] slot5={s5} slot6={s6}; direct(prince@5,duke@6)={direct:.2f} "
      f"swapped(duke@5,prince@6)={swapped:.2f}")
if swapped > direct:
    s5, s6 = s6, s5
    c5, c6 = c6, c5
assign = {"units/heroes/prince": (s5, c5), "units/heroes/dragon_duke": (s6, c6)}

# 4) save (with backups) + hot-load + validate on the same frame
for key, (cx, crop) in assign.items():
    dst = os.path.join(BACKEND, "assets", *key.split("/")) + ".png"
    shutil.copyfile(dst, os.path.join(HERE, key.rsplit("/", 1)[-1] + ".pre_recapture.bak.png"))
    cv2.imwrite(dst, crop)
    vision.cache[key] = crop
    vision.cache[key.rsplit("/", 1)[-1]] = crop
    print(f"[recap] saved {key} <- card at x={cx} ({crop.shape[1]}x{crop.shape[0]})")

print("[recap] validation scan on the same frame:")
for key in ("units/heroes/prince", "units/heroes/dragon_duke"):
    tpl = vision.cache[key]
    best = (0.0, None)
    for s in (0.9, 0.95, 1.0, 1.05, 1.1):
        t = cv2.resize(tpl, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        th, tw = t.shape[:2]
        res = cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED)
        _, mv, _, ml = cv2.minMaxLoc(res)
        if mv > best[0]:
            best = (mv, (ml[0] + tw // 2, ml[1] + th // 2))
    tag = "OK" if best[0] >= 0.62 else "STILL WEAK"
    print(f"  {key:34} conf={best[0]:.2f} at {best[1]}  [{tag}]")
