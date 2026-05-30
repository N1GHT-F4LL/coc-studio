"""Graph execution + block catalog.

REST:
  GET  /api/blocks      -> all registered BlockSpec JSON (frontend palette, M3)
  POST /api/run         -> run a graph synchronously; returns collected events
  POST /api/run/stop    -> request cooperative stop of the active run

The realtime ``/ws/run`` debugger (api/run_ws.py) reuses ``setup_and_run`` +
``controller`` from here, swapping the event collector for a WS sink.
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


class _EmitLogHandler(logging.Handler):
    """Forwards log records to the run's emit() as {"type":"log",...} events.

    Installed on the root logger for the duration of a run so the screens'/core's
    existing ``logging`` calls stream into the WS debugger with no code changes.
    """

    def __init__(self, emit):
        super().__init__(level=logging.INFO)
        self._emit = emit

    def emit(self, record):  # noqa: A003 - matches logging.Handler API
        try:
            self._emit({
                "type": "log",
                "level": record.levelname,
                "name": record.name,
                "msg": record.getMessage(),
            })
        except Exception:
            pass  # never let logging break the run


def setup_and_run(graph_dict, emit, stop_event, stream_logs=False):
    """Blocking: ensure device/OCR, build context, run graph. Returns (status, vars).

    ``emit`` receives every run-event (node/done + log when stream_logs). Shared by
    POST /api/run (emit=list.append) and WS /ws/run (emit=queue push).
    """
    ok, reason = manager.connect()
    if not ok:
        emit({"type": "done", "status": "error",
              "error": f"device not connected: {reason}"})
        return "error", {}
    manager.ensure_ocr()

    # Wire cooperative stop into the existing poll loops, like run_bot does.
    manager.ui_manager.stop_event = stop_event

    ctx = RuntimeContext(
        device=manager.device,
        ui_manager=manager.ui_manager,
        vision=vision,
        ocr_read=read_number_with_confidence,
        settings=load_settings(),
        logger=logger,
        stop_event=stop_event,
        vars={},
        emit=emit,
    )

    log_handler = None
    if stream_logs:
        log_handler = _EmitLogHandler(emit)
        logging.getLogger().addHandler(log_handler)

    graph = Graph.from_dict(graph_dict)
    try:
        status = run_graph(graph, ctx)
    except GraphError as e:
        emit({"type": "done", "status": "invalid", "error": str(e)})
        return "invalid", ctx.vars
    finally:
        manager.ui_manager.stop_event = None
        if log_handler is not None:
            logging.getLogger().removeHandler(log_handler)
    return status, ctx.vars


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
    events = []
    try:
        status, run_vars = await asyncio.to_thread(
            setup_and_run, graph_dict, events.append, stop_event
        )
    finally:
        controller.end()

    return {"ok": status == "ok", "status": status, "events": events, "vars": run_vars}


@router.post("/run/stop")
def run_stop():
    return {"ok": controller.stop()}
