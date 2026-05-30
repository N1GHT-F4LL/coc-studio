"""run_graph — the generic executor.

Generalizes the proven loop in ``screens/battle_screen.py:_slot_deploy``
(completed/pending/ready, cycle-guarded), extended for M5 with:

  - **data edges**: a node's ``data_in`` ports are resolved from upstream
    outputs, and a data edge also implies ordering (consumer runs after producer).
  - **branching / skip**: control (``after``) edges may carry a branch label.
    A node is *active* only if at least one incoming control edge is active
    (default edges are always active once their source ran; branch edges are
    active only when the source's chosen ``_branch`` matches) and all its data
    producers ran. Inactive nodes are *skipped*, and skips propagate downstream.

Error model stays **fail-stop** (REQUIREMENT §5/§16): a block raising follows its
``on_error`` node if present, else aborts the whole run.
"""
from .graph import Graph
from .registry import REGISTRY

# Sentinel keys a control block may return to drive branch edges.
BRANCH_KEY = "_branch"


class GraphError(Exception):
    """Raised before execution when the graph is structurally invalid."""


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
    ctx.emit({"type": "node", "id": node.id, "state": "running"})
    out = REGISTRY[node.type]().run(ctx, inputs) or {}
    outputs[node.id] = out
    ctx.emit({"type": "node", "id": node.id, "state": "done", "outputs": out})


def run_graph(graph: Graph, ctx) -> str:
    """Execute ``graph`` to completion. Returns "ok" | "error" | "stopped".

    Also emits a final ``{"type":"done","status":...}`` event.
    """
    errors = graph.validate()
    if errors:
        raise GraphError("; ".join(errors))

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
            ctx.emit({"type": "done", "status": "error",
                      "error": "no ready nodes (cycle?)"})
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
