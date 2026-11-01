"""Calibration probe: report where given templates match in a screenshot.

Loads the asset cache, reads an image, and for each template name prints the
best multi-scale match confidence + center coordinate. Use it to verify that
unit icons (or anchors) are detectable on a real frame before wiring coords.

Usage (from anywhere, with venv python):
    python scripts/probe_template.py IMAGE.png units/troops/thrower units/troops/healer ...
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import cv2  # noqa: E402

import app_paths  # noqa: E402
from core.vision import vision  # noqa: E402

SCALES = (0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00, 1.10, 1.25, 1.50)


def main():
    img_path = sys.argv[1]
    names = sys.argv[2:]
    vision.load_assets(app_paths.ASSETS_DIR)
    frame = cv2.imread(img_path)
    if frame is None:
        print("ERR: cannot read", img_path)
        return 2
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    print(f"image {img_path}  {frame.shape[1]}x{frame.shape[0]}")
    for name in names:
        tpl = vision.cache.get(name)
        if tpl is None:
            print(f"  {name:38} MISSING from asset cache")
            continue
        score, scaled, rmap = vision._find_best_scale(gray, tpl, threshold=0.30, scales=SCALES)
        if rmap is None or scaled is None:
            print(f"  {name:38} no match (best<0.30)")
            continue
        _, _, _, max_loc = cv2.minMaxLoc(rmap)
        th, tw = scaled.shape[:2]
        cx, cy = int(max_loc[0] + tw // 2), int(max_loc[1] + th // 2)
        print(f"  {name:38} conf={score:.2f}  center=({cx},{cy})  size={tw}x{th}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
