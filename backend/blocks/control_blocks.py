"""Control primitives — engine-native blocks (no device needed).

M2 ships ``delay`` only (used in engine unit tests too). The branching blocks
(``if``, ``loop_n``, ``loop_until``, ``on_error``) land in M5 with typed edges.
"""
import time

from engine.registry import BlockSpec, Param, Port, Kind, register


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
