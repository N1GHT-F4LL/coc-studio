"""Calibration helper: capture the current device screen to a PNG.

Connects the device (BlueStacks via ADB), optionally taps "Train Troops" to
open the army screen, then saves whatever is currently on screen so regions /
template crops can be measured from a real frame.

Usage (from backend/, with the venv python):
    python scripts/capture_screen.py OUT.png            # capture current screen
    python scripts/capture_screen.py OUT.png --train    # ensure home -> tap Train Troops, then capture

Prints the saved path and the frame resolution (W x H).
"""
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import cv2  # noqa: E402

from device_manager import manager, load_settings, save_settings, COC_PACKAGE  # noqa: E402
from screens.home_screen import HomeScreen  # noqa: E402
from screens.train_screen import TRAIN_TROOPS_BUTTON  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("capture")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", help="output PNG path")
    ap.add_argument("--train", action="store_true", help="ensure home then tap Train Troops first")
    args = ap.parse_args()

    ok, reason = manager.connect()
    log.info("connect: ok=%s reason=%s", ok, reason)
    if not ok:
        log.error("device not connected — is BlueStacks running on 127.0.0.1:5555?")
        return 2

    ui = manager.ui_manager
    dev = manager.device

    if args.train:
        dev.ensure_coc_ready(COC_PACKAGE, load_settings(), save_settings, log)
        home = HomeScreen(ui)
        for _ in range(3):
            home.close_popups()
            ui._poll_sleep(0.5)
        loc = ui.wait_until_appears(TRAIN_TROOPS_BUTTON, timeout=8, silent=True)
        if loc:
            log.info("tapping Train Troops at %s", loc)
            ui.click(*loc)
            ui._poll_sleep(1.5)
        else:
            log.warning("Train Troops button not found — capturing current screen instead.")

    frame = manager.capture_bgr()
    if frame is None:
        log.error("no frame captured.")
        return 3
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    cv2.imwrite(args.out, frame)
    h, w = frame.shape[:2]
    log.info("saved %s (%dx%d)", args.out, w, h)
    print(f"SAVED {args.out} {w}x{h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
