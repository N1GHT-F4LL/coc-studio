"""Crop the missing roster faces from the captured bright-roster frames and
verify each against its source frame (self-match ≈1.0 at the known position)
plus cross-frames (no false hits elsewhere).
"""
import os
import sys

sys.path.insert(0, r"C:\Users\antoinenguyen_09\Downloads\coc-studio\backend")
import cv2

FRAMES = r"C:\Users\antoinenguyen_09\Downloads\coc-studio\calib\roster_frames"
ASSETS = r"C:\Users\antoinenguyen_09\Downloads\coc-studio\backend\assets\units\roster"

# face box (x1, y1, x2, y2) per unit, hand-read from the frames
FACES = {
    "balloon":       ("troop_0.png", (1340, 552, 1478, 685)),
    "freeze":        ("spell_0.png", (370, 550, 505, 685)),
    "stone_slammer": ("siege_0.png", (345, 565, 565, 795)),
}

os.makedirs(ASSETS, exist_ok=True)
for name, (frame_name, (x1, y1, x2, y2)) in FACES.items():
    frame = cv2.imread(os.path.join(FRAMES, frame_name))
    if frame is None:
        print(f"MISSING frame {frame_name}")
        continue
    face = frame[y1:y2, x1:x2]
    out = os.path.join(ASSETS, f"{name}.png")
    cv2.imwrite(out, face)
    print(f"{name}: cropped {face.shape[1]}x{face.shape[0]} -> {out}")

    g_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    g_face = cv2.cvtColor(face, cv2.COLOR_BGR2GRAY)
    res = cv2.matchTemplate(g_frame, g_face, cv2.TM_CCOEFF_NORMED)
    _, best, _, ml = cv2.minMaxLoc(res)
    print(f"   self-match on source frame: {best:.3f} at {ml}")
