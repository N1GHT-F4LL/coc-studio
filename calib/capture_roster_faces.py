"""Capture the bright roster strip frames for every section (troop/spell/siege)
so missing roster faces (units/roster/balloon, freeze, stone_slammer) can be
cropped from the REAL roster render.

Runs standalone (its own device session), navigates with the proven
TrainScreen flow, and saves frames to calib/roster_frames/. NO training taps.
"""
import os
import sys
import time

sys.path.insert(0, r"C:\Users\antoinenguyen_09\Downloads\coc-studio\backend")
import cv2

OUT = r"C:\Users\antoinenguyen_09\Downloads\coc-studio\calib\roster_frames"
os.makedirs(OUT, exist_ok=True)

from device_manager import manager
from popup_guard import boot_recovery
from screens.home_screen import HomeScreen
from screens.train_screen import TrainScreen, ROSTER_SEARCH_STEPS


def wait_home(timeout=120):
    home = HomeScreen(manager.ui_manager)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if home.is_current_screen():
            return True
        time.sleep(3)
    return False


def main():
    ok, reason = manager.connect()
    print("connect:", ok, reason)
    if not ok:
        sys.exit(1)
    if not wait_home(30):
        print("not home — force-stop + relaunch for a clean state...")
        boot_recovery()
        if not wait_home(150):
            print("home NOT reached — abort"); sys.exit(1)
    print("home verified — opening the army screen...")
    ui = manager.ui_manager
    train = TrainScreen(ui)
    if not train.open():
        print("army screen NOT opened — abort"); sys.exit(1)

    for kind in ("troop", "spell", "siege"):
        train.open_roster(kind)
        time.sleep(0.8)
        for i in range(len(ROSTER_SEARCH_STEPS) + 1):
            frame = ui.get_screen()
            if frame is not None:
                path = os.path.join(OUT, f"{kind}_{i}.png")
                cv2.imwrite(path, frame)
                print("saved", path)
            if i < len(ROSTER_SEARCH_STEPS):
                (sx, sy), (ex, ey) = ROSTER_SEARCH_STEPS[i]
                manager.device.swipe([(sx, sy), (ex, ey)])
                time.sleep(0.9)
        train.close_roster()
        time.sleep(0.5)

    train.back_home()
    print("done — frames in calib/roster_frames/")


if __name__ == "__main__":
    main()
