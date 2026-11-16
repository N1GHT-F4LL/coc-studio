"""Loot-ROI calibration tool — draw the calibrated ROIs + OCR results onto
scout frames for human review.

Usage (from backend/):
  ..\\.venv\\Scripts\\python.exe -X utf8 scripts\\calib_loot_rois.py [frame1.png frame2.png ...]

No frame args -> uses every frame in data/calib_debug/loot_frames/frame_*.png.
Each frame gets an overlay (ROIs + readings) saved next to it as
<name>_overlay.png, and a summary table prints the readings so they can be
compared against what is visible on the frame.
"""
import glob
import json
import os
import sys

import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)

from core.ocr import warmup_ocr  # noqa: E402
from screens.attack_screen import AttackScreen, LOOT_KEYS  # noqa: E402

COLORS = {"gold": (0, 255, 255), "elixir": (0, 255, 0), "dark_elixir": (0, 0, 255)}


def main():
    with open(os.path.join(BACKEND, "data", "settings.json"), encoding="utf-8") as f:
        settings = json.load(f)
    rois = settings.get("attack", {}).get("loot_rois", {})
    if not rois.get("gold"):
        sys.exit("attack.loot_rois missing in settings.json — nothing to draw")

    paths = sys.argv[1:] or sorted(
        glob.glob(os.path.join(BACKEND, "data", "calib_debug", "loot_frames", "frame_*.png"))
    )
    if not paths:
        sys.exit("no scout frames found — pass frame paths or capture some first")

    warmup_ocr()
    screen_reader = AttackScreen(None, settings)
    print(f"{len(paths)} frame(s), ROIs: "
          + ", ".join(f"{k}={tuple(int(v) for v in rois[k])}" for k in LOOT_KEYS))
    print()
    for path in paths:
        img = cv2.imread(path)
        if img is None:
            print(f"  (skip unreadable {path})")
            continue
        loot, conf = screen_reader._read_loot(img, settings["attack"])
        canvas = img.copy()
        for key in LOOT_KEYS:
            x1, y1, x2, y2 = [int(v) for v in rois[key]]
            color = COLORS[key]
            cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
            cv2.putText(canvas, f"{key}: {loot[key]:,} c={conf[key]:.2f}",
                        (x1, max(16, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.55, color, 1, cv2.LINE_AA)
        out = os.path.splitext(path)[0] + "_overlay.png"
        cv2.imwrite(out, canvas)
        rel = os.path.relpath(path, BACKEND)
        print(f"{rel}: gold={loot['gold']:,} elixir={loot['elixir']:,} "
              f"dark={loot['dark_elixir']:,} -> {os.path.relpath(out, BACKEND)}")
    print("\nReview the _overlay.png frames: every coloured box must sit tight "
          "around its digit group, and the printed values must match what is "
          "visible on the frame.")


if __name__ == "__main__":
    main()
