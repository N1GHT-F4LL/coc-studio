"""Engine smoke test — no device needed.

Verifies the generic executor: topo-order, run-events, cycle guard, and the
fail-stop error model (a raising block aborts the run; later nodes don't run).

Run from backend/:  ..\.venv\Scripts\python.exe tests\test_engine.py
"""
import logging
import os
import sys
import threading

# Make backend/ importable (mirrors main.py), regardless of CWD.
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import blocks  # noqa: F401  -- register built-in blocks
from engine.registry import REGISTRY, register, BlockSpec, all_specs
from engine.graph import Graph
from engine.executor import run_graph, GraphError
from engine.context import RuntimeContext

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("test_engine")

_passed = 0
_failed = 0


def check(cond, msg):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {msg}")
    else:
        _failed += 1
        print(f"  FAIL  {msg}")


# --- test-only blocks -------------------------------------------------------
@register("_test_marker")
class _Marker(BlockSpec):
    """Appends its node id to ctx.vars['order'] so we can assert topo-order."""
    label = "marker"; category = "Test"; inputs = []; outputs = []

    def run(self, ctx, inputs):
        ctx.vars.setdefault("order", []).append(inputs.get("_id"))
        return {"ok": True}


@register("_test_boom")
class _Boom(BlockSpec):
    label = "boom"; category = "Test"; inputs = []; outputs = []

    def run(self, ctx, inputs):
        raise RuntimeError("boom")


@register("_test_emit")
class _Emit(BlockSpec):
    """Outputs {"val": params['val']} so a downstream block can read it via a data edge."""
    label = "emit"; category = "Test"; inputs = []; outputs = []

    def run(self, ctx, inputs):
        return {"val": inputs.get("val")}


@register("_test_record")
class _Record(BlockSpec):
    """Records its resolved 'x' input into ctx.vars['rec'] (proves data-edge wiring)."""
    label = "record"; category = "Test"; inputs = []; outputs = []

    def run(self, ctx, inputs):
        ctx.vars.setdefault("rec", []).append(inputs.get("x"))
        ctx.vars.setdefault("order", []).append(inputs.get("_id"))
        return {}


def make_ctx(events):
    return RuntimeContext(
        device=None, ui_manager=None, vision=None, ocr_read=None,
        settings={}, logger=log, stop_event=threading.Event(),
        vars={}, emit=events.append,
    )


def _node(nid, after=None, on_error=None, params=None, type="delay"):
    return {"id": nid, "type": type, "after": after or [],
            "on_error": on_error, "params": params or {}}


def test_registry_specs():
    print("\n[registry] /api/blocks specs")
    specs = {s["type"] for s in all_specs()}
    for t in ("collect_resources", "find_match", "deploy", "return_home",
              "wait_template", "tap", "read_number", "delay"):
        check(t in specs, f"block registered: {t}")


def test_topo_order():
    print("\n[executor] topo-order over control edges")
    # diamond: a -> b, a -> c, (b,c) -> d
    g = Graph.from_dict({"name": "diamond", "nodes": [
        _node("a", type="_test_marker", params={"_id": "a"}),
        _node("b", after=["a"], type="_test_marker", params={"_id": "b"}),
        _node("c", after=["a"], type="_test_marker", params={"_id": "c"}),
        _node("d", after=["b", "c"], type="_test_marker", params={"_id": "d"}),
    ]})
    events = []
    ctx = make_ctx(events)
    status = run_graph(g, ctx)
    order = ctx.vars["order"]
    check(status == "ok", f"status ok (got {status})")
    check(order[0] == "a", "a runs first")
    check(order[-1] == "d", "d runs last")
    check(order.index("b") > order.index("a") and order.index("c") > order.index("a"),
          "b,c after a")
    done = [e for e in events if e.get("type") == "done"]
    check(done and done[-1]["status"] == "ok", "final done event = ok")


def test_cycle_guard():
    print("\n[executor] cycle is rejected")
    g = Graph.from_dict({"name": "cyc", "nodes": [
        _node("a", after=["b"], type="_test_marker"),
        _node("b", after=["a"], type="_test_marker"),
    ]})
    try:
        run_graph(g, make_ctx([]))
        check(False, "GraphError raised for cycle")
    except GraphError as e:
        check("cycle" in str(e).lower(), f"GraphError mentions cycle: {e}")


def test_unknown_type():
    print("\n[graph] unknown block type is rejected")
    g = Graph.from_dict({"name": "x", "nodes": [_node("a", type="does_not_exist")]})
    errs = g.validate()
    check(any("unknown block type" in e for e in errs), "unknown type flagged")


def test_fail_stop():
    print("\n[executor] fail-stop: raising block aborts, later nodes don't run")
    g = Graph.from_dict({"name": "fs", "nodes": [
        _node("a", type="_test_marker", params={"_id": "a"}),
        _node("boom", after=["a"], type="_test_boom"),
        _node("after_boom", after=["boom"], type="_test_marker", params={"_id": "after_boom"}),
    ]})
    events = []
    ctx = make_ctx(events)
    status = run_graph(g, ctx)
    check(status == "error", f"status error (got {status})")
    check("after_boom" not in ctx.vars.get("order", []), "node after failure did NOT run")
    err_events = [e for e in events if e.get("state") == "error"]
    check(any(e["id"] == "boom" for e in err_events), "error event emitted for boom")


def test_on_error_then_abort():
    print("\n[executor] on_error handler runs, then run still aborts")
    g = Graph.from_dict({"name": "oe", "nodes": [
        _node("boom", type="_test_boom", on_error="handler"),
        _node("handler", type="_test_marker", params={"_id": "handler"}),
        _node("never", after=["boom"], type="_test_marker", params={"_id": "never"}),
    ]})
    events = []
    ctx = make_ctx(events)
    status = run_graph(g, ctx)
    check(status == "error", f"status error (got {status})")
    check("handler" in ctx.vars.get("order", []), "on_error handler ran")
    check("never" not in ctx.vars.get("order", []), "downstream still aborted")


def test_stop_event():
    print("\n[executor] cooperative stop")
    g = Graph.from_dict({"name": "stop", "nodes": [
        _node("a", type="_test_marker", params={"_id": "a"}),
        _node("b", after=["a"], type="_test_marker", params={"_id": "b"}),
    ]})
    events = []
    ctx = make_ctx(events)
    ctx.stop_event.set()  # already stopped before first node
    status = run_graph(g, ctx)
    check(status == "stopped", f"status stopped (got {status})")
    check(ctx.vars.get("order", []) == [], "no nodes ran when pre-stopped")


def test_data_edge():
    print("\n[executor] data edge resolves value + orders consumer after producer")
    g = Graph.from_dict({"name": "data", "nodes": [
        {"id": "p", "type": "_test_emit", "params": {"val": 42}},
        {"id": "c", "type": "_test_record", "params": {"_id": "c"},
         "data_in": {"x": {"from": "p", "port": "val"}}},
    ]})
    ctx = make_ctx([])
    status = run_graph(g, ctx)
    check(status == "ok", f"status ok (got {status})")
    check(ctx.vars.get("rec") == [42], f"consumer read producer output (rec={ctx.vars.get('rec')})")


def test_data_edge_orders():
    print("\n[executor] data edge implies ordering even with no control edge")
    # 'c' is declared BEFORE 'p' but depends on p's data -> must still run after p.
    g = Graph.from_dict({"name": "ord", "nodes": [
        {"id": "c", "type": "_test_record", "params": {"_id": "c"},
         "data_in": {"x": {"from": "p", "port": "val"}}},
        {"id": "p", "type": "_test_emit", "params": {"val": 7}},
    ]})
    ctx = make_ctx([])
    run_graph(g, ctx)
    check(ctx.vars.get("rec") == [7], "consumer ran after producer despite declaration order")


def test_if_branch():
    print("\n[executor] if routes then/else; untaken branch is skipped")
    for cond, taken, untaken in (("then", "then", "else"), ("else", "else", "then")):
        g = Graph.from_dict({"name": f"if-{cond}", "nodes": [
            {"id": "ifn", "type": "if", "params": {"cond": cond == "then"}},
            {"id": "thenN", "type": "_test_marker", "params": {"_id": "thenN"},
             "after": [{"from": "ifn", "branch": "then"}]},
            {"id": "elseN", "type": "_test_marker", "params": {"_id": "elseN"},
             "after": [{"from": "ifn", "branch": "else"}]},
        ]})
        events = []
        ctx = make_ctx(events)
        status = run_graph(g, ctx)
        order = ctx.vars.get("order", [])
        ran = f"{taken}N"
        skip = f"{untaken}N"
        check(status == "ok", f"[{cond}] status ok")
        check(ran in order, f"[{cond}] {ran} ran")
        check(skip not in order, f"[{cond}] {skip} did NOT run")
        skipped = [e for e in events if e.get("state") == "skipped"]
        check(any(e["id"] == skip for e in skipped), f"[{cond}] {skip} emitted skipped")


def test_skip_propagation():
    print("\n[executor] skip propagates to downstream of the untaken branch")
    g = Graph.from_dict({"name": "skipprop", "nodes": [
        {"id": "ifn", "type": "if", "params": {"cond": False}},  # takes 'else'
        {"id": "a", "type": "_test_marker", "params": {"_id": "a"},
         "after": [{"from": "ifn", "branch": "then"}]},   # skipped
        {"id": "b", "type": "_test_marker", "params": {"_id": "b"}, "after": ["a"]},  # downstream of skipped
    ]})
    events = []
    ctx = make_ctx(events)
    status = run_graph(g, ctx)
    check(status == "ok", f"status ok (got {status})")
    check("a" not in ctx.vars.get("order", []), "branch node a skipped")
    check("b" not in ctx.vars.get("order", []), "downstream b skipped (propagated)")
    skipped = {e["id"] for e in events if e.get("state") == "skipped"}
    check({"a", "b"} <= skipped, "both a and b emitted skipped")


import time as _time

# -- timeout test blocks (cooperative) ---------------------------------------
@register("_test_slow_cooperative")
class _SlowCooperative(BlockSpec):
    """Sleeps up to 10 s but polls ctx.stopped() every 0.05 s (cooperative)."""
    label = "slow_coop"; category = "Test"; inputs = []; outputs = []

    def run(self, ctx, inputs):
        deadline = _time.time() + 10
        while _time.time() < deadline:
            if ctx.stopped():
                return {}
            _time.sleep(0.05)
        return {}


@register("_test_side_effect")
class _SideEffect(BlockSpec):
    """Appends 'ran' to ctx.vars['effects'] so we can detect post-timeout execution."""
    label = "side_effect"; category = "Test"; inputs = []; outputs = []

    def run(self, ctx, inputs):
        ctx.vars.setdefault("effects", []).append("ran")
        return {}


def test_node_timeout_fires():
    """Cooperative timeout: slow node is signalled to stop, run aborts with error."""
    print("\n[executor] node_timeout: cooperative block aborts on stop signal")
    g = Graph.from_dict({"name": "t1", "meta": {"node_timeout": 0.3}, "nodes": [
        _node("slow", type="_test_slow_cooperative"),
    ]})
    events = []
    ctx = make_ctx(events)
    t0 = _time.time()
    status = run_graph(g, ctx)
    elapsed = _time.time() - t0
    check(status == "error", f"status=error (got {status!r})")
    check(elapsed < 5.0, f"run completed in <5 s (elapsed={elapsed:.2f}s)")
    err_events = [e for e in events if e.get("state") == "error"]
    check(any(e.get("id") == "slow" for e in err_events), "error event emitted for timed-out node")
    done = [e for e in events if e.get("type") == "done"]
    check(done and done[-1]["status"] == "error", "final done event status=error")


def test_node_timeout_no_side_effects_after():
    """A node after the timed-out one must not run (run is aborted cleanly)."""
    print("\n[executor] node_timeout: downstream node does not run after timeout abort")
    g = Graph.from_dict({"name": "t2", "meta": {"node_timeout": 0.3}, "nodes": [
        _node("slow", type="_test_slow_cooperative"),
        _node("after", after=["slow"], type="_test_side_effect"),
    ]})
    events = []
    ctx = make_ctx(events)
    run_graph(g, ctx)
    check("ran" not in ctx.vars.get("effects", []),
          "downstream node did NOT run after timeout (no late side-effects)")


def test_node_timeout_no_late_emit():
    """Timed-out node must not emit spurious done/running events after terminal done."""
    print("\n[executor] node_timeout: no events emitted after terminal done event")
    g = Graph.from_dict({"name": "t3", "meta": {"node_timeout": 0.3}, "nodes": [
        _node("slow", type="_test_slow_cooperative"),
    ]})
    events = []
    ctx = make_ctx(events)
    run_graph(g, ctx)
    done_indices = [i for i, e in enumerate(events) if e.get("type") == "done"]
    check(bool(done_indices), "done event present")
    if done_indices:
        last_done = done_indices[-1]
        post = events[last_done + 1:]
        check(post == [], f"no events after terminal done (got {post!r})")


def test_node_timeout_fast_node_unaffected():
    """A node that finishes before the deadline must not be aborted."""
    print("\n[executor] node_timeout: fast node completes normally within timeout")
    g = Graph.from_dict({"name": "t4", "meta": {"node_timeout": 5.0}, "nodes": [
        _node("a", type="_test_marker", params={"_id": "a"}),
        _node("b", after=["a"], type="_test_side_effect"),
    ]})
    events = []
    ctx = make_ctx(events)
    status = run_graph(g, ctx)
    check(status == "ok", f"fast nodes finish ok (got {status!r})")
    check("ran" in ctx.vars.get("effects", []), "both nodes ran (timeout did not interrupt)")


def test_node_timeout_on_error_runs():
    """on_error handler must execute even when the node timed out.

    When the watchdog fires it sets ctx.stop_event so cooperative blocks abort.
    run_graph temporarily clears that event before running the on_error handler
    and re-sets it after, so the handler can complete normally.
    """
    print("\n[executor] node_timeout: on_error handler runs after timeout abort")
    g = Graph.from_dict({"name": "t5", "meta": {"node_timeout": 0.3}, "nodes": [
        _node("slow", type="_test_slow_cooperative", on_error="handler"),
        _node("handler", type="_test_side_effect"),   # records 'ran' in ctx.vars
    ]})
    events = []
    ctx = make_ctx(events)
    status = run_graph(g, ctx)
    check(status == "error", f"status=error (got {status!r})")
    check("ran" in ctx.vars.get("effects", []),
          "on_error handler ran despite timeout (stop_event cleared for handler)")
    handler_events = [e for e in events if e.get("id") == "handler" and e.get("state") == "done"]
    check(bool(handler_events), "on_error handler emitted a 'done' event")


def test_node_timeout_no_done_event_on_aborted_node():
    """A timed-out cooperative node must NOT emit a success state:done event.

    Without the post-run stopped() check in _run_node, a cooperative block that
    returns early would still emit done before the error event, producing
    contradictory lifecycle events.
    """
    print("\n[executor] node_timeout: timed-out node must not emit state:done success event")
    g = Graph.from_dict({"name": "t_nodone", "meta": {"node_timeout": 0.3}, "nodes": [
        _node("slow", type="_test_slow_cooperative"),
    ]})
    events = []
    ctx = make_ctx(events)
    run_graph(g, ctx)
    node_events = [e for e in events if e.get("id") == "slow"]
    done_success = [e for e in node_events if e.get("state") == "done"]
    error_ev = [e for e in node_events if e.get("state") == "error"]
    check(bool(error_ev), "timed-out node emitted state:error")
    check(not done_success,
          f"timed-out node did NOT emit state:done success event (got: {done_success!r})")


@register("_test_slow_noncoop")
class _SlowNonCoop(BlockSpec):
    """Sleeps for a fixed period without checking ctx.stopped() (non-cooperative)."""
    label = "slow_noncoop"; category = "Test"; inputs = []; outputs = []

    def run(self, ctx, inputs):
        _time.sleep(10)   # non-cooperative — ignores the stop signal
        return {}


def test_node_timeout_on_error_skipped_user_stop_during_run():
    """on_error must NOT run when user pressed Stop mid-execution.

    When the user presses Stop while a non-cooperative node is executing, the
    user_was_stopped flag captured at watchdog-fire time will be True, so
    run_graph must skip the on_error handler (honour the stop).
    """
    print("\n[executor] node_timeout: on_error skipped when user Stop fired during execution")
    g = Graph.from_dict({"name": "t_noncoop", "meta": {"node_timeout": 0.5}, "nodes": [
        _node("slow_nc", type="_test_slow_noncoop", on_error="handler"),
        _node("handler", type="_test_side_effect"),
    ]})
    events = []
    ctx = make_ctx(events)
    # Set stop_event after a short delay, simulating user pressing Stop at 0.15 s.
    def _press_stop():
        _time.sleep(0.15)
        ctx.stop_event.set()
    threading.Thread(target=_press_stop, daemon=True).start()
    status = run_graph(g, ctx)
    # Run may return "stopped" (if stop_event is checked before watchdog fires)
    # or "error" (if watchdog fires first but user_was_stopped=True).  Either way
    # the on_error handler must NOT have run.
    check(status in ("stopped", "error"),
          f"run aborts with stopped or error (got {status!r})")
    check("ran" not in ctx.vars.get("effects", []),
          "on_error handler did NOT run after user Stop during execution")


def test_node_timeout_on_error_skipped_when_user_stopped():
    """on_error handler must NOT run after a user-initiated Stop.

    If the user pressed Stop *before* the timeout fires, run_graph must honour
    the explicit cancellation and skip the on_error handler entirely.
    """
    print("\n[executor] node_timeout: on_error skipped when user already stopped")
    g = Graph.from_dict({"name": "t6", "meta": {"node_timeout": 5.0}, "nodes": [
        _node("slow", type="_test_slow_cooperative", on_error="handler"),
        _node("handler", type="_test_side_effect"),
    ]})
    events = []
    ctx = make_ctx(events)
    # Pre-set stop_event to simulate a user Stop arriving before the run.
    ctx.stop_event.set()
    status = run_graph(g, ctx)
    # With stop_event pre-set, the run should abort immediately ("stopped").
    # The on_error handler must NOT have run.
    check(status in ("stopped", "error"),
          f"run aborts when pre-stopped (got {status!r})")
    check("ran" not in ctx.vars.get("effects", []),
          "on_error handler did NOT run after user Stop (stop_event preserved)")


def test_node_timeout_invalid_meta_zero():
    """A node_timeout of zero is ignored (treated as unlimited)."""
    print("\n[executor] node_timeout: zero timeout is ignored, run completes")
    g = Graph.from_dict({"name": "tz", "meta": {"node_timeout": 0}, "nodes": [
        _node("a", type="_test_marker", params={"_id": "a"}),
    ]})
    status = run_graph(g, make_ctx([]))
    check(status == "ok", f"zero timeout ignored, status=ok (got {status!r})")


def test_node_timeout_invalid_meta_negative():
    """A negative node_timeout is ignored (treated as unlimited)."""
    print("\n[executor] node_timeout: negative timeout is ignored, run completes")
    g = Graph.from_dict({"name": "tn", "meta": {"node_timeout": -5.0}, "nodes": [
        _node("a", type="_test_marker", params={"_id": "a"}),
    ]})
    status = run_graph(g, make_ctx([]))
    check(status == "ok", f"negative timeout ignored, status=ok (got {status!r})")


def test_node_timeout_invalid_meta_nonnumeric():
    """A non-numeric node_timeout is ignored (treated as unlimited)."""
    print("\n[executor] node_timeout: non-numeric timeout is ignored, run completes")
    g = Graph.from_dict({"name": "tnn", "meta": {"node_timeout": "fast"}, "nodes": [
        _node("a", type="_test_marker", params={"_id": "a"}),
    ]})
    status = run_graph(g, make_ctx([]))
    check(status == "ok", f"non-numeric timeout ignored, status=ok (got {status!r})")


def test_stuck_graph_diagnostic():
    """Executor no-ready-node path emits a diagnostic naming the stuck nodes.

    graph.validate() uses Kahn's algorithm and would normally catch cycles before
    run_graph is called. We monkeypatch validate() to return [] so the cyclic
    graph slips through to the executor loop, which is the code path being tested.
    """
    print("\n[executor] stuck graph: executor diagnostic names stuck nodes")
    g = Graph.from_dict({"name": "stuck", "nodes": [
        _node("alpha", after=["beta"], type="_test_marker"),
        _node("beta",  after=["alpha"], type="_test_marker"),
    ]})
    g.validate = lambda: []   # bypass pre-run cycle check — test the executor path
    events = []
    ctx = make_ctx(events)
    status = run_graph(g, ctx)
    check(status == "error", f"stuck graph status=error (got {status!r})")
    done = [e for e in events if e.get("type") == "done"]
    check(bool(done) and done[-1]["status"] == "error", "done event status=error")
    err_msg = done[-1].get("error", "") if done else ""
    check(
        "stuck" in err_msg.lower() or "waiting" in err_msg.lower() or "ready" in err_msg.lower(),
        f"error message is diagnostic (got: {err_msg!r})"
    )
    check(
        "alpha" in err_msg or "beta" in err_msg,
        f"error message names at least one stuck node (got: {err_msg!r})"
    )


if __name__ == "__main__":
    test_registry_specs()
    test_topo_order()
    test_cycle_guard()
    test_unknown_type()
    test_fail_stop()
    test_on_error_then_abort()
    test_stop_event()
    test_data_edge()
    test_data_edge_orders()
    test_if_branch()
    test_skip_propagation()
    test_node_timeout_fires()
    test_node_timeout_no_side_effects_after()
    test_node_timeout_no_late_emit()
    test_node_timeout_fast_node_unaffected()
    test_node_timeout_on_error_runs()
    test_node_timeout_no_done_event_on_aborted_node()
    test_node_timeout_on_error_skipped_user_stop_during_run()
    test_node_timeout_on_error_skipped_when_user_stopped()
    test_node_timeout_invalid_meta_zero()
    test_node_timeout_invalid_meta_negative()
    test_node_timeout_invalid_meta_nonnumeric()
    test_stuck_graph_diagnostic()
    print(f"\n=== {_passed} passed, {_failed} failed ===")
    sys.exit(1 if _failed else 0)
