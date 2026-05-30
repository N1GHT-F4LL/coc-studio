"""run_graph — the generic topo-order executor.

Generalizes the proven loop in ``screens/battle_screen.py:_slot_deploy``
(completed/pending/ready, cycle-guarded). Differences:
  - dispatches by block ``type`` via the REGISTRY instead of a hard-coded
    deploy action,
  - resolves each node's data inputs (``params`` literals + ``data_in`` ports),
  - emits run-events (node running/done/error, done) for the run console.

Error model is **fail-stop** (REQUIREMENT §5/§16): a block raising follows its
``on_error`` node if present, otherwise aborts the whole run. Never swallows an
error and continues with broken state.
"""
from .graph import Graph
from .registry import REGISTRY


class GraphError(Exception):
    """Raised before execution when the graph is structurally invalid."""


def resolve_inputs(node, spec, outputs: dict, ctx) -> dict:
    """Merge literal params with values pulled from upstream data ports.

    ``data_in`` wins over ``params`` for the same name. Data edges aren't used
    by the M2 CoC blocks but the resolver is wired now for M5 (typed edges).
    """
    inputs = dict(node.params)
    for port, src in node.data_in.items():
        if not isinstance(src, dict):
            continue
        frm = src.get("from")
        out_port = src.get("port")
        up = outputs.get(frm, {})
        if out_port in up:
            inputs[port] = up[out_port]
    return inputs


def _run_node(node, outputs: dict, ctx):
    """Execute one node: resolve inputs, call block.run, store + emit outputs."""
    spec_cls = REGISTRY[node.type]
    inputs = resolve_inputs(node, spec_cls, outputs, ctx)
    ctx.emit({"type": "node", "id": node.id, "state": "running"})
    out = spec_cls().run(ctx, inputs) or {}
    outputs[node.id] = out
    ctx.emit({"type": "node", "id": node.id, "state": "done", "outputs": out})
    return out


def run_graph(graph: Graph, ctx) -> str:
    """Execute ``graph`` to completion. Returns final status string.

    Status: "ok" | "error" | "stopped". Also emitted as a final
    ``{"type":"done","status":...}`` event.
    """
    errors = graph.validate()
    if errors:
        raise GraphError("; ".join(errors))

    by_id = {n.id: n for n in graph.nodes}
    outputs: dict = {}
    completed: set = set()
    pending = list(graph.nodes)          # preserve original order for stable dispatch

    while pending:
        if ctx.stopped():
            ctx.emit({"type": "done", "status": "stopped"})
            return "stopped"

        # Nodes whose control deps are all satisfied (mirrors _slot_deploy).
        ready = [n for n in pending if all(dep in completed for dep in n.after)]
        if not ready:
            # Shouldn't happen post-validate, but guard cleanly like _slot_deploy.
            ctx.emit({"type": "done", "status": "error",
                      "error": "no ready nodes (cycle?)"})
            return "error"

        for node in ready:
            if ctx.stopped():
                ctx.emit({"type": "done", "status": "stopped"})
                return "stopped"
            try:
                _run_node(node, outputs, ctx)
            except Exception as e:  # fail-stop
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
