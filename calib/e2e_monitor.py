"""E2E watch helper (agent scratch): connect /ws/run, start the endless farm
loop, and append every log/node/done event to calib/e2e_mv_watch.log.
Reconnects forever so the watcher outlives transient WS drops; the run itself
lives server-side (RunHub) and is unaffected.
Run from the repo root:  python calib/e2e_monitor.py
"""
import asyncio
import json
import os
import time

import websockets

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRAPH_PATH = os.path.join(ROOT, "backend", "data", "graphs",
                          "dragon_balloon_loop.json")
LOG_PATH = os.path.join(ROOT, "calib", "e2e_mv_watch.log")


def append(line):
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


async def session():
    with open(GRAPH_PATH, encoding="utf-8") as f:
        graph = json.load(f)
    async with websockets.connect("ws://127.0.0.1:8000/ws/run") as ws:
        snap = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
        append(f"{time.strftime('%H:%M:%S')} === attached: running={snap.get('running')} "
               f"status={snap.get('status')}")
        if not snap.get("running"):
            await ws.send(json.dumps({"cmd": "start", "graph": graph}))
            append(f"{time.strftime('%H:%M:%S')} === start cmd sent "
                   f"(graph={graph.get('name')})")
        while True:
            ev = json.loads(await ws.recv())
            t = ev.get("type")
            if t == "log":
                append(f"{time.strftime('%H:%M:%S')} [{ev.get('level', 'INFO')}] "
                       f"{ev.get('msg', '')}")
            elif t == "node":
                append(f"{time.strftime('%H:%M:%S')} <node {ev.get('id')} "
                       f"{ev.get('state')}>")
            elif t == "done":
                append(f"{time.strftime('%H:%M:%S')} === RUN DONE "
                       f"status={ev.get('status')} error={ev.get('error')}")
            elif t == "started":
                append(f"{time.strftime('%H:%M:%S')} === run started")
            # snapshot/vars/etc: ignore


def main():
    while True:
        try:
            asyncio.run(session())
        except Exception as e:
            append(f"{time.strftime('%H:%M:%S')} === ws closed ({e}) — retry in 5s")
            time.sleep(5)


if __name__ == "__main__":
    main()
