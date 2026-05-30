"""Graph execution + block catalog.

REST:
  GET  /api/blocks      -> all registered BlockSpec JSON (frontend palette, M3)
  POST /api/run         -> run a graph synchronously; returns collected events
  POST /api/run/stop    -> request cooperative stop of the active run

M2 is synchronous (worker thread + collected events). The realtime
``/ws/run`` streaming debugger lands in M4 — it will reuse run_graph + the same
RuntimeContext, swapping the event collector for a WS sink.
"""
import asyncio
import logging
import threading

from fastapi import APIRouter, Body, HTTPException

import blocks  # noqa: F401  -- side effect: populate engine.registry.REGISTRY
from core.vision import vision
from device_manager import manager, load_settings, read_number_with_confidence
from engine.context import RuntimeContext
from engine.graph import Graph
from engine.executor import run_graph, GraphError
from engine.registry import all_specs

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["run"])


class RunController:
    """Single-run guard + cooperative stop handle for the active graph run."""

    def __init__(self):
        self._lock = threading.Lock()
        self.stop_event = None  # set while a run is active

    def begin(self):
        with self._lock:
            if self.stop_event is not None:
                return None  # a run is already active
            self.stop_event = threading.Event()
            return self.stop_event

    def end(self):
        with self._lock:
            self.stop_event = None

    def stop(self):
        with self._lock:
            if self.stop_event is not None:
                self.stop_event.set()
                return True
            return False


controller = RunController()


@router.get("/blocks")
def get_blocks():
    return {"blocks": all_specs()}


def _execute(graph_dict, stop_event):
    """Blocking: build context, run graph, return (status, events, vars)."""
    # Ensure the device + assets are ready (idempotent) and OCR is warm.
    ok, reason = manager.connect()
    if not ok:
        return "error", [{"type": "done", "status": "error",
                          "error": f"device not connected: {reason}"}], {}
    manager.ensure_ocr()

    # Wire cooperative stop into the existing poll loops, like run_bot does.
    manager.ui_manager.stop_event = stop_event

    events = []
    ctx = RuntimeContext(
        device=manager.device,
        ui_manager=manager.ui_manager,
        vision=vision,
        ocr_read=read_number_with_confidence,
        settings=load_settings(),
        logger=logger,
        stop_event=stop_event,
        vars={},
        emit=events.append,
    )

    graph = Graph.from_dict(graph_dict)
    try:
        status = run_graph(graph, ctx)
    except GraphError as e:
        return "invalid", [{"type": "done", "status": "invalid", "error": str(e)}], ctx.vars
    finally:
        manager.ui_manager.stop_event = None
    return status, events, ctx.vars


@router.post("/run")
async def run(body: dict = Body(...)):
    graph_dict = body.get("graph")
    if not isinstance(graph_dict, dict):
        raise HTTPException(status_code=400, detail="body must be {\"graph\": {...}}")

    # Validate structure up front so a bad graph 400s instead of 500s.
    errors = Graph.from_dict(graph_dict).validate()
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})

    stop_event = controller.begin()
    if stop_event is None:
        raise HTTPException(status_code=409, detail="a run is already in progress")
    try:
        status, events, run_vars = await asyncio.to_thread(
            _execute, graph_dict, stop_event
        )
    finally:
        controller.end()

    return {"ok": status == "ok", "status": status, "events": events, "vars": run_vars}


@router.post("/run/stop")
def run_stop():
    return {"ok": controller.stop()}
