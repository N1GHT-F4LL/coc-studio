"""Capture a FACE-only template for a troop from the bright army add-roster.

Why face-only: the shipped ``units/troops/<name>`` assets carry army-count/level
badges and a different render, so they match the live roster at only ~0.5. A
tight face crop from the BRIGHT roster (army just cleared) localises at ~1.0.

Workflow:
  1. On the device, open Train Troops, clear the troops (so the roster is bright),
     and make sure the troop you want is visible in the roster.
  2. Run with the troop name + the face-box center/size you measured from a
     screenshot (use scripts/capture_screen.py + a grid to measure):

    python scripts/capture_face.py thrower --cx 760 --cy 815 --w 64 --h 54
    python scripts/capture_face.py archer  --cx 72  --cy 815

  Saves backend/assets/units/roster/<name>.png and verifies find_template locates
  it (prints confidence + center). Re-run with different --cx/--cy/--w/--h until
  the reported center sits on the troop and confidence is high (>0.9 same-frame).
"""
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import cv2  # noqa: E402

import app_paths  # noqa: E402
from core.vision import vision  # noqa: E402
from device_manager import manager  # noqa: E402

logging.basicConfig(level=logging.WARNING)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", help="troop name, e.g. thrower (saved as units/roster/<name>)")
    ap.add_argument("--cx", type=int, required=True, help="face center x")
    ap.add_argument("--cy", type=int, required=True, help="face center y")
    ap.add_argument("--w", type=int, default=64, help="face half-not: full width (px)")
    ap.add_argument("--h", type=int, default=54, help="full height (px)")
    args = ap.parse_args()

    ok, reason = manager.connect()
    if not ok:
        print("ERR connect:", reason)
        return 2
    frame = manager.capture_bgr()
    if frame is None:
        print("ERR no frame")
        return 3

    x1, x2 = args.cx - args.w // 2, args.cx + args.w // 2
    y1, y2 = args.cy - args.h // 2, args.cy + args.h // 2
    face = frame[y1:y2, x1:x2]
    out_dir = os.path.join(app_paths.ASSETS_DIR, "units", "roster")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{args.name}.png")
    cv2.imwrite(out, face)
    print(f"SAVED units/roster/{args.name}.png {face.shape[1]}x{face.shape[0]}")

    # Verify it localises.
    vision.load_assets(app_paths.ASSETS_DIR)
    loc = vision.find_template(frame, f"units/roster/{args.name}", threshold=0.7, use_orb_fallback=False)
    print(f"find_template -> {loc}  (expected near ({args.cx},{args.cy}))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
