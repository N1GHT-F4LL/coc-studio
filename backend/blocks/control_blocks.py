"""Control blocks — engine-native (no device needed).

  delay        cooperative sleep
  if           routes the ``then``/``else`` control branch from a Bool input
  loop_n       runs a saved sub-graph N times
  loop_until   runs a saved sub-graph until a ctx var is truthy (or max iters)

``if`` returns the engine's branch sentinel (``_branch``) which the executor uses
to activate branch-labelled control edges. The loop blocks reuse ``run_graph`` on
a referenced saved graph (the subroutine mechanism) — nested ``done`` events are
filtered so they don't end the outer run.
"""
import json
import os
import time

import app_paths
from engine.registry import BlockSpec, Param, Port, Kind, register
from engine.executor import run_graph, BRANCH_KEY
from engine.graph import Graph


def _load_graph(name):
    path = os.path.join(app_paths.GRAPHS_DIR, f"{name}.json")
    with open(path, "r", encoding="utf-8") as f:
        return Graph.from_dict(json.load(f))


def _run_subgraph(ctx, graph):
    """Run a sub-graph with the same context, swallowing its terminal done event."""
    outer_emit = ctx.emit

    def sub_emit(ev):
        if ev.get("type") == "done":
            return  # don't let a nested run end the outer run
        outer_emit(ev)

    ctx.emit = sub_emit
    try:
        return run_graph(graph, ctx)
    finally:
        ctx.emit = outer_emit


@register("delay")
class Delay(BlockSpec):
    label = "Delay"
    category = "Control"
    inputs = [Param("seconds", Kind.Number, default=1)]
    outputs = []

    def run(self, ctx, inputs):
        seconds = float(inputs.get("seconds", 1))
        # Cooperative sleep: wake immediately on stop (mirrors ui_manager._poll_sleep).
        if ctx.stop_event is not None:
            ctx.stop_event.wait(seconds)
        else:
            time.sleep(seconds)
        return {}


@register("if")
class If(BlockSpec):
    label = "If"
    category = "Control"
    inputs = [Param("cond", Kind.Bool, default=False)]
    # Trigger outputs render as branch control-out handles; the executor routes
    # control edges labelled with the matching branch name.
    outputs = [Port("then", Kind.Trigger), Port("else", Kind.Trigger)]

    def run(self, ctx, inputs):
        cond = bool(inputs.get("cond"))
        ctx.logger.info("[if] cond=%s -> %s", cond, "then" if cond else "else")
        return {BRANCH_KEY: "then" if cond else "else"}


@register("loop_n")
class LoopN(BlockSpec):
    label = "Loop N times"
    category = "Control"
    inputs = [Param("graph_ref", Kind.Text, source="graphs"),
              Param("times", Kind.Number, default=3)]
    outputs = []

    def run(self, ctx, inputs):
        name = inputs.get("graph_ref")
        if not name:
            raise ValueError("loop_n: graph_ref is required")
        graph = _load_graph(name)
        times = int(inputs.get("times", 3))
        for i in range(times):
            if ctx.stopped():
                break
            ctx.logger.info("[loop_n] %s iteration %d/%d", name, i + 1, times)
            _run_subgraph(ctx, graph)
        return {}


@register("loop_until")
class LoopUntil(BlockSpec):
    label = "Loop Until Var"
    category = "Control"
    inputs = [
        Param("graph_ref", Kind.Text, source="graphs"),
        Param("until_var", Kind.Text),
        Param("max_iters", Kind.Number, default=10),
    ]
    outputs = []

    def run(self, ctx, inputs):
        name = inputs.get("graph_ref")
        var = inputs.get("until_var")
        if not name or not var:
            raise ValueError("loop_until: graph_ref and until_var are required")
        graph = _load_graph(name)
        max_iters = int(inputs.get("max_iters", 10))
        for i in range(max_iters):
            if ctx.stopped() or ctx.vars.get(var):
                break
            ctx.logger.info("[loop_until] %s iteration %d (until %s)", name, i + 1, var)
            _run_subgraph(ctx, graph)
        return {}
