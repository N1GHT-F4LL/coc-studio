"""WebSocket /ws/run — realtime graph debugger + reattach.

Protocol (client -> server JSON):
  {"cmd":"start", "graph": {...}}   start a run (if none is active)
  {"cmd":"stop"}                    cooperatively stop the active run
  {"cmd":"pause"}                   pause between poll/action checkpoints
  {"cmd":"resume"}                  resume a paused run

Server -> client JSON events:
  {"type":"snapshot", ...}          sent immediately on connect — the current run
                                    state (running/status/graph/nodes/vars/logs)
                                    so a (re)connecting client rebuilds its view.
  then the live event stream verbatim (``started``/``node``/``log``/``vars``/``done``).

The run lives in the shared ``RunHub`` (api/run_api.controller), independent of
any WS connection: the worker thread publishes into the hub, which buffers state
and fans events out to every connected client. **Disconnecting does NOT stop the
run** — the client just unsubscribes; reopening the web reattaches via snapshot.
Only an explicit {"cmd":"stop"} (or backend exit) ends a run.
"""
import logging
import threading

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from engine.graph import Graph
from api.run_api import controller, setup_and_run

logger = logging.getLogger(__name__)
router = APIRouter()


async def _start_run(ws: WebSocket, graph_dict) -> None:
    """Validate + begin a run, then drive it on a worker thread (publishing into
    the hub). Errors (bad graph / already running) go only to the requester."""
    errors = (
        Graph.from_dict(graph_dict).validate()
        if isinstance(graph_dict, dict)
        else ["missing 'graph'"]
    )
    if errors:
        await ws.send_json({"type": "done", "status": "invalid", "error": "; ".join(errors)})
        return

    stop_event = controller.begin(graph_dict)
    if stop_event is None:
        await ws.send_json(
            {"type": "done", "status": "busy", "error": "a run is already in progress"}
        )
        return

    controller.publish({"type": "started"})

    def worker():
        try:
            _status, run_vars = setup_and_run(
                graph_dict, controller.publish, stop_event, controller.pause_event, stream_logs=True
            )
            controller.publish({"type": "vars", "vars": run_vars})
        except Exception as e:  # defensive — setup_and_run already guards GraphError
            logger.exception("run worker crashed")
            controller.publish({"type": "done", "status": "error", "error": str(e)})
        finally:
            controller.end()

    threading.Thread(target=worker, daemon=True, name="graph-run").start()


@router.websocket("/ws/run")
async def run_ws(ws: WebSocket) -> None:
    import asyncio

    await ws.accept()
    loop = asyncio.get_running_loop()
    controller.set_loop(loop)
    q = controller.subscribe()
    logger.info("Run client connected")

    # Rebuild the client's view from the current run state before live events.
    await ws.send_json(controller.snapshot())

    async def sender():
        """Forward fanned-out events from the hub to this client."""
        try:
            while True:
                ev = await q.get()
                await ws.send_json(ev)
        except Exception:
            pass  # socket closing — receiver loop handles teardown

    send_task = asyncio.create_task(sender())
    try:
        while True:
            msg = await ws.receive_json()
            cmd = msg.get("cmd")
            if cmd == "stop":
                controller.stop()
            elif cmd == "pause":
                controller.pause()
            elif cmd == "resume":
                controller.resume()
            elif cmd == "start":
                await _start_run(ws, msg.get("graph"))
            else:
                await ws.send_json({"type": "error", "error": f"unknown cmd: {cmd!r}"})
    except WebSocketDisconnect:
        # Client vanished — DO NOT stop the run. It keeps going server-side; a
        # future client reattaches via snapshot.
        logger.info("Run client disconnected (run continues)")
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Run ws error: %s", e)
    finally:
        send_task.cancel()
        try:
            await send_task
        except (asyncio.CancelledError, Exception):
            # cancel() raises CancelledError inside the awaiting q.get(); it is a
            # BaseException (not Exception), so catch it explicitly or it escapes
            # to uvicorn as "Exception in ASGI application".
            pass
        controller.unsubscribe(q)
