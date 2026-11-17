"""Offline diagnosis of the 2026-11-17 00:10 mapping failure.

Runs the SAME matching logic as multi_village._derive_mapping on the two saved
debug frames, but prints every scale hypothesis + per-region predicted-vs-found
detail so the exact failure point is visible.
"""
import cv2
import numpy as np

CAP = cv2.imread(r"C:\Users\antoinenguyen_09\Downloads\coc-studio\calib\mv_mapfail_cap.png",
                 cv2.IMREAD_COLOR)
ADB = cv2.imread(r"C:\Users\antoinenguyen_09\Downloads\coc-studio\calib\mv_mapfail_adb.png",
                 cv2.IMREAD_COLOR)
print("cap shape:", CAP.shape, "| adb shape:", ADB.shape)

cg = cv2.cvtColor(CAP, cv2.COLOR_BGR2GRAY)
ag = cv2.cvtColor(ADB, cv2.COLOR_BGR2GRAY)
refs = {
    'anchor_battle': (20, 730, 235, 900),
    'build': (1400, 730, 1600, 900),
    'icon_gold': (1530, 25, 1595, 65),
    'icon_elixir': (1530, 82, 1595, 120),
    'icon_dark': (1505, 130, 1570, 168),
}
ax1, ay1, ax2, ay2 = refs['anchor_battle']
anchor_tpl = ag[ay1:ay2, ax1:ax2]
anchor_dev = ((ax1 + ax2) / 2, (ay1 + ay2) / 2)

results = []
for i in range(101):
    s = round(0.50 + 0.008 * i, 3)
    t = cv2.resize(anchor_tpl, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    th, tw = t.shape[:2]
    if th >= cg.shape[0] or tw >= cg.shape[1]:
        continue
    r = cv2.matchTemplate(cg, t, cv2.TM_CCOEFF_NORMED)
    _, c, _, ml = cv2.minMaxLoc(r)
    results.append((c, s, ml))
    if c > 0.6:
        s_ox = (ml[0] + s * (ax2 - ax1) / 2) - s * anchor_dev[0]
        s_oy = (ml[1] + s * (ay2 - ay1) / 2) - s * anchor_dev[1]
        # verify the other 4 regions at predicted positions
        verified = {'anchor_battle': round(c, 3)}
        for key, (x1, y1, x2, y2) in refs.items():
            if key == 'anchor_battle':
                continue
            dcx, dcy = (x1 + x2) / 2, (y1 + y2) / 2
            px = int(round(s_ox + s * dcx))
            py = int(round(s_oy + s * dcy))
            tp = ag[y1:y2, x1:x2]
            th2, tw2 = tp.shape[:2]
            wx1, wy1 = max(0, px - 40), max(0, py - 30)
            wx2 = min(cg.shape[1], px + 40 + tw2)
            wy2 = min(cg.shape[0], py + 30 + th2)
            if wx2 - wx1 < tw2 or wy2 - wy1 < th2:
                verified[key] = "window OOB"
                continue
            rr = cv2.matchTemplate(cg[wy1:wy2, wx1:wx2], tp, cv2.TM_CCOEFF_NORMED)
            _, c2, _, ml2 = cv2.minMaxLoc(rr)
            verified[key] = round(c2, 3)
        n_ok = sum(1 for v in verified.values() if isinstance(v, float) and v >= 0.6)
        print(f"scale {s:.3f} conf {c:.3f} at {ml} -> ox {s_ox:.0f} oy {s_oy:.0f} "
              f"| {n_ok}/5 | {verified}")

results.sort(reverse=True)
print("\nTOP-5 anchor confs overall:", [(round(c, 3), s) for c, s, _ in results[:5]])
