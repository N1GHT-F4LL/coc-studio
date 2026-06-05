"""WebSocket /ws/run — realtime graph debugger.

Protocol (client -> server JSON):
  {"cmd":"start", "graph": {...}}   start a run
  {"cmd":"stop"}                    cooperatively stop the active run

Server -> client JSON events (stream): the executor's run-events verbatim
(``node`` running/done/error, ``done`` status) plus ``log`` (forwarded logging)
and a final ``vars`` snapshot.

The run executes in a worker thread (blocking ADB/vision I/O); events cross back
to the event loop through a thread-safe asyncio.Queue. Reuses
``run_api.setup_and_run`` + the shared single-run ``controller`` so REST and WS
runs can't overlap.
"""
import asyncio
import logging
import threading

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from engine.graph import Graph
from api.run_api import controller, setup_and_run

logger = logging.getLogger(__name__)
router = APIRouter()

_SENTINEL = object()  # marks end-of-run on the queue


async def _listen_stop(ws: WebSocket, stop_event):
    """While a run is active, watch for {cmd:stop} / disconnect -> cooperative stop."""
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("cmd") == "stop":
                stop_event.set()
    except WebSocketDisconnect:
        stop_event.set()  # client vanished mid-run -> stop it
    except Exception:
        stop_event.set()


async def _run_streaming(ws: WebSocket, loop, graph_dict, stop_event):
    queue: asyncio.Queue = asyncio.Queue()

    def emit(ev):
        # Called from the worker thread — hop back onto the event loop safely.
        loop.call_soon_threadsafe(queue.put_nowait, ev)

    def worker():
        try:
            _status, run_vars = setup_and_run(
                graph_dict, emit, stop_event, stream_logs=True
            )
            emit({"type": "vars", "vars": run_vars})
        except Exception as e:  # defensive — setup_and_run already guards GraphError
            logger.exception("run worker crashed")
            emit({"type": "done", "status": "error", "error": str(e)})
        finally:
            controller.end()
            loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

    threading.Thread(target=worker, daemon=True, name="graph-run").start()
    await ws.send_json({"type": "started"})

    stopper = asyncio.create_task(_listen_stop(ws, stop_event))
    disconnected = False
    try:
        while True:
            ev = await queue.get()
            if ev is _SENTINEL:
                break
            if not disconnected:
                try:
                    await ws.send_json(ev)
                except Exception:
                    disconnected = True
                    stop_event.set()  # keep draining so the worker can finish
    finally:
        # Await the stopper's cancellation so it has released ws.receive_json()
        # before the outer loop resumes receiving — otherwise two coroutines
        # briefly recv() the same socket ("cannot call recv while another
        # coroutine is already waiting for the next message").
        stopper.cancel()
        try:
            await stopper
        except (asyncio.CancelledError, Exception):
            pass


@router.websocket("/ws/run")
async def run_ws(ws: WebSocket):
    await ws.accept()
    loop = asyncio.get_running_loop()
    logger.info("Run debugger client connected")
    try:
        while True:
            msg = await ws.receive_json()
            cmd = msg.get("cmd")
            if cmd == "stop":
                controller.stop()
                continue
            if cmd != "start":
                await ws.send_json({"type": "error", "error": f"unknown cmd: {cmd!r}"})
                continue

            graph_dict = msg.get("graph")
            errors = (
                Graph.from_dict(graph_dict).validate()
                if isinstance(graph_dict, dict)
                else ["missing 'graph'"]
            )
            if errors:
                await ws.send_json(
                    {"type": "done", "status": "invalid", "error": "; ".join(errors)}
                )
                continue

            stop_event = controller.begin()
            if stop_event is None:
                await ws.send_json(
                    {"type": "done", "status": "busy",
                     "error": "a run is already in progress"}
                )
                continue

            await _run_streaming(ws, loop, graph_dict, stop_event)
    except WebSocketDisconnect:
        logger.info("Run debugger client disconnected")
        controller.stop()
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Run debugger error: %s", e)
        try:
            await ws.close()
        except Exception:
            pass
