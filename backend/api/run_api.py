"""Graph execution + block catalog.

REST:
  GET  /api/blocks      -> all registered BlockSpec JSON (frontend palette, M3)
  POST /api/run         -> run a graph synchronously; returns collected events
  POST /api/run/stop    -> request cooperative stop of the active run

The realtime ``/ws/run`` debugger (api/run_ws.py) reuses ``setup_and_run`` +
``controller`` from here, swapping the event collector for a WS sink.
"""
import asyncio
import collections
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


_LOG_BUFFER = 500  # how many recent log lines to retain for reattach replay


class RunHub:
    """Single-run guard + cooperative stop handle + a server-side buffer of the
    active run's state, fanned out to any number of (re)connecting WS clients.

    The run lives independently of any WS connection: a client that disconnects
    just unsubscribes; the worker thread keeps publishing into the buffer, and a
    client that (re)connects gets a ``snapshot()`` to rebuild its view. State is
    in-memory only — it survives a web reload, not a backend restart.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.stop_event = None      # set while a run is active
        self.loop = None            # asyncio loop, for threadsafe fan-out
        self._subscribers = set()   # asyncio.Queue per connected client
        self._reset_state()

    def _reset_state(self):
        self.running = False
        self.status = ""           # "", running, ok, error, stopped, invalid
        self.error = None
        self.graph = None          # the running GraphDoc (for reattach auto-load)
        self.node_states = {}      # node id -> running/done/error/skipped
        self.vars = {}
        self.logs = collections.deque(maxlen=_LOG_BUFFER)

    # --- loop / subscribers -------------------------------------------------
    def set_loop(self, loop):
        self.loop = loop

    def subscribe(self):
        q = asyncio.Queue()
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            self._subscribers.discard(q)

    def snapshot(self):
        with self._lock:
            return {
                "type": "snapshot",
                "running": self.running,
                "status": self.status,
                "error": self.error,
                "graph": self.graph,
                "nodes": dict(self.node_states),
                "vars": self.vars,
                "logs": list(self.logs),
            }

    # --- run lifecycle ------------------------------------------------------
    def begin(self, graph=None):
        with self._lock:
            if self.stop_event is not None:
                return None  # a run is already active
            self._reset_state()
            self.stop_event = threading.Event()
            self.running = True
            self.status = "running"
            self.graph = graph
            return self.stop_event

    def end(self):
        with self._lock:
            self.stop_event = None
            self.running = False

    def stop(self):
        with self._lock:
            if self.stop_event is not None:
                self.stop_event.set()
                return True
            return False

    # --- event ingest + fan-out (called from the run worker thread) ---------
    def publish(self, ev):
        """Fold an event into the buffer, then fan it out to every subscriber."""
        with self._lock:
            t = ev.get("type")
            if t == "node":
                self.node_states[ev.get("id")] = ev.get("state")
            elif t == "log":
                self.logs.append(ev)
            elif t == "vars":
                self.vars = ev.get("vars", {}) or {}
            elif t == "done":
                self.status = ev.get("status", self.status)
                self.error = ev.get("error")
                self.running = False
            subs = list(self._subscribers)
            loop = self.loop
        if loop is not None:
            for q in subs:
                loop.call_soon_threadsafe(q.put_nowait, ev)


# Exported as ``controller`` for backward-compat with existing imports.
controller = RunHub()


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

    controller.set_loop(asyncio.get_running_loop())
    stop_event = controller.begin(graph_dict)
    if stop_event is None:
        raise HTTPException(status_code=409, detail="a run is already in progress")
    events = []

    def emit(ev):
        events.append(ev)
        controller.publish(ev)  # also fan out to any attached WS client

    try:
        status, run_vars = await asyncio.to_thread(
            setup_and_run, graph_dict, emit, stop_event
        )
        emit({"type": "vars", "vars": run_vars})
    finally:
        controller.end()

    return {"ok": status == "ok", "status": status, "events": events, "vars": run_vars}


@router.post("/run/stop")
def run_stop():
    return {"ok": controller.stop()}
