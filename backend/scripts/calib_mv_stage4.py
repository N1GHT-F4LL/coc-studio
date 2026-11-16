"""Stage 4 — first REAL account switch + confirm_yes calibration (one run).

  home_v1.png snapshot (current = Antoine)
  -> prefix -> swap -> SWITCH ID -> tap ROW 2 (Nghiays)
  -> confirm dialog appears -> self-capture -> measure scid_confirm_yes
  -> tap Yes -> wait home (<=180s) -> capture home_v2.png
  -> round trip back to row 1 (Antoine) -> verify home
"""
import os
import sys
import time

sys.path.insert(0, r'C:\Users\antoinenguyen_09\Downloads\coc-studio\backend')

import ctypes
import json

ctypes.windll.user32.SetProcessDPIAware()
import ctypes.wintypes as wt
import cv2
import mss
import numpy as np
import subprocess

from core.vision import vision
from screens.home_screen import HomeScreen

S, OX, OY = 1.020, 3.0, 42.4
OUT = r'C:\Users\antoinenguyen_09\Downloads\coc-studio\backend\data\calib_debug\mv_calib'
ASSETS = r'C:\Users\antoinenguyen_09\Downloads\coc-studio\backend\assets'
MVP = r'C:\Users\antoinenguyen_09\Downloads\coc-studio\backend\data\multi_village.json'
SERIAL = '127.0.0.1:21503'

user32 = ctypes.windll.user32
hwnd = None


def _find_hwnd():
    global hwnd
    hwnd = None

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(h, _):
        global hwnd
        if user32.IsWindowVisible(h):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(h, buf, 256)
            if buf.value == 'MEmu':
                hwnd = h
        return True
    user32.EnumWindows(cb, 0)
    return hwnd


def adb_frame():
    p = subprocess.run(['adb', '-s', SERIAL, 'exec-out', 'screencap', '-p'],
                       capture_output=True, stdin=subprocess.DEVNULL, timeout=30)
    if p.returncode != 0 or not p.stdout:
        return None
    return cv2.imdecode(np.frombuffer(p.stdout, np.uint8), cv2.IMREAD_COLOR)


def tap(x, y):
    subprocess.run(['adb', '-s', SERIAL, 'shell', 'input', 'tap',
                    str(int(x)), str(int(y))],
                   capture_output=True, stdin=subprocess.DEVNULL)


def selfcap(tag):
    _find_hwnd()
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    mon = {'left': rect.left, 'top': rect.top,
           'width': rect.right - rect.left, 'height': rect.bottom - rect.top}
    with mss.mss() as sct:
        img = np.array(sct.grab(mon))[:, :, :3]
    os.makedirs(OUT, exist_ok=True)
    cv2.imwrite(os.path.join(OUT, f'selfcap_{tag}.png'), img)
    return img


def is_home(adb):
    atk = vision.find_template(adb, 'buttons/home/btn_attack', threshold=0.7,
                               use_orb_fallback=False)
    bld = vision.find_template(adb, 'buttons/home/btn_build', threshold=0.7,
                               use_orb_fallback=False)
    return bool(atk and bld)


def scid_page_up(cap):
    cg = cv2.cvtColor(cap, cv2.COLOR_BGR2GRAY)
    px1, py1 = int(OX + S * 1150), int(OY + S * 280)
    px2, py2 = int(OX + S * 1500), int(OY + S * 500)
    win = cg[py1:py2, px1:px2]
    _, dk = cv2.threshold(win, 90, 255, cv2.THRESH_BINARY_INV)
    return int(np.count_nonzero(dk)) > 800


def drive_to_switch_id():
    """prefix -> swap -> SCID page -> SWITCH ID -> the account list."""
    adb = adb_frame()
    if not is_home(adb):
        print('  not home — RELOAD GAME (416,558) + settings X recovery')
        tap(416, 558); time.sleep(15)
        tap(1382, 68); time.sleep(2)
        adb = adb_frame()
        if not is_home(adb):
            sys.exit('cannot reach home — inspect data/calib_debug/mv_calib/')
    tap(83, 92); time.sleep(2.5)
    tap(1263, 65); time.sleep(1.5)
    adb = adb_frame()
    g = cv2.cvtColor(adb, cv2.COLOR_BGR2GRAY)
    tpl = cv2.imread(os.path.join(ASSETS, 'multi_village', 'settings_tab.png'),
                     cv2.IMREAD_GRAYSCALE)
    r = cv2.matchTemplate(g, tpl, cv2.TM_CCOEFF_NORMED)
    _, c, _, _ = cv2.minMaxLoc(r)
    print(f'  panel conf {c:.3f}')
    if c < 0.8:
        sys.exit(f'panel verify failed ({c:.3f}) — aborting')
    tap(1050, 170); time.sleep(3.0)
    cap = selfcap('drive_scid')
    if not scid_page_up(cap):
        sys.exit('SCID page did not open — aborting')
    tap(1335, 375); time.sleep(3.0)
    cap = selfcap('drive_list')
    print('  account list up (SWITCH ID -> list)')


def wait_home_and_snapshot(idx, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        adb = adb_frame()
        if adb is not None and is_home(adb):
            print(f'  home verified for village {idx} '
                  f'({timeout - (deadline - time.time()):.0f}s)')
            os.makedirs(r'C:\Users\antoinenguyen_09\Downloads\coc-studio\backend'
                        r'\data\multi_village', exist_ok=True)
            path = (r'C:\Users\antoinenguyen_09\Downloads\coc-studio\backend'
                    r'\data\multi_village') + f'\\home_v{idx}.png'
            cv2.imwrite(path, adb)
            print(f'  snapshot saved: {path}')
            return True
        time.sleep(3.0)
    print(f'  home NOT verified within {timeout}s for village {idx}')
    return False


def main():
    vision.load_assets(ASSETS)
    _find_hwnd()

    cfg = json.load(open(MVP, encoding='utf-8'))
    coords = cfg['coords']
    row1 = coords['scid_first_row']
    row_h = coords['scid_row_height_px']

    adb = adb_frame()
    if not is_home(adb):
        sys.exit('game not on home — run the recovery first')
    print('home confirmed (Antoine)')
    os.makedirs(r'C:\Users\antoinenguyen_09\Downloads\coc-studio\backend'
                r'\data\multi_village', exist_ok=True)
    cv2.imwrite(r'C:\Users\antoinenguyen_09\Downloads\coc-studio\backend'
                r'\data\multi_village\home_v1.png', adb)
    print('home_v1.png snapshot saved (village 1 identity reference)')

    # --- switch to village 2 (row 2 = Nghiays) ------------------------------
    print('\n=== switching to village 2 (row 2) ===')
    drive_to_switch_id()
    row2 = (row1[0], row1[1] + row_h)
    print(f'  tapping row 2 at {row2}')
    tap(*row2); time.sleep(2.0)
    cap = selfcap('confirm_dialog')
    cv2.imwrite(os.path.join(OUT, 'confirm_dialog.png'), cap)

    # measure the positive button: the dialog is viewport-centered; the Yes
    # button is the saturated green blob in the lower half of the dialog
    cg = cv2.cvtColor(cap, cv2.COLOR_BGR2GRAY)
    # dialog band: device y 250-650, x 300-1300
    bx1, by1 = int(OX + S * 300), int(OY + S * 250)
    bx2, by2 = int(OX + S * 1300), int(OY + S * 650)
    band = cap[by1:by2, bx1:bx2]
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (35, 80, 120), (75, 255, 255))   # green button body
    ys, xs = np.where(mask > 0)
    if len(xs) < 500:
        cv2.imwrite(os.path.join(OUT, 'confirm_dialog_debug.png'), band)
        sys.exit('no green Continue/Yes blob found — inspect confirm_dialog.png')
    cx = int(np.mean(xs)) + bx1
    cy = int(np.mean(ys)) + by1
    print(f'  confirm dialog positive button at device ({cx},{cy}) '
          f'({len(xs)} green px)')
    cv2.drawMarker(cap, (cx, cy), (0, 255, 0), cv2.MARKER_CROSS, 24, 2)
    cv2.imwrite(os.path.join(OUT, 'confirm_dialog_measured.png'), cap)

    # --- write confirm_yes + tap it ------------------------------------------
    coords = cfg['coords']
    coords['scid_confirm_yes'] = [cx, cy]
    json.dump(cfg, open(MVP, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
    print('  scid_confirm_yes written into multi_village.json')
    tap(cx, cy)
    print('  tapped Yes — waiting for the village to load (<=180s)...')
    if not wait_home_and_snapshot(2):
        sys.exit('village 2 load failed — inspect the logs')

    # --- round trip back to village 1 ----------------------------------------
    print('\n=== round trip: back to village 1 (row 1) ===')
    drive_to_switch_id()
    tap(*row1); time.sleep(2.0)
    # confirm button position is the same dialog — reuse the measured point
    tap(cx, cy)
    print('  tapped Yes — waiting...')
    if not wait_home_and_snapshot(1):
        sys.exit('round-trip back to village 1 failed')

    print('\n===== RESULT =====')
    print('scid_confirm_yes =', [cx, cy])
    print('first real switch: village 2 OK + round trip OK')
    print('=====')


if __name__ == '__main__':
    main()
