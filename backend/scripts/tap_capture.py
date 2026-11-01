"""Calibration helper: tap a coordinate (or not) then capture the screen.

Used to interactively map the army-screen edit flow (trash/clear, add-troop
slots) by tapping and screenshotting one step at a time.

Usage (from anywhere, venv python):
    python scripts/tap_capture.py OUT.png            # just capture
    python scripts/tap_capture.py OUT.png X Y        # tap (X,Y) then capture
    python scripts/tap_capture.py OUT.png X Y N      # tap (X,Y) N times then capture
"""
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import cv2  # noqa: E402

from device_manager import manager  # noqa: E402

logging.basicConfig(level=logging.WARNING)


def main():
    out = sys.argv[1]
    x = int(sys.argv[2]) if len(sys.argv) > 2 else None
    y = int(sys.argv[3]) if len(sys.argv) > 3 else None
    n = int(sys.argv[4]) if len(sys.argv) > 4 else 1

    ok, reason = manager.connect()
    if not ok:
        print("ERR connect:", reason)
        return 2
    ui = manager.ui_manager
    if x is not None and y is not None:
        for _ in range(n):
            ui.click(x, y)
            ui._poll_sleep(0.35)
        print(f"TAPPED ({x},{y}) x{n}")
        ui._poll_sleep(0.6)

    frame = manager.capture_bgr()
    if frame is None:
        print("ERR no frame")
        return 3
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    cv2.imwrite(out, frame)
    print(f"SAVED {out} {frame.shape[1]}x{frame.shape[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
