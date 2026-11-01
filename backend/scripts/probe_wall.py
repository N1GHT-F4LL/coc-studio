"""One-off probe: find wall segments on the live screen and optionally tap one.

Usage (from backend/):
    python scripts/probe_wall.py                # list wall template matches
    python scripts/probe_wall.py --tap          # tap the best match, capture after
    python scripts/probe_wall.py --tap-at X Y   # tap exact coords, capture after
"""
import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import cv2  # noqa: E402

import app_paths  # noqa: E402
from core.vision import vision  # noqa: E402
from device_manager import manager  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("probe_wall")

WALL_TEMPLATES = [
    "buildings/walls/wall",
    "buildings/walls/wall_2",
    "buildings/walls/wall_3",
    "buildings/walls/wall_4",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tap", action="store_true")
    ap.add_argument("--tap-at", nargs=2, type=int, default=None)
    ap.add_argument("--out", default=os.path.join("..", "_probe", "after_tap.png"))
    args = ap.parse_args()

    ok, reason = manager.connect()
    log.info("connect: ok=%s reason=%s", ok, reason)
    if not ok:
        sys.exit(1)

    screen = manager.device.get_screen()
    best = None
    for name in WALL_TEMPLATES:
        if name not in vision.cache:
            log.info("%s: not in cache", name)
            continue
        matches = vision.find_all_matches(screen, name, threshold=0.7, min_distance=40)
        log.info("%s: %d matches %s", name, len(matches), matches[:5])
        if matches and best is None:
            best = matches[0]

    target = tuple(args.tap_at) if args.tap_at else best
    if (args.tap or args.tap_at) and target:
        log.info("tapping %s", target)
        manager.device.tap(*target)
        time.sleep(1.5)
        after = manager.device.get_screen()
        out = os.path.abspath(args.out)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        cv2.imwrite(out, after)
        log.info("saved %s", out)


if __name__ == "__main__":
    main()
