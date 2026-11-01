"""Capture Treasure-event frames for hammer-template calibration (USER-RUN).

Produces three 1600x900 frames in backend/data/calib_debug/:
  treasure_active.png — home village WITH the event banner visible
  treasure_chest.png  — the event screen right after the block's 4 chest taps
                        (verifies the Return Home tap target)
  treasure_clean.png  — home village WITHOUT the banner (clean baseline)

Step 2 replays the block's real sequence (tap TREASURE_TAP x4 @0.2s, wait 4s)
using the constants imported from popup_guard — single source of truth.

Run (from backend/):  ..\\.venv\\Scripts\\python.exe -X utf8 scripts\\capture_treasure_frames.py
Prereq: bot STOPPED; CoC on the home village; treasure banner active.
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from popup_guard import TREASURE_HOME_TAP, TREASURE_TAP  # noqa: E402  constants only

DEBUG_DIR = os.path.join(BACKEND, "data", "calib_debug")


def banner(msg):
    print("\n" + "=" * 64)
    print(msg)
    print("=" * 64)


def wait_enter(note=""):
    if note:
        print(f"    ({note})")
    input("    Nhấn ENTER ở CỬA SỔ TERMINAL NÀY (click chọn nó trước) > ")


def run_adb(serial, args, adb="adb"):
    return subprocess.run([adb, "-s", serial] + args, capture_output=True,
                          stdin=subprocess.DEVNULL, timeout=30)


def screencap(serial, adb="adb"):
    for _ in range(2):  # one retry on a black frame (same guard as popup_guard)
        p = run_adb(serial, ["exec-out", "screencap", "-p"], adb=adb)
        if p.returncode == 0 and p.stdout:
            arr = cv2.imdecode(np.frombuffer(p.stdout, np.uint8), cv2.IMREAD_COLOR)
            if arr is not None and float(arr.mean()) >= 2.0:
                return arr
        time.sleep(0.4)
    return None


def save(frame, name):
    path = os.path.join(DEBUG_DIR, name)
    cv2.imwrite(path, frame)
    print(f"    saved {os.path.relpath(path, BACKEND)}")
    return path


def main():
    import json
    with open(os.path.join(BACKEND, "data", "settings.json"), encoding="utf-8") as f:
        serial = json.load(f)["device"]["serial"]
    os.makedirs(DEBUG_DIR, exist_ok=True)

    banner("CHỤP FRAME HIỆU CHUẨN TREASURE EVENT — 3 frame")
    print("Yêu cầu: bot KHÔNG đang chạy; CoC ở màn hình LÀNG (home).")
    print(f"Hằng số dùng từ popup_guard: TREASURE_TAP={TREASURE_TAP}, "
          f"TREASURE_HOME_TAP={TREASURE_HOME_TAP}")

    banner("BƯỚC 1/3 — frame CÓ banner (hammer đang hiện ở dải dưới)")
    wait_enter("đã đứng ở home và THẤY banner treasure event")
    active = screencap(serial)
    if active is None:
        sys.exit("screencap thất bại — kiểm tra adb/Memu rồi chạy lại")
    save(active, "treasure_active.png")

    banner("BƯỚC 2/3 — mở event đúng như block làm (4 tap + chờ 4s)")
    wait_enter("sẵn sàng để script tap vào banner/chest")
    for _ in range(4):
        time.sleep(0.2)
        run_adb(serial, ["shell", "input", "tap", str(TREASURE_TAP[0]), str(TREASURE_TAP[1])])
    time.sleep(4)
    chest = screencap(serial)
    if chest is None:
        sys.exit("screencap thất bại sau khi mở event — chạy lại từ bước 1")
    save(chest, "treasure_chest.png")
    print("    -> nhìn Memu: màn event/reward đang mở (Return Home sẽ ở ~(788,751))")

    banner("BƯỚC 3/3 — tap Return Home rồi chụp frame home SẠCH")
    wait_enter("sẵn sàng để script tap Return Home")
    run_adb(serial, ["shell", "input", "tap", str(TREASURE_HOME_TAP[0]), str(TREASURE_HOME_TAP[1])])
    time.sleep(3)
    print("    Nếu chưa về home / banner còn hiện, hãy xử lý tay cho home SẠCH KHÔNG banner.")
    wait_enter("đang ở home KHÔNG banner")
    clean = screencap(serial)
    if clean is None:
        sys.exit("screencap thất bại — chạy lại bước này bằng cách chạy lại script")
    save(clean, "treasure_clean.png")

    banner("HOÀN TẤT — RESULT")
    print("=====")
    print("RESULT capture_treasure_frames:")
    print("  active: backend/data/calib_debug/treasure_active.png")
    print("  chest : backend/data/calib_debug/treasure_chest.png")
    print("  clean : backend/data/calib_debug/treasure_clean.png")
    print("=====")
    print("Copy RESULT này về cho agent đo active_max / clean_max.")


if __name__ == "__main__":
    main()
