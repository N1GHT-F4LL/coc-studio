# -*- coding: utf-8 -*-
"""calib/sendevent_effect_test.py — THE decisive sendevent test: find the
Attack button on the home screen, tap it with a raw sendevent single-finger
stream (Protocol B, same as Memu's own host clicks), and check whether the
attack screen opens. Then clean up back to home.
Run:  .venv/Scripts/python.exe calib/sendevent_effect_test.py"""
import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.normpath(os.path.join(HERE, "..", "backend"))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

import logging  # noqa: E402
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("setest")

import urllib.request  # noqa: E402
try:
    req = urllib.request.Request("http://127.0.0.1:8000/api/run/stop", method="POST",
                                 data=b"{}", headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=3)
    print("[setest] stopped the running loop")
except Exception:
    print("[setest] no run active")
out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                     stdin=subprocess.DEVNULL).stdout
for pid in {l.split()[-1] for l in out.splitlines()
            if ":8000" in l and "LISTENING" in l.upper()}:
    subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True,
                   stdin=subprocess.DEVNULL)

import blocks  # noqa: F401,E402
from device_manager import manager, load_settings  # noqa: E402
from engine.context import RuntimeContext  # noqa: E402
from blocks.coc_blocks import EnsureHome  # noqa: E402
from screens.attack_screen import AttackScreen  # noqa: E402
from screens.home_screen import HomeScreen  # noqa: E402

ok, reason = manager.connect()
print(f"[setest] connect {ok} ({reason})")
if not ok:
    sys.exit("no device")
dev, ui = manager.device, manager.ui_manager
settings = load_settings()
ctx = RuntimeContext(device=dev, ui_manager=ui, vision=None,
                     ocr_read=lambda *a, **k: (None, 0.0), settings=settings,
                     logger=log, stop_event=threading.Event(), vars={}, emit=lambda ev: None)
if not EnsureHome().run(ctx, {"zoom_out": False, "timeout": 10})["home"]:
    sys.exit("no home")

# find the Attack button
home = HomeScreen(ui)
screen = ui.get_screen()
from core.vision import vision  # noqa: E402
attack_loc = vision.find_template(screen, "buttons/home/btn_attack",
                                  threshold=0.7, use_orb_fallback=False)
print(f"[setest] Attack button at {attack_loc}")
if not attack_loc:
    sys.exit("Attack button not found — is the game on the home screen?")

EV_DEV, MAXX, MAXY = dev._find_touch_input_device()
SW, SH = dev.get_screen_size()


def sendevent_tap(x, y):
    """Single-finger Protocol B tap, exactly like Memu's own host clicks."""
    ex, ey = dev._pixel_to_event(x, y, MAXX, MAXY, SW, SH)
    script = (f"sendevent {EV_DEV} 3 53 {ex}; sendevent {EV_DEV} 3 54 {ey}; "
              f"sendevent {EV_DEV} 3 48 10; sendevent {EV_DEV} 3 57 0; "
              f"sendevent {EV_DEV} 0 0 0; sleep 1; "
              f"sendevent {EV_DEV} 3 53 0; sendevent {EV_DEV} 3 54 0; "
              f"sendevent {EV_DEV} 3 48 0; sendevent {EV_DEV} 3 57 -1")
    return dev._run_adb(["shell", script])


attack = AttackScreen(ui, settings)
success = 0
for attempt in range(3):
    screen = ui.get_screen()
    loc = vision.find_template(screen, "buttons/home/btn_attack",
                               threshold=0.7, use_orb_fallback=False)
    if not loc:
        print(f"[setest] attempt {attempt + 1}: Attack button not visible — re-ensuring home")
        EnsureHome().run(ctx, {"zoom_out": False, "timeout": 10})
        continue
    print(f"[setest] attempt {attempt + 1}: sendevent tap on Attack at {loc}")
    sendevent_tap(*loc)
    ui._poll_sleep(2.0)
    if attack.is_current_screen():
        success += 1
        print(f"[setest] *** ATTACK SCREEN OPENED — sendevent TAP WORKS ***")
        # close the attack menu back to home
        find_loc = ui.wait_until_appears("buttons/attack/btn_find_a_match",
                                         timeout=3, silent=True, use_orb_fallback=False)
        if find_loc:
            home.close_popups()
        home.close_popups()
        ui._poll_sleep(1.0)
        break
    else:
        print(f"[setest] attack screen did NOT open — sendevent tap had no effect")

print(f"[setest] RESULT: {success}/3 — "
      + ("sendevent injection WORKS on this device" if success else
         "sendevent injection is DEAD on this device (rc=0 but zero effect)"))
