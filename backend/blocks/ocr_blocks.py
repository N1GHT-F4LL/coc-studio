"""OCR primitives — read integers from a screen region via core.ocr."""
from engine.registry import BlockSpec, Param, Port, Kind, register


def _read(ctx, region, min_value=0, max_value=None):
    screen = ctx.ui_manager.get_screen()
    if screen is None:
        return None, 0.0
    return ctx.ocr_read(screen, tuple(region), min_value=min_value, max_value=max_value)


@register("read_number")
class ReadNumber(BlockSpec):
    label = "Read Number (OCR)"
    category = "OCR"
    inputs = [Param("region", Kind.Region), Param("min_value", Kind.Number, default=0)]
    outputs = [Port("value", Kind.Number), Port("confidence", Kind.Number)]

    def run(self, ctx, inputs):
        region = inputs.get("region")
        if not region or len(region) != 4:
            raise ValueError("read_number: region must be [x1,y1,x2,y2]")
        val, conf = _read(ctx, region, min_value=int(inputs.get("min_value", 0)))
        return {"value": val if val is not None else 0, "confidence": float(conf)}


@register("loot_ge")
class LootGE(BlockSpec):
    label = "Loot >= Threshold"
    category = "OCR"
    inputs = [Param("region", Kind.Region), Param("threshold", Kind.Number, default=0)]
    outputs = [Port("ok", Kind.Bool), Port("value", Kind.Number)]

    def run(self, ctx, inputs):
        region = inputs.get("region")
        if not region or len(region) != 4:
            raise ValueError("loot_ge: region must be [x1,y1,x2,y2]")
        val, _conf = _read(ctx, region)
        val = val if val is not None else 0
        return {"ok": val >= int(inputs.get("threshold", 0)), "value": val}
