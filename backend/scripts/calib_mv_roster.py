"""MV roster enumeration — scroll the SCID account list and OCR every account.

Drive: prefix -> swap -> SWITCH ID -> the account-list page, then loop:
  self-capture (desktop mss — sees through FLAG_SECURE) -> OCR the right panel
  -> extract account rows (the NAME line sits ~55-70px above each
  'Town Hall: NN' marker) -> merge new names -> swipe up 250px inside the list
  -> repeat (max 8 rounds) until the 'Log in to Supercell ID' terminator row
  is visible, or two consecutive scrolls yield zero new names.

Per-account geometry is recorded as (scroll_round, tap_y) so the runtime can
replay: [scroll x prelude] -> tap (1300, y).

Run:  ../.venv/Scripts/python.exe -X utf8 scripts/calib_mv_roster.py
"""
import os
import re
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

from core.ocr import _get_reader, warmup_ocr
from core.vision import vision

OUT = r'C:\Users\antoinenguyen_09\Downloads\coc-studio\backend\data\calib_debug\mv_calib'
ASSETS = r'C:\Users\antoinenguyen_09\Downloads\coc-studio\backend\assets'
SERIAL = '127.0.0.1:21503'
S, OX, OY = 1.020, 3.0, 42.4        # desktop<->device mapping (re-derived if the rect moves)

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


def swipe(x, y1, y2, ms=400):
    subprocess.run(['adb', '-s', SERIAL, 'shell', 'input', 'swipe',
                    str(int(x)), str(int(y1)), str(int(x)), str(int(y2)), str(int(ms))],
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
    cv2.imwrite(os.path.join(OUT, f'roster_{tag}.png'), img)
    return img


def is_home(adb):
    atk = vision.find_template(adb, 'buttons/home/btn_attack', threshold=0.7,
                               use_orb_fallback=False)
    bld = vision.find_template(adb, 'buttons/home/btn_build', threshold=0.7,
                               use_orb_fallback=False)
    return bool(atk and bld)


def drive_to_list():
    """reset to the list TOP: close any open SCID page (X) -> re-open via the
    verified prefix -> swap -> SWITCH ID. The list always opens scrolled to
    the top, giving deterministic absolute row positions."""
    tap(1548, 51); time.sleep(2.0)   # close the SCID page if it was open
    for attempt in range(2):
        adb = adb_frame()
        if adb is None:
            sys.exit('no adb frame — device offline?')
        if is_home(adb):
            print('  home verified — driving the prefix')
            tap(83, 92); time.sleep(2.5)
            tap(1263, 65); time.sleep(1.5)
        else:
            print('  not home — settings panel assumed open, tapping swap directly')
        adb = adb_frame()
        g = cv2.cvtColor(adb, cv2.COLOR_BGR2GRAY)
        tpl = cv2.imread(os.path.join(ASSETS, 'multi_village', 'settings_tab.png'),
                         cv2.IMREAD_GRAYSCALE)
        r = cv2.matchTemplate(g, tpl, cv2.TM_CCOEFF_NORMED)
        _, c, _, _ = cv2.minMaxLoc(r)
        print(f'  panel conf {c:.3f}')
        if c < 0.8:
            if attempt == 0:
                print('  panel not open — RELOAD GAME recovery, then retry')
                tap(416, 558); time.sleep(15)
                continue
            sys.exit('panel verify failed twice — aborting')
        tap(1050, 170); time.sleep(3.0)
        cap = selfcap('pre_switchid')
        cg = cv2.cvtColor(cap, cv2.COLOR_BGR2GRAY)
        px1, py1 = int(OX + S * 1150), int(OY + S * 280)
        px2, py2 = int(OX + S * 1500), int(OY + S * 500)
        win = cg[py1:py2, px1:px2]
        _, dk = cv2.threshold(win, 90, 255, cv2.THRESH_BINARY_INV)
        if int(np.count_nonzero(dk)) > 400:
            print('  SCID page already up — skipping SWITCH ID tap')
            return
        tap(1335, 375); time.sleep(3.0)
        return
    sys.exit('could not reach the SCID page')


def ocr_panel(cap, reader):
    """OCR the SCID right panel -> (names_with_y, terminator_found, th_markers)."""
    cg = cv2.cvtColor(cap, cv2.COLOR_BGR2GRAY)
    rx1 = int(OX + S * 1000)
    rx2 = min(cap.shape[1], int(OX + S * 1600) + 30)
    panel = cap[:, rx1:rx2]
    items = reader.readtext(cv2.cvtColor(panel, cv2.COLOR_BGR2RGB),
                            detail=1, paragraph=False)
    lines = []   # (shot_y, device_y, text, conf)
    for b, t, cf in items:
        t = str(t).strip()
        if not t or float(cf) < 0.35 or len(b) < 2:
            continue
        try:
            xs_box = [pt[0] for pt in b]        # b = 4 corner points [x, y]
            ys_box = [pt[1] for pt in b]
            top_y = min(ys_box)
            d_y = (top_y - OY) / S
            d_x = ((min(xs_box) + max(xs_box)) / 2 - OX) / S
            lines.append((top_y, d_y, t, float(cf), d_x))
        except Exception:
            continue
    lines.sort()
    names = []       # (device_y, name)
    terminator = False
    for _sy, dy, t, cf, dx in lines:
        tl = t.lower()
        if 'log in to supercell' in tl:
            terminator = True
        if re.match(r'^town hall', tl):
            # the account NAME sits ~55-70px above its Town Hall marker
            cands = [l for l in lines if 15 <= dy - l[1] <= 80 and l[1] < dy]
            if cands:
                best = min(cands, key=lambda l: dy - l[1])
                names.append((int(dy - 62), best[2]))
    # de-dup names by (rounded y, lowercased text)
    seen = set()
    uniq = []
    for y, n in names:
        k = (round(y / 10), n.lower())
        if k not in seen:
            seen.add(k)
            uniq.append((y, n))
    return uniq, terminator, lines


def main():
    vision.load_assets(ASSETS)
    warmup_ocr()
    reader = _get_reader()
    _find_hwnd()

    print('=== driving to the account list ===')
    drive_to_list()

    roster = []          # ordered unique names, first-seen order
    roster_geo = {}      # name -> (scroll_round, device_y at that round)
    terminator_seen = False
    no_new_streak = 0

    for rnd in range(8):
        cap = selfcap(f'round{rnd}')
        names, terminator, lines = ocr_panel(cap, reader)
        new = []
        for y, n in names:
            known = any(n.lower() == r.lower() for r in roster)
            if not known:
                roster.append(n)
                roster_geo[n] = (rnd, y)
                new.append(n)
        print(f'round {rnd}: {len(names)} row(s) visible, {len(new)} new — '
              f'roster {roster}')
        if terminator:
            terminator_seen = True
            print('  terminator "Log in to Supercell ID" visible — list fully enumerated')
            break
        if not new:
            no_new_streak += 1
            if no_new_streak >= 2:
                print('  two scrolls with zero new names — stopping (no terminator '
                      'seen; the list may be longer than 8 scrolls)')
                break
        else:
            no_new_streak = 0
        swipe(1300, 600, 450)
        time.sleep(1.8)

    print(f'\n===== ROSTER ({len(roster)} accounts) =====')
    for i, n in enumerate(roster, 1):
        rnd, y = roster_geo.get(n, (0, 0))
        print(f'  {i}. {n}  (scroll round {rnd}, tap_y {y})')
    print('====================')

    out = {'roster': roster,
           'geometry': {n: {'scroll_round': rnd, 'tap_y': y}
                        for n, (rnd, y) in roster_geo.items()},
           'terminator_seen': terminator_seen}
    with open(os.path.join(OUT, 'roster.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f'saved: {os.path.join(OUT, "roster.json")}')
    print('Pick the farming targets (max 5, in rotation order) and tell me — '
          'I will bind villages to them and finish the calibration.')


if __name__ == '__main__':
    main()
