"""run_graph — the generic executor.

Generalizes the proven loop in ``screens/battle_screen.py:_slot_deploy``
(completed/pending/ready, cycle-guarded), extended with:

  - **data edges**: a node's ``data_in`` ports are resolved from upstream
    outputs, and a data edge also implies ordering (consumer runs after producer).
  - **branching / skip**: control (``after``) edges may carry a branch label.
    A node is *active* only if at least one incoming control edge is active
    (default edges are always active once their source ran; branch edges are
    active only when the source's chosen ``_branch`` matches) and all its data
    producers ran. Inactive nodes are *skipped*, and skips propagate downstream.
  - **per-node timeout** (cooperative): if ``graph.meta["node_timeout"]`` is set
    (seconds), a watchdog thread signals ``ctx.stop_event`` after the deadline so
    that cooperative blocks (those that poll ``ctx.stopped()`` or
    ``ctx.wait_if_paused()``) abort promptly. The node always runs in the
    calling thread — there is no concurrent access to ``outputs`` or
    ``ctx.vars``. Once the node returns, ``run_graph`` raises ``TimeoutError``
    so the normal fail-stop path aborts the run cleanly.

    Limitation: a block that makes a single long blocking syscall without ever
    checking ``ctx.stopped()`` will complete that syscall before observing the
    signal. Python cannot interrupt a running C extension from outside.

Error model stays **fail-stop** (REQUIREMENT §5/§16): a block raising follows its
``on_error`` node if present, else aborts the whole run.
"""
import threading

from .graph import Graph
from .registry import REGISTRY

# Sentinel keys a control block may return to drive branch edges.
BRANCH_KEY = "_branch"


class GraphError(Exception):
    """Raised before execution when the graph is structurally invalid."""


class NodeTimeoutError(TimeoutError):
    """Raised by the executor when a node exceeds its per-node timeout budget.

    ``user_was_stopped`` is True when ``ctx.stop_event`` was already set
    *before* the watchdog fired (i.e. the user pressed Stop independently of
    the timeout).  ``run_graph`` uses this to decide whether to run the
    ``on_error`` handler: a user stop is never cleared so the handler only
    runs for a timeout-only abort.
    """

    def __init__(self, msg: str, *, user_was_stopped: bool = False) -> None:
        super().__init__(msg)
        self.user_was_stopped = user_was_stopped


def resolve_inputs(node, outputs: dict) -> dict:
    """Merge literal params with values pulled from upstream data ports.

    ``data_in`` wins over ``params`` for the same name.
    """
    inputs = dict(node.params)
    for port, src in node.data_in.items():
        if not isinstance(src, dict):
            continue
        up = outputs.get(src.get("from"), {})
        out_port = src.get("port")
        if out_port in up:
            inputs[port] = up[out_port]
    return inputs


def _is_active(node, completed: set, skipped: set, outputs: dict) -> bool:
    """Decide whether a node should run, given all its deps are terminal.

    - every data producer must have completed (not been skipped),
    - and at least one incoming control edge must be active; a node with no
      control edges is controlled only by its data deps (or is a root).
    """
    for src in node.data_sources():
        if src in skipped:
            return False  # a data input never arrived

    control = node.control_edges()
    if not control:
        return True  # root, or driven purely by (satisfied) data edges
    for frm, branch in control:
        if frm in completed and (branch is None or outputs.get(frm, {}).get(BRANCH_KEY) == branch):
            return True
    return False  # all incoming control edges inactive -> skip


def _run_node(node, outputs: dict, ctx):
    inputs = resolve_inputs(node, outputs)
    ctx.wait_if_paused()
    if ctx.stopped():
        return
    ctx.emit({"type": "node", "id": node.id, "state": "running"})
    out = REGISTRY[node.type]().run(ctx, inputs) or {}
    # Do not emit a success "done" if the node was stopped mid-execution
    # (e.g. cooperative timeout abort).  The caller is responsible for
    # emitting the appropriate terminal event (error/stopped).
    if ctx.stopped():
        return
    outputs[node.id] = out
    ctx.emit({"type": "node", "id": node.id, "state": "done", "outputs": out})


def _run_node_with_timeout(node, outputs: dict, ctx, timeout: float):
    """Run *node* in the calling thread with cooperative cancellation.

    A daemon watchdog thread fires after *timeout* seconds and signals
    ``ctx.stop_event``.  Blocks that poll ``ctx.stopped()`` or
    ``ctx.wait_if_paused()`` will then abort at their next check.  Because the
    node runs in the *calling* thread there is no concurrent write to *outputs*
    or ``ctx.vars`` — the watchdog only ever sets the event, nothing else.

    After ``_run_node`` returns:
    - If the watchdog fired, we raise ``TimeoutError`` so the fail-stop handler
      in ``run_graph`` can emit the error event and abort the run cleanly.
    - If the node finished before the deadline, we cancel the watchdog (join with
      a short timeout so the thread exits promptly) and return normally.
    """
    if ctx.stop_event is None:
        # No stop mechanism — fall back to unlimited execution.
        _run_node(node, outputs, ctx)
        return

    watchdog_fired = threading.Event()
    cancel = threading.Event()
    # Captured inside _watchdog at the moment it fires — the only safe time to
    # distinguish a user-initiated stop from a timeout-only stop.  A pre-run
    # snapshot would miss users who press Stop *while* the node is executing.
    user_was_stopped_at_fire: list[bool] = [False]

    def _watchdog():
        if not cancel.wait(timeout):
            # Deadline elapsed and node is still running.
            # Record whether the user had already stopped at *this exact instant*
            # before we set the event ourselves.
            user_was_stopped_at_fire[0] = ctx.stop_event.is_set()
            watchdog_fired.set()
            ctx.stop_event.set()

    wt = threading.Thread(target=_watchdog, daemon=True, name=f"timeout-{node.id}")
    wt.start()
    try:
        _run_node(node, outputs, ctx)
    finally:
        cancel.set()      # tell watchdog the node has finished
        wt.join(timeout=0.5)  # reap the thread promptly (it exits once cancel is set)

    if watchdog_fired.is_set():
        raise NodeTimeoutError(
            f"Node {node.id!r} ({node.type}) exceeded its {timeout}s timeout. "
            "Increase graph.meta['node_timeout'] or check the block for a "
            "hanging operation.",
            user_was_stopped=user_was_stopped_at_fire[0],
        )


def run_graph(graph: Graph, ctx) -> str:
    """Execute ``graph`` to completion. Returns "ok" | "error" | "stopped".

    Also emits a final ``{"type":"done","status":...}`` event.

    ``graph.meta["node_timeout"]`` (float, seconds) optionally limits how long
    any single node may run before a TimeoutError is raised (fail-stop).
    """
    errors = graph.validate()
    if errors:
        raise GraphError("; ".join(errors))

    # Per-node timeout: read from graph metadata; None = unlimited.
    # Invalid values (non-numeric, zero, negative) are logged and ignored.
    raw_timeout = graph.meta.get("node_timeout")
    node_timeout: float | None = None
    if raw_timeout is not None:
        try:
            v = float(raw_timeout)
            if v > 0:
                node_timeout = v
            else:
                ctx.logger.warning(
                    "graph.meta['node_timeout'] must be a positive number; "
                    "ignoring value %r (no per-node timeout applied)", raw_timeout
                )
        except (TypeError, ValueError):
            ctx.logger.warning(
                "graph.meta['node_timeout'] is not numeric (%r); "
                "ignoring (no per-node timeout applied)", raw_timeout
            )

    by_id = {n.id: n for n in graph.nodes}
    outputs: dict = {}
    completed: set = set()
    skipped: set = set()
    pending = list(graph.nodes)  # preserve original order for stable dispatch

    while pending:
        if ctx.stopped():
            ctx.emit({"type": "done", "status": "stopped"})
            return "stopped"

        terminal = completed | skipped
        # Nodes whose every dependency (control + data) is already terminal.
        ready = [n for n in pending if n.dep_ids() <= terminal]
        if not ready:
            # Produce a detailed diagnostic: list which nodes are stuck and
            # which of their deps are still unresolved.
            stuck_lines = []
            for n in pending:
                unmet = sorted(n.dep_ids() - terminal)
                stuck_lines.append(f"  {n.id!r} ({n.type}) waiting on: {', '.join(unmet) or '(none)'}")
            detail = "\n".join(stuck_lines)
            error_msg = (
                "Graph is stuck — no nodes are ready to run. "
                "This is usually caused by a dependency cycle or a disconnected "
                f"control edge. Stuck nodes:\n{detail}"
            )
            ctx.logger.error(error_msg)
            ctx.emit({"type": "done", "status": "error", "error": error_msg})
            return "error"

        for node in ready:
            if ctx.stopped():
                ctx.emit({"type": "done", "status": "stopped"})
                return "stopped"

            if not _is_active(node, completed, skipped, outputs):
                skipped.add(node.id)
                pending.remove(node)
                ctx.emit({"type": "node", "id": node.id, "state": "skipped"})
                continue

            try:
                if node_timeout is not None:
                    _run_node_with_timeout(node, outputs, ctx, node_timeout)
                else:
                    _run_node(node, outputs, ctx)
            except NodeTimeoutError as e:
                # Timeout abort. The watchdog set ctx.stop_event for cooperative
                # cancellation. Run the on_error handler only when the user had
                # NOT already requested a stop — we must never clear a
                # user-initiated stop signal.  Always re-arm before returning.
                ctx.logger.error("Block %r (%s) timed out: %s", node.id, node.type, e)
                ctx.emit({"type": "node", "id": node.id, "state": "error",
                          "error": str(e)})
                handler_id = node.on_error
                if handler_id and handler_id in by_id:
                    if e.user_was_stopped:
                        # User pressed Stop before or during the timeout window;
                        # honour that signal — skip on_error handler entirely.
                        ctx.logger.info(
                            "on_error handler %r skipped: user Stop was already "
                            "requested before the timeout fired.", handler_id
                        )
                    else:
                        # Timeout-only stop: temporarily clear stop_event so the
                        # on_error handler can execute, then re-arm unconditionally.
                        if ctx.stop_event is not None:
                            ctx.stop_event.clear()
                        try:
                            _run_node(by_id[handler_id], outputs, ctx)
                        except Exception as he:
                            ctx.logger.exception(
                                "on_error handler %r failed after timeout", handler_id
                            )
                            ctx.emit({"type": "node", "id": handler_id,
                                      "state": "error", "error": str(he)})
                        finally:
                            if ctx.stop_event is not None:
                                ctx.stop_event.set()  # re-arm: run is still aborting
                ctx.emit({"type": "done", "status": "error", "error": str(e),
                          "node": node.id})
                return "error"
            except Exception as e:  # fail-stop (non-timeout)
                ctx.logger.exception("Block %r (%s) failed", node.id, node.type)
                ctx.emit({"type": "node", "id": node.id, "state": "error",
                          "error": str(e)})
                handler_id = node.on_error
                if handler_id and handler_id in by_id:
                    try:
                        _run_node(by_id[handler_id], outputs, ctx)
                    except Exception as he:
                        ctx.logger.exception("on_error handler %r failed", handler_id)
                        ctx.emit({"type": "node", "id": handler_id,
                                  "state": "error", "error": str(he)})
                ctx.emit({"type": "done", "status": "error", "error": str(e),
                          "node": node.id})
                return "error"

            completed.add(node.id)
            pending.remove(node)

    ctx.emit({"type": "done", "status": "ok"})
    return "ok"
