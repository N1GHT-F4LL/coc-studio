"""FULLY AUTONOMOUS SCID calibration — state-machine driven, one continuous run.

States (detected from adb + desktop self-captures):
  HOME          -> drive the verified prefix (hut -> tab-verify -> swap)
  SETTINGS PANEL-> tap swap directly (panel already open)
  SCID PAGE UP  -> skip straight to the account-list measurement
  UNKNOWN       -> RELOAD GAME (416,558), wait, re-check

Sequence: [state machine] -> SWITCH ID (1335,375) -> account list -> OCR rows ->
measure scid_first_row + scid_row_height_px -> log the roster -> close safely
(SCID X 1548,51 -> settings X 1382,68) -> home check.
"""
import json
import os
import sys
import time

sys.path.insert(0, r'C:\Users\antoinenguyen_09\Downloads\coc-studio\backend')

import ctypes
import threading

ctypes.windll.user32.SetProcessDPIAware()
import ctypes.wintypes as wt
import cv2
import mss
import numpy as np
import subprocess

from core.ocr import _get_reader, warmup_ocr
from core.vision import vision

S, OX, OY = 1.020, 3.0, 42.4        # desktop<->device mapping (left-strip derived)
OUT = r'C:\Users\antoinenguyen_09\Downloads\coc-studio\backend\data\calib_debug\mv_calib'
ASSETS = r'C:\Users\antoinenguyen_09\Downloads\coc-studio\backend\assets'
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


def selfcap(tag=''):
    _find_hwnd()
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    mon = {'left': rect.left, 'top': rect.top,
           'width': rect.right - rect.left, 'height': rect.bottom - rect.top}
    with mss.mss() as sct:
        img = np.array(sct.grab(mon))[:, :, :3]
    if tag:
        os.makedirs(OUT, exist_ok=True)
        cv2.imwrite(os.path.join(OUT, f'selfcap_{tag}.png'), img)
    return img


def is_home(adb):
    atk = vision.find_template(adb, 'buttons/home/btn_attack', threshold=0.7,
                               use_orb_fallback=False)
    bld = vision.find_template(adb, 'buttons/home/btn_build', threshold=0.7,
                               use_orb_fallback=False)
    return bool(atk and bld)


def settings_panel_open(adb):
    g = cv2.cvtColor(adb, cv2.COLOR_BGR2GRAY)
    tpl = cv2.imread(os.path.join(ASSETS, 'multi_village', 'settings_tab.png'),
                     cv2.IMREAD_GRAYSCALE)
    r = cv2.matchTemplate(g, tpl, cv2.TM_CCOEFF_NORMED)
    _, c, _, _ = cv2.minMaxLoc(r)
    return c >= 0.8, c


def scid_page_up(cap):
    cg = cv2.cvtColor(cap, cv2.COLOR_BGR2GRAY)
    px1, py1 = int(OX + S * 1150), int(OY + S * 280)
    px2, py2 = int(OX + S * 1500), int(OY + S * 500)
    win = cg[py1:py2, px1:px2]
    _, dk = cv2.threshold(win, 90, 255, cv2.THRESH_BINARY_INV)
    return int(np.count_nonzero(dk)) > 400


def main():
    os.makedirs(OUT, exist_ok=True)
    vision.load_assets(ASSETS)
    warmup_ocr()
    reader = _get_reader()
    _find_hwnd()

    # --- state machine -----------------------------------------------------
    adb = adb_frame()
    home = is_home(adb)
    panel, pc = settings_panel_open(adb) if adb is not None else (False, 0.0)
    print(f'state: home={home}, settings_panel={panel} (conf {pc:.3f})')

    if home:
        print('HOME -> driving the verified prefix')
        tap(83, 92); time.sleep(2.5)
        tap(1263, 65); time.sleep(1.5)
        adb = adb_frame()
        panel, pc = settings_panel_open(adb)
        print(f'  panel after hut+tab: {panel} (conf {pc:.3f})')
        if not panel:
            sys.exit('panel verify failed after prefix — aborting (home preserved)')
        tap(1050, 170); time.sleep(3.0)
    elif panel:
        print('SETTINGS PANEL open -> tapping swap directly')
        tap(1050, 170); time.sleep(3.0)
    else:
        print('UNKNOWN state -> RELOAD GAME + prefix')
        tap(416, 558); time.sleep(18)
        tap(83, 92); time.sleep(2.5)
        tap(1263, 65); time.sleep(1.5)
        adb = adb_frame()
        panel, pc = settings_panel_open(adb)
        print(f'  panel after reload+prefix: {panel} (conf {pc:.3f})')
        if not panel:
            sys.exit('panel verify failed after recovery — aborting')
        tap(1050, 170); time.sleep(3.0)

    cap = selfcap('scid_page')
    up = scid_page_up(cap)
    print(f'SCID page up: {up}')
    if not up:
        sys.exit('SCID page did not open — aborting (page closed on its own?)')

    # --- SWITCH ID -> account list ------------------------------------------
    tap(1335, 375); time.sleep(3.0)
    cap = selfcap('scid_list')
    print('account list captured')

    # --- OCR the rows (right panel, device x >= 1020) -----------------------
    cg = cv2.cvtColor(cap, cv2.COLOR_BGR2GRAY)
    rx1 = int(OX + S * 1020)
    rx2 = min(cap.shape[1], int(OX + S * 1600) + 20)
    panel_img = cap[:, rx1:rx2]
    items = reader.readtext(cv2.cvtColor(panel_img, cv2.COLOR_BGR2RGB),
                            detail=1, paragraph=False)
    texts = []
    for b, t, cf in items:
        t = str(t).strip()
        if t and float(cf) >= 0.4 and len(t) >= 3:
            texts.append((t, float(cf), b[0][0] + rx1, b[0][1]))
    th_rows = []
    for t, cf, bx, by in texts:
        print(f'  OCR ({bx},{by}): {t!r} c={cf:.2f}')
        if 'Town Hall' in t:
            th_rows.append((t, by))

    # --- derive first_row / row_height ---------------------------------------
    print()
    if len(th_rows) >= 2:
        ys = sorted(by for _, by in th_rows)
        row_h = int(round(ys[1] - ys[0]))
        # row-1 tap centre: just below the first account NAME line (names sit
        # above the Town Hall markers; name-to-name pitch == row height)
        # the account name sits ~60px above its Town Hall marker (measured:
        # 625-566 / 773-711 / 921-860) — tap just below the name line
        first_y = int(ys[0] - 55)
        result = {'scid_row_height_px': row_h,
                  'scid_first_row': [1300, first_y],
                  'rows_top_to_bottom': [t for t, _ in th_rows],
                  'town_hall_markers': len(th_rows)}
        print('===== RESULT =====')
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print('=====')
        with open(os.path.join(OUT, 'scid_rows.json'), 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        # write into multi_village.json (the two measured values only)
        mvp = r'C:\Users\antoinenguyen_09\Downloads\coc-studio\backend\data\multi_village.json'
        cfg = json.load(open(mvp, encoding='utf-8'))
        cfg['coords']['scid_row_height_px'] = row_h
        cfg['coords']['scid_first_row'] = [1300, first_y]
        json.dump(cfg, open(mvp, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
        print('written into data/multi_village.json')
    else:
        print(f'only {len(th_rows)} Town-Hall marker(s) — the list may need scrolling')

    # --- close safely ---------------------------------------------------------
    tap(1548, 51); time.sleep(2.0)
    tap(1382, 68); time.sleep(2.0)
    adb = adb_frame()
    home = is_home(adb)
    print(f'closed: back home = {home}')


if __name__ == '__main__':
    main()
