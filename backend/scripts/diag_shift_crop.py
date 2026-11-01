"""Self-validating crop match: crop distinctive structures from frame A,
template-match into frame B, save a side-by-side (A-crop | B-at-match) image
so a human can SEE whether the lock is real or a lookalike.

Run:  cd backend && ..\\.venv\\Scripts\\python.exe scripts\\diag_shift_crop.py
"""
import os
import sys

import cv2  # noqa: E402
import numpy as np  # noqa: E402

CALIB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "calib"))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "calib_debug")

A = cv2.imread(os.path.join(CALIB, "frame_3-6_START.png"))
B = cv2.imread(os.path.join(CALIB, "frame_9-12_START.png"))
ga, gb = (cv2.cvtColor(x, cv2.COLOR_BGR2GRAY) for x in (A, B))
gb = gb  # search space stays gray; crops for display come from colour frames

# (label, x1, y1, x2, y2) crops in the 3-6 frame (real coords, grid-read)
CROPS = [
    ("TH_blue", 760, 215, 890, 315),
    ("bottom_walls", 590, 530, 920, 610),
    ("left_corner", 350, 240, 500, 380),
    ("right_corner", 1150, 200, 1300, 340),
]

rows = []
for label, x1, y1, x2, y2 in CROPS:
    tpl_c = A[y1:y2, x1:x2]                       # colour crop for display
    tpl = cv2.cvtColor(tpl_c, cv2.COLOR_BGR2GRAY)  # gray for matching
    res = cv2.matchTemplate(gb, tpl, cv2.TM_CCOEFF_NORMED)
    _, mv, _, ml = cv2.minMaxLoc(res)
    dx, dy = ml[0] - x1, ml[1] - y1
    hit = B[ml[1]:ml[1] + tpl.shape[0], ml[0]:ml[0] + tpl.shape[1]]
    tpl = tpl_c
    h = max(tpl.shape[0], hit.shape[0])
    pair = np.hstack([
        cv2.copyMakeBorder(tpl, 2, 2, 2, 2, cv2.BORDER_CONSTANT, value=(0, 255, 0)),
        np.full((h + 4, 20, 3), 128, np.uint8),
        cv2.copyMakeBorder(hit, 2, 2, 2, 2, cv2.BORDER_CONSTANT, value=(0, 0, 255)),
    ])
    bar = np.full((34, pair.shape[1], 3), 30, np.uint8)
    cv2.putText(bar, f"{label}: 3-6({x1},{y1}) -> 9-12 shift ({dx:+d},{dy:+d}) conf {mv:.2f}",
                (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1, cv2.LINE_AA)
    rows.append(np.vstack([bar, pair]))
    print(f"{label}: shift ({dx:+d},{dy:+d}) conf {mv:.2f}")

w = max(r.shape[1] for r in rows)
rows = [cv2.copyMakeBorder(r, 0, 0, 0, w - r.shape[1], cv2.BORDER_CONSTANT,
                           value=(60, 60, 60)) for r in rows]
os.makedirs(OUT, exist_ok=True)
out = os.path.join(OUT, "diag_shift_3-6_vs_9-12.png")
cv2.imwrite(out, np.vstack([np.full((30, w, 3), 0, np.uint8)] + rows))
print("saved", os.path.relpath(out, os.path.abspath(os.path.join(OUT, "..", ".."))))

# --- skull check: 9-12 -> 12-3 (is the -103,0 shift real?) ------------------
C = cv2.imread(os.path.join(CALIB, "frame_12-3_START.png"))
gc = cv2.cvtColor(C, cv2.COLOR_BGR2GRAY)
SKULL = (1170, 120, 1410, 290)
tpl = cv2.cvtColor(A[SKULL[1]:SKULL[3], SKULL[0]:SKULL[2]], cv2.COLOR_BGR2GRAY)
res = cv2.matchTemplate(gc, tpl, cv2.TM_CCOEFF_NORMED)
_, mv, _, ml = cv2.minMaxLoc(res)
print(f"skull 9-12{SKULL[:2]} -> 12-3: shift ({ml[0]-SKULL[0]:+d},{ml[1]-SKULL[1]:+d}) conf {mv:.2f}")

# --- zoomed lower half of 3-6 (where does the wall diamond really end?) -----
crop = A[350:700, 480:1120]
crop = cv2.resize(crop, None, fx=1.6, fy=1.6, interpolation=cv2.INTER_CUBIC)
for gy in range(0, 700, 100):          # grid reference (350->700 mapped)
    yy = int((gy - 350) * 1.6)
    if 0 <= yy < crop.shape[0]:
        cv2.line(crop, (0, yy), (crop.shape[1], yy), (255, 255, 255), 1)
        cv2.putText(crop, str(gy), (4, yy + 16), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 255, 255), 1, cv2.LINE_AA)
for gx in range(500, 1120, 100):
    xx = int((gx - 480) * 1.6)
    if 0 <= xx < crop.shape[1]:
        cv2.line(crop, (xx, 0), (xx, crop.shape[0]), (255, 255, 255), 1)
        cv2.putText(crop, str(gx), (xx + 2, 18), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 255, 255), 1, cv2.LINE_AA)
out2 = os.path.join(OUT, "diag_3-6_lowerhalf.png")
cv2.imwrite(out2, crop)
print("saved", os.path.relpath(out2, os.path.abspath(os.path.join(OUT, "..", ".."))))
