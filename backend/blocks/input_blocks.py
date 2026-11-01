"""Input primitives — thin wraps over device / ui_manager click+swipe+pinch.

Taps go through ``ui_manager.click`` (applies humanize jitter) to match the
behaviour the rest of the bot relies on; ``device.tap`` is the raw fallback.
"""
from engine.registry import BlockSpec, Param, Port, Kind, register


@register("tap")
class Tap(BlockSpec):
    label = "Tap"
    category = "Input"
    inputs = [Param("coord", Kind.Coord)]
    outputs = []

    def run(self, ctx, inputs):
        coord = inputs.get("coord")
        if not coord:
            raise ValueError("tap: no coord")
        ctx.ui_manager.click(int(coord[0]), int(coord[1]))
        return {}


@register("tap_template")
class TapTemplate(BlockSpec):
    label = "Tap Template"
    category = "Input"
    inputs = [
        Param("template", Kind.Template),
        Param("timeout", Kind.Number, default=5),
        Param("threshold", Kind.Number, default=0.7),
    ]
    outputs = [Port("tapped", Kind.Bool)]

    def run(self, ctx, inputs):
        loc = ctx.ui_manager.wait_until_appears(
            inputs["template"],
            timeout=float(inputs.get("timeout", 5)),
            threshold=float(inputs.get("threshold", 0.7)),
        )
        if loc:
            ctx.ui_manager.click(*loc)
            return {"tapped": True}
        return {"tapped": False}


@register("swipe_line")
class SwipeLine(BlockSpec):
    label = "Swipe Line"
    category = "Input"
    inputs = [Param("start", Kind.Coord), Param("end", Kind.Coord)]
    outputs = []

    def run(self, ctx, inputs):
        start, end = inputs.get("start"), inputs.get("end")
        if not start or not end:
            raise ValueError("swipe_line: need start and end coords")
        ctx.device.swipe([(int(start[0]), int(start[1])), (int(end[0]), int(end[1]))])
        return {}


@register("pinch")
class Pinch(BlockSpec):
    label = "Pinch (zoom)"
    category = "Input"
    inputs = [
        Param("direction", Kind.Text, default="out"),
        Param("span_pixels", Kind.Number, default=600),
        Param("repeats", Kind.Number, default=1),
    ]
    outputs = []

    def run(self, ctx, inputs):
        ctx.device.pinch(
            direction=inputs.get("direction", "out"),
            span_pixels=int(inputs.get("span_pixels", 600)),
            repeats=int(inputs.get("repeats", 1)),
        )
        return {}
