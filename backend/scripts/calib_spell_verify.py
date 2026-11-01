"""Spell-points VERIFY capture (device, USER-RUN) — dragon_balloon.

12 captures = 3 bases x 4 variants. Each capture lands on a FRESH scout screen
(the script taps Next — the camera recenters every base), then replays the
runtime opening EXACTLY: multi_zoom_out (u2 pinch, same as ensure_home) +
the variant's pan node (`input swipe ... 900` + 1.0s settle, same as
_slot_deploy), then screencaps and draws the spell points on the frame.

Scout view == battle view (the camera carries over) — this verifies the
coordinates without spending an army.

Run (from backend/):  ..\\.venv\\Scripts\\python.exe -X utf8 scripts\\calib_spell_verify.py
Prereqs: bot STOPPED (no active run), CoC on any scout screen (Next visible).
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)

import cv2  # noqa: E402
from calib_spell_points import SPELL_POINTS  # noqa: E402  single source of points

DEBUG_DIR = os.path.join(BACKEND, "data", "calib_debug")
VARIANTS = ("9-12", "12-3", "3-6", "6-9")
NEXT_TPL = os.path.join(BACKEND, "assets", "buttons", "attack", "btn_next_enemy.png")
NEXT_THRESHOLD = 0.65


def banner(msg):
    print("\n" + "=" * 64)
    print(msg)
    print("=" * 64)


def step_msg(msg):
    print(f"\n>>> {msg}")


def wait_enter(note=""):
    if note:
        print(f"    ({note})")
    input("    Nhấn ENTER ở CỬA SỔ TERMINAL NÀY (click chọn nó trước) > ")


def run_adb(serial, args, adb="adb"):
    """Short-lived adb call with stdin isolated (never races our input())."""
    return subprocess.run([adb, "-s", serial] + args, capture_output=True,
                          stdin=subprocess.DEVNULL, timeout=30)


def screencap(serial, adb="adb"):
    p = run_adb(serial, ["exec-out", "screencap", "-p"], adb=adb)
    if p.returncode != 0 or not p.stdout:
        return None
    arr = np_from_buffer(p.stdout)
    return arr


def np_from_buffer(buf):
    import numpy as np
    arr = np.frombuffer(buf, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def tap(serial, x, y, adb="adb"):
    run_adb(serial, ["shell", "input", "tap", str(int(x)), str(int(y))], adb=adb)


def swipe(serial, x1, y1, x2, y2, ms, adb="adb"):
    run_adb(serial, ["shell", "input", "swipe",
                     str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)),
                     str(int(ms))], adb=adb)


def find_next(frame):
    """Locate the Next button by template match; None if not visible."""
    tpl = cv2.imread(NEXT_TPL, cv2.IMREAD_COLOR)
    if tpl is None or frame is None:
        return None
    res = cv2.matchTemplate(frame, tpl, cv2.TM_CCOEFF_NORMED)
    _, mv, _, ml = cv2.minMaxLoc(res)
    if mv < NEXT_THRESHOLD:
        return None
    return (ml[0] + tpl.shape[1] // 2, ml[1] + tpl.shape[0] // 2), mv


def backend_up():
    """Best-effort: is the coc-studio backend alive? (no GET run-state endpoint
    exists, so an active RUN can only be excluded by the user — banner line)."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=2):
            return True
    except Exception:
        return False


def load_pan(serial, variant, adb):
    """Runtime-identical opening for one variant: zoom-out + pan + settle."""
    from zoom_out import multi_zoom_out
    step_msg(f"[{variant}] ZOOMING OUT (u2 pinch, như runtime)...")
    if not multi_zoom_out(serial):
        print("    ! zoom-out không xác nhận — vẫn tiếp tục (zoom hiện tại được dùng)")
    with open(os.path.join(BACKEND, "data", "scenarios", "dragon_balloon.json"),
              encoding="utf-8") as f:
        doc = json.load(f)
    pan = next(n for n in doc["variants"][VARIANTS.index(variant)]["nodes"]
               if n.get("type") == "pan")
    x1, y1, x2, y2 = (int(pan.get(k) or 0) for k in ("x1", "y1", "x2", "y2"))
    step_msg(f"[{variant}] PAN ({x1},{y1})->({x2},{y2}) đúng 900ms như _slot_deploy...")
    swipe(serial, x1, y1, x2, y2, 900, adb=adb)
    time.sleep(1.0)                    # same settle as the pan node


def draw_points(frame, variant):
    img = frame.copy()
    for pt in SPELL_POINTS[variant]["rage"]:
        cv2.circle(img, tuple(pt), 9, (0, 0, 255), -1)
        cv2.circle(img, tuple(pt), 16, (0, 0, 255), 2)
    for pt in SPELL_POINTS[variant]["freeze"]:
        cv2.drawMarker(img, tuple(pt), (255, 0, 255), cv2.MARKER_TILTED_CROSS, 26, 3)
    return img


def main():
    with open(os.path.join(BACKEND, "data", "settings.json"), encoding="utf-8") as f:
        serial = json.load(f)["device"]["serial"]

    banner("VERIFY SPELL POINTS — 12 frame (3 base x 4 variant)")
    if backend_up():
        print("!! Backend :8000 đang sống — nếu bot đang RUN thì STOP trước,")
        print("   script này sẽ đụng ADB trực tiếp cùng lúc với run là hỏng cả hai.")
    step_msg(f"Device: {serial}. YÊU CẦU: (1) bot KHÔNG đang chạy; "
             "(2) CoC ở màn SCOUT base địch bất kỳ (nút Next thấy được); "
             "(3) KHÔNG chạm vào Memu trong lúc script thao tác.")
    wait_enter("đã đặt CoC ở màn scout, sẵn sàng bắt đầu")

    os.makedirs(DEBUG_DIR, exist_ok=True)
    saved = []
    for i in range(12):
        variant = VARIANTS[i % 4]
        base_no = i // 4 + 1
        banner(f"Lần chụp {i + 1}/12 — variant {variant} (base #{base_no})")

        if i > 0:
            frame = screencap(serial)
            hit = find_next(frame)
            if hit:
                (nx, ny), conf = hit
                step_msg(f"Tap Next (conf {conf:.2f}) sang base mới...")
                tap(serial, nx, ny)
                time.sleep(2.5)        # base load + scout settle
            else:
                step_msg("KHÔNG thấy nút Next — bạn tự sang base kế tiếp")
                wait_enter("đã ở màn scout của base MỚI")

        load_pan(serial, variant, "adb")

        step_msg(f"[{variant}] Chụp màn hình...")
        frame = screencap(serial)
        if frame is None:
            print("    ! screencap thất bại — bỏ lần này, ENTER để thử tiếp")
            wait_enter()
            continue
        raw = os.path.join(DEBUG_DIR, f"spell_verify_raw_{variant}_{i + 1}.png")
        out = os.path.join(DEBUG_DIR, f"spell_verify_{variant}_{i + 1}.png")
        cv2.imwrite(raw, frame)
        cv2.imwrite(out, draw_points(frame, variant))
        saved.append(out)
        print(f"    saved {os.path.relpath(out, BACKEND)}")

    banner("HOÀN TẤT — RESULT")
    print(f"Đã lưu {len(saved)}/12 frame verify (đỏ=rage x4, X tím=freeze x3):")
    for p in saved:
        print("  ", os.path.relpath(p, BACKEND))
    print("\nCopy khối RESULT này + trả lời: mọi điểm đỏ/X có nằm trên building")
    print("của base sau pan không (cho phép sai lệch nhỏ vì base khác nhau)?")
    print("=====")
    print("RESULT spell_verify:")
    print("  files:", len(saved))
    print("  dir: backend/data/calib_debug/spell_verify_*.png")
    print("=====")


if __name__ == "__main__":
    main()
