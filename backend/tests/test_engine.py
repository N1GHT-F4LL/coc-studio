"""Engine smoke test — no device needed.

Verifies the generic executor: topo-order, run-events, cycle guard, and the
fail-stop error model (a raising block aborts the run; later nodes don't run).

Run from backend/:  ..\\.venv\\Scripts\\python.exe tests\\test_engine.py
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
    all_block_specs = all_specs()
    specs = {s["type"] for s in all_block_specs}
    for t in ("collect_resources", "find_match", "deploy", "return_home",
              "wait_template", "tap", "read_number", "delay"):
        check(t in specs, f"block registered: {t}")
    deploy = next((s for s in all_block_specs if s["type"] == "deploy"), None)
    deploy_inputs = {p["name"]: p for p in (deploy or {}).get("inputs", [])}
    check(deploy_inputs.get("deploy_event_troops", {}).get("default") is True,
          "deploy exposes enabled event troop dump")

def test_deploy_bool_params():
    print("\n[deploy] bool param parsing")
    from blocks.coc_blocks import _param_bool
    check(_param_bool("false", True) is False, "string false disables bool param")
    check(_param_bool("0", True) is False, "string 0 disables bool param")
    check(_param_bool(None, True) is True, "missing bool uses default")


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


if __name__ == "__main__":
    test_registry_specs()
    test_deploy_bool_params()
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
    print(f"\n=== {_passed} passed, {_failed} failed ===")
    sys.exit(1 if _failed else 0)
