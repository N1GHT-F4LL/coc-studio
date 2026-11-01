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
