"""WS run monitor (agent-run): start dragon_balloon_loop via /ws/run and log
every event to stdout so the background task output becomes the run's log.

Run:  ../.venv/Scripts/python.exe -X utf8 ../calib/treasure_run_monitor.py
"""
import asyncio
import json
import os
import sys

import websockets

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
sys.path.insert(0, BACKEND)


async def main():
    with open(os.path.join(BACKEND, "data", "graphs", "dragon_balloon_loop.json"),
              encoding="utf-8") as f:
        graph = json.load(f)
    uri = "ws://127.0.0.1:8000/ws/run"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"cmd": "start", "graph": graph}))
        print(">>> run start requested (dragon_balloon_loop)", flush=True)
        while True:
            ev = json.loads(await ws.recv())
            t = ev.get("type")
            if t == "snapshot":
                print(f">>> snapshot: running={ev.get('running')} status={ev.get('status')}",
                      flush=True)
            elif t == "log":
                print(f"[{ev.get('level', '?')}] {ev.get('msg', '')}", flush=True)
            elif t == "node":
                print(f">>> node {ev.get('id')} -> {ev.get('state')}", flush=True)
            elif t == "vars":
                pass
            elif t == "done":
                print(f">>> RUN DONE status={ev.get('status')} error={ev.get('error')}",
                      flush=True)
                return
            else:
                print(f">>> event {t}", flush=True)


asyncio.run(main())
