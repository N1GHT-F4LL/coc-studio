"""PASSIVE loot-frame collector — screencap only, never taps.

Runs alongside the user's active bot: polls adb screencaps, saves frames that
show the scout screen (Next button anchor), and attaches to /ws/run as a
passive listener to log the bot's own 'Enemy loot' lines for cross-reference.

Output: backend/data/calib_debug/loot_frames/frame_<ts>.png + loot_log.txt
Run:  ../.venv/Scripts/python.exe -X utf8 ../calib/passive_loot_capture.py [duration_s]
"""
import asyncio
import json
import os
import subprocess
import sys
import threading
import time

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(HERE, "..", "backend")
sys.path.insert(0, BACKEND)

from core.vision import vision  # noqa: E402

OUT = os.path.join(BACKEND, "data", "calib_debug", "loot_frames")
SERIAL = "127.0.0.1:21503"
DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 600


def screencap():
    p = subprocess.run(["adb", "-s", SERIAL, "exec-out", "screencap", "-p"],
                       capture_output=True, stdin=subprocess.DEVNULL, timeout=30)
    if p.returncode != 0 or not p.stdout:
        return None
    return cv2.imdecode(np.frombuffer(p.stdout, np.uint8), cv2.IMREAD_COLOR)


def is_scout(frame):
    """Next-button anchor (bottom-right) = scout screen."""
    t = vision.cache.get("buttons/attack/btn_next_enemy")
    if t is None:
        return False
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    res = cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED)
    return float(res.max()) >= 0.6


def ws_listener(stop_evt, log_path):
    import websockets

    async def run():
        async with websockets.connect("ws://127.0.0.1:8000/ws/run") as ws:
            with open(log_path, "a", encoding="utf-8") as f:
                while not stop_evt.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    except Exception:
                        return
                    ev = json.loads(raw)
                    if ev.get("type") == "log":
                        line = f"{time.strftime('%H:%M:%S')} [{ev.get('level')}] {ev.get('msg','')}"
                        f.write(line + "\n")
                        f.flush()

    async def guard():
        try:
            await asyncio.wait_for(run(), timeout=DURATION + 30)
        except Exception:
            pass

    asyncio.run(guard())


def main():
    os.makedirs(OUT, exist_ok=True)
    vision.load_assets(os.path.join(BACKEND, "assets"))
    stop_evt = threading.Event()
    log_path = os.path.join(OUT, "loot_log.txt")
    th = threading.Thread(target=ws_listener, args=(stop_evt, log_path), daemon=True)
    th.start()

    saved = 0
    t0 = time.time()
    print(f"passive capture for {DURATION}s -> {OUT}", flush=True)
    while time.time() - t0 < DURATION:
        frame = screencap()
        if frame is not None and is_scout(frame):
            saved += 1
            path = os.path.join(OUT, f"frame_{time.strftime('%H%M%S')}.png")
            cv2.imwrite(path, frame)
            print(f"  scout frame #{saved}: {os.path.basename(path)}", flush=True)
        time.sleep(2.0)
    stop_evt.set()
    print(f"done: {saved} scout frames", flush=True)


if __name__ == "__main__":
    main()
