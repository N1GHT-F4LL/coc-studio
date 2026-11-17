"""Reproduce the user's 2026-11-16 flow over the live backend:

  Multi-Village tab: Enable rotation + interval 8 min + tick all 9 villages
  (ALREADY in data/multi_village.json — the user's own state).
  Bot Builder: load dragon_balloon_loop -> Run.

Expected AFTER the fix: mv_rotation does NOT refuse (configs exist; confirmed
is advisory) -> node mvin completes -> the run proceeds into ensure_home, and
the loop aborts CLEANLY on the first inner failure (fail-stop) instead of
spamming "[MV] ... refuses" forever.

Read-only for the device except whatever ensure_home legitimately does in the
few seconds before the script sends cmd:stop.
"""
import asyncio
import json
import sys
import urllib.request

sys.path.insert(0, r"C:\Users\antoinenguyen_09\Downloads\coc-studio\backend")

import websockets

BASE = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000/ws/run"
GRAPH = "dragon_balloon_loop"


def http_get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return json.load(r)


async def main():
    mv = http_get("/api/multi_village")
    cfg = mv["config"]
    print("== MV state ==")
    print("  enabled:", cfg["enabled"], "| interval_mins:", cfg["interval_mins"],
          "| active:", mv["active_village_idx"], "| current:", mv["current_village_idx"])
    for v in cfg["villages"]:
        print(f"  v{v['idx']} {v['name']!r}: enabled={v['enabled']} "
              f"confirmed={v['confirmed']} config={'YES' if v.get('config') else 'null'}")
    dev = http_get("/api/device/status")
    print("== device ==", dev)

    with open(rf"C:\Users\antoinenguyen_09\Downloads\coc-studio\backend\data\graphs\{GRAPH}.json",
              encoding="utf-8") as f:
        graph = json.load(f)

    print("== starting run via WS ==")
    async with websockets.connect(WS, max_size=10 * 1024 * 1024) as ws:
        snap = json.loads(await ws.recv())
        print("  snapshot:", snap.get("status"), "running:", snap.get("running"))
        await ws.send(json.dumps({"cmd": "start", "graph": graph}))
        seen_error = False
        try:
            for _ in range(400):
                ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=25))
                t = ev.get("type")
                if t == "log":
                    print("  [log]", ev.get("level"), ev.get("msg"))
                    if ev.get("level") == "ERROR":
                        seen_error = True
                elif t == "node":
                    print(f"  [node] {ev.get('id')} -> {ev.get('state')}")
                elif t == "done":
                    print("  [done]", ev.get("status"), ev.get("error", ""))
                    break
                if seen_error and t == "node":
                    # first inner failure observed — give the executor a moment,
                    # then stop; fail-stop must end the loop by itself
                    pass
        except asyncio.TimeoutError:
            print("  (25s without events — stopping)")
        await ws.send(json.dumps({"cmd": "stop"}))
        # drain briefly for the stopped/done event
        try:
            for _ in range(20):
                ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=6))
                if ev.get("type") in ("log", "node", "done"):
                    print("  [post-stop]", ev.get("type"),
                          ev.get("msg") or f"{ev.get('id')}->{ev.get('state')}" or ev.get("status"))
                if ev.get("type") == "done":
                    break
        except asyncio.TimeoutError:
            pass
    print("== RESULT ==")
    print("  refused-in-loop observed:", seen_error)


asyncio.run(main())
