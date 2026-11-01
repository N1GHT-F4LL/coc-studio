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
import os
import threading

from fastapi import APIRouter, Body, HTTPException

import app_paths

import blocks  # noqa: F401  -- side effect: populate engine.registry.REGISTRY
import popup_guard
from core.vision import vision
from device_manager import manager, load_settings, read_number_with_confidence, COC_PACKAGE
import scenario_store
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
        self.pause_event = None     # set while paused
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
                "paused": self.pause_event.is_set() if self.pause_event is not None else False,
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
            # The scaled-army cache is per Run session: Stop/Start always
            # starts with a fresh one (ensure_troops re-derives it if the
            # account's camp doesn't fit the plan).
            scenario_store.clear_army_cache()
            popup_guard.clear_recovery_history()
            self.stop_event = threading.Event()
            self.pause_event = threading.Event()
            self.running = True
            self.status = "running"
            self.graph = graph
            return self.stop_event

    def end(self):
        with self._lock:
            self.stop_event = None
            self.pause_event = None
            self.running = False

    def stop(self):
        requested = False
        with self._lock:
            if self.stop_event is not None:
                self.stop_event.set()
                # Stop invalidates the scaled-army cache (per user spec).
                scenario_store.clear_army_cache()
                popup_guard.clear_recovery_history()
                requested = True
        if requested:
            # Publish OUTSIDE the lock — publish() re-acquires it (non-reentrant)
            # and the press must be VISIBLE in the log stream, not just a light.
            # "name" is REQUIRED by the frontend LogLine contract — an unnamed
            # log line crashed RunConsole's render (white page on Stop).
            self.publish({"type": "log", "level": "WARNING", "name": "run",
                          "msg": "[STOP] Stop requested — aborting at the next checkpoint; "
                                 "army cache + session flags cleared, nothing carries over."})
        return requested

    def pause(self):
        with self._lock:
            if self.pause_event is None or self.stop_event is None:
                return False
            self.pause_event.set()
            self.status = "paused"
        self.publish({"type": "paused"})
        return True

    def resume(self):
        with self._lock:
            if self.pause_event is None or self.stop_event is None:
                return False
            self.pause_event.clear()
            self.status = "running"
        self.publish({"type": "resumed"})
        return True

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
            elif t == "paused":
                self.status = "paused"
            elif t == "resumed":
                self.status = "running"
            subs = list(self._subscribers)
            loop = self.loop
        if loop is not None:
            for q in subs:
                loop.call_soon_threadsafe(q.put_nowait, ev)


# Exported as ``controller`` for backward-compat with existing imports.
controller = RunHub()

# Learned button coordinates persist here between runs (per screen resolution).
COORDS_PATH = os.path.join(app_paths.DATA_DIR, "coord_cache.json")


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


def _popup_watchdog(ui, device, stop_event, wd_stop, log):
    """Run-long guard for the four SYSTEM popups (Another device / Connection
    lost / Client error! / rate-the-game). They have no live game session
    behind them — no in-game button can clear them — so the check is strict
    template matching and the recovery is a full RELAUNCH (Simplicity bot
    mechanism, popup_guard).

    Recovery budget = RATE, not a run-total: genuine connection drops over a
    long loop self-heal up to RECOVERY_MAX per RECOVERY_WINDOW; beyond that
    the connection is dying persistently — the run is STOPPED CLEANLY
    (cooperative) instead of flailing through failed cycles (2026-11-01
    incident: 3-cap burned in 3 iterations, then ERROR spam with no recovery)."""
    ticks = 0
    while not wd_stop.wait(5.0) and not stop_event.is_set():
        try:
            ticks += 1
            if ticks % 12 == 0:
                # heartbeat: proves the scanner is alive so a silent incident
                # is distinguishable from a dead watchdog
                log.info("[watchdog] scan alive (%d ticks) — no system popup on screen.",
                         ticks)
            if popup_guard.recent_recovery():
                continue   # a guard thread is mid-recovery — stay out of the way
            if not popup_guard.connection_popup_visible():
                # Non-fatal in-game popup: the Star Bonus screen only needs
                # its green Okay tapped (no relaunch, no abort).
                if popup_guard.dismiss_star_bonus(log):
                    continue
                continue
            if popup_guard.recovery_rate_exceeded():
                log.error("[watchdog] %d+ relaunches in the last %ds — the connection "
                          "keeps dropping. Stopping the run cleanly: check the "
                          "network/device, then press Run again.",
                          popup_guard.RECOVERY_MAX, int(popup_guard.RECOVERY_WINDOW))
                controller.stop()   # cooperative: publishes [STOP], clears caches
                continue
            log.warning("Connection lost detected—recovering…")
            popup_guard.boot_recovery()
        except Exception:
            pass  # the watchdog must never break the run


def setup_and_run(graph_dict, emit, stop_event, pause_event=None, stream_logs=False):
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

    # Seed learned button coords once per process so the first lookups this
    # session are ROI confirms, not full-screen searches.
    if not vision._loc_cache:
        vision.load_coords(COORDS_PATH)

    # Wire cooperative stop into the existing poll loops, like run_bot does.
    manager.ui_manager.stop_event = stop_event
    manager.ui_manager.pause_event = pause_event

    ctx = RuntimeContext(
        device=manager.device,
        ui_manager=manager.ui_manager,
        vision=vision,
        ocr_read=read_number_with_confidence,
        settings=load_settings(),
        logger=logger,
        stop_event=stop_event,
        pause_event=pause_event,
        vars={},
        emit=emit,
    )

    log_handler = None
    if stream_logs:
        log_handler = _EmitLogHandler(emit)
        logging.getLogger().addHandler(log_handler)

    wd_stop = threading.Event()
    watchdog = threading.Thread(
        target=_popup_watchdog,
        args=(manager.ui_manager, manager.device, stop_event, wd_stop, logger),
        daemon=True, name="popup-watchdog",
    )
    watchdog.start()

    graph = Graph.from_dict(graph_dict)
    try:
        status = run_graph(graph, ctx)
        if status == "stopped":
            logger.warning("[STOP] run stopped by user — caches are cleared "
                           "(army + session flags), nothing carries over to the next Run.")
    except GraphError as e:
        emit({"type": "done", "status": "invalid", "error": str(e)})
        return "invalid", ctx.vars
    finally:
        wd_stop.set()
        manager.ui_manager.stop_event = None
        manager.ui_manager.pause_event = None
        if log_handler is not None:
            logging.getLogger().removeHandler(log_handler)
        try:
            vision.save_coords(COORDS_PATH)   # persist anything learned this run
        except Exception:
            pass
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
            setup_and_run, graph_dict, emit, stop_event, controller.pause_event
        )
        emit({"type": "vars", "vars": run_vars})
    finally:
        controller.end()

    return {"ok": status == "ok", "status": status, "events": events, "vars": run_vars}


@router.post("/run/stop")
def run_stop():
    return {"ok": controller.stop()}

@router.post("/run/pause")
def run_pause():
    return {"ok": controller.pause()}

@router.post("/run/resume")
def run_resume():
    return {"ok": controller.resume()}
