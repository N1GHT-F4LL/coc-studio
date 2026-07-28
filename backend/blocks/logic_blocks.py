"""Logic / value blocks — engine-native, no device.

These feed the ``if`` block and data edges: produce constants, compare numbers,
and combine booleans. e.g. read_loot.gold -> compare(>=, 500000) -> if.cond.
"""
import operator

from engine.registry import BlockSpec, Param, Port, Kind, register

_OPS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}


@register("const_number")
class ConstNumber(BlockSpec):
    label = "Number"
    category = "Logic"
    inputs = [Param("value", Kind.Number, default=0)]
    outputs = [Port("value", Kind.Number)]

    def run(self, ctx, inputs):
        return {"value": float(inputs.get("value", 0))}


@register("const_bool")
class ConstBool(BlockSpec):
    label = "Boolean"
    category = "Logic"
    inputs = [Param("value", Kind.Bool, default=True)]
    outputs = [Port("value", Kind.Bool)]

    def run(self, ctx, inputs):
        return {"value": bool(inputs.get("value"))}


@register("compare")
class Compare(BlockSpec):
    label = "Compare (a ? b)"
    category = "Logic"
    inputs = [
        Param("a", Kind.Number, default=0),
        Param("op", Kind.Text, default=">=", choices=list(_OPS.keys())),
        Param("b", Kind.Number, default=0),
    ]
    outputs = [Port("result", Kind.Bool)]

    def run(self, ctx, inputs):
        op = _OPS.get(inputs.get("op", ">="))
        if op is None:
            raise ValueError(f"compare: unknown op {inputs.get('op')!r}")
        return {"result": bool(op(float(inputs.get("a", 0)), float(inputs.get("b", 0))))}


@register("logic_and")
class LogicAnd(BlockSpec):
    label = "And"
    category = "Logic"
    inputs = [Param("a", Kind.Bool, default=False), Param("b", Kind.Bool, default=False)]
    outputs = [Port("result", Kind.Bool)]

    def run(self, ctx, inputs):
        return {"result": bool(inputs.get("a")) and bool(inputs.get("b"))}


@register("logic_or")
class LogicOr(BlockSpec):
    label = "Or"
    category = "Logic"
    inputs = [Param("a", Kind.Bool, default=False), Param("b", Kind.Bool, default=False)]
    outputs = [Port("result", Kind.Bool)]

    def run(self, ctx, inputs):
        return {"result": bool(inputs.get("a")) or bool(inputs.get("b"))}


@register("logic_not")
class LogicNot(BlockSpec):
    label = "Not"
    category = "Logic"
    inputs = [Param("a", Kind.Bool, default=False)]
    outputs = [Port("result", Kind.Bool)]

    def run(self, ctx, inputs):
        return {"result": not bool(inputs.get("a"))}


@register("const_text")
class ConstText(BlockSpec):
    label = "Text"
    category = "Logic"
    inputs = [Param("value", Kind.Text, default="")]
    outputs = [Port("value", Kind.Text)]

    def run(self, ctx, inputs):
        return {"value": str(inputs.get("value", ""))}


@register("const_coord")
class ConstCoord(BlockSpec):
    label = "Coordinate"
    category = "Logic"
    inputs = [
        Param("x", Kind.Number, default=0, label="X"),
        Param("y", Kind.Number, default=0, label="Y"),
    ]
    outputs = [Port("coord", Kind.Coord)]

    def run(self, ctx, inputs):
        return {"coord": (float(inputs.get("x", 0)), float(inputs.get("y", 0)))}


@register("log_message")
class LogMessage(BlockSpec):
    label = "Log"
    category = "Logic"
    inputs = [
        Param("message", Kind.Text, default="", label="Message"),
        Param("level", Kind.Text, default="info",
              label="Level", choices=["debug", "info", "warning", "error"]),
    ]
    outputs = []

    def run(self, ctx, inputs):
        msg = str(inputs.get("message", ""))
        level = str(inputs.get("level", "info")).lower()
        log_fn = getattr(ctx.logger, level, ctx.logger.info)
        log_fn("[log] %s", msg)
        return {}


@register("set_var")
class SetVar(BlockSpec):
    label = "Set Variable"
    category = "Logic"
    inputs = [
        Param("name", Kind.Text, default="", label="Variable name"),
        Param("value", Kind.Text, default="", label="Value"),
    ]
    outputs = []

    def run(self, ctx, inputs):
        name = str(inputs.get("name", "")).strip()
        if not name:
            ctx.logger.warning("[set_var] 'name' is empty — nothing written.")
            return {}
        ctx.vars[name] = inputs.get("value", "")
        ctx.logger.debug("[set_var] %s = %r", name, ctx.vars[name])
        return {}


@register("get_var")
class GetVar(BlockSpec):
    label = "Get Variable"
    category = "Logic"
    inputs = [Param("name", Kind.Text, default="", label="Variable name")]
    outputs = [Port("value", Kind.Text), Port("exists", Kind.Bool)]

    def run(self, ctx, inputs):
        name = str(inputs.get("name", "")).strip()
        val = ctx.vars.get(name)
        return {"value": str(val) if val is not None else "", "exists": val is not None}
