"""Live validation of the 2026-11-17 mapping fix on the REAL device.

Flow (mirrors the user's incident path, bounded):
  1. wait for the backend (start.ps1) + POST /api/device/connect
  2. standalone precheck: is the game on home? (close a leftover Settings
     panel via the calibrated X if needed)
  3. POST /api/multi_village/apply/2  -> the REAL switch path that dead-locked
     (open_switcher -> mapping -> SCID list -> switch -> verify)
  4. POST /api/multi_village/apply/1  -> round-trip back to Antoine
  5. final MV state
"""
import json
import os
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8000"
CFG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "backend", "data", "multi_village.json")


def http(method, path, body=None, timeout=300):
    req = urllib.request.Request(BASE + path, method=method)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
        return json.load(r)


def wait_backend(seconds=60):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            return http("GET", "/api/health", timeout=5)
        except Exception:
            time.sleep(2)
    raise SystemExit("backend did not come up")


def precheck_home():
    """Standalone device look: land the precheck frame, close a leftover
    Settings panel if one is open. Uses its own device_manager session."""
    sys.path.insert(0, r"C:\Users\antoinenguyen_09\Downloads\coc-studio\backend")
    import cv2
    from device_manager import manager
    from screens.home_screen import HomeScreen
    ok, reason = manager.connect()
    print("  connect:", ok, reason)
    if not ok:
        return False
    home = HomeScreen(manager.ui_manager)
    close_x = (1400, 72)
    try:
        cfg = json.load(open(CFG_PATH, encoding="utf-8"))
        close_x = tuple(cfg["coords"].get("settings_close_x", close_x))
    except Exception:
        pass
    for attempt in range(6):
        if home.is_current_screen():
            print("  precheck: game is on the home screen.")
            return True
        if attempt == 0:
            print(f"  precheck: not home — closing leftover panel via X {close_x}...")
            manager.device._run_adb(["shell", "input", "tap", str(close_x[0]), str(close_x[1])])
        elif attempt == 1:
            frame = manager.ui_manager.get_screen()
            if frame is not None:
                cv2.imwrite(r"C:\Users\antoinenguyen_09\Downloads\coc-studio\calib\mv_live_precheck.png", frame)
                print("  precheck: frame saved to calib/mv_live_precheck.png")
        time.sleep(5)
    print("  precheck: home NOT reached — see calib/mv_live_precheck.png")
    return False


def main():
    print("== backend ==")
    print("  health:", wait_backend())
    dev = http("POST", "/api/device/connect")
    print("  device/connect:", dev)

    print("== precheck (standalone device session) ==")
    if not precheck_home():
        print("ABORT — game not on home; inspect calib/mv_live_precheck.png")
        return

    cfg = json.load(open(CFG_PATH, encoding="utf-8"))
    villages = {v["idx"]: v for v in cfg["villages"]}

    for idx in (2, 1):
        v = villages[idx]
        print(f"== apply/{idx} ({v['name']}) — the REAL switch path ==")
        t0 = time.time()
        try:
            res = http("POST", f"/api/multi_village/apply/{idx}",
                       {"config": v.get("config")}, timeout=300)
            print(f"  OK in {time.time()-t0:.0f}s:", res)
        except Exception as e:
            body = getattr(e, "read", None)
            detail = ""
            if body is not None:
                try:
                    detail = e.read().decode("utf-8", "replace")[:300]
                except Exception:
                    pass
            print(f"  FAILED in {time.time()-t0:.0f}s: {e} {detail}")

    print("== final MV state ==")
    st = http("GET", "/api/multi_village")
    print("  current:", st["current_village_idx"], "| active:", st["active_village_idx"])
    for v in st["config"]["villages"]:
        print(f"  v{v['idx']} {v['name']!r}: confirmed={v['confirmed']}")


if __name__ == "__main__":
    main()
