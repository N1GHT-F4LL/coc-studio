"""OCR primitives — read integers from a screen region via core.ocr."""
from engine.registry import BlockSpec, Param, Port, Kind, register
from screens.attack_screen import AttackScreen


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


@register("read_loot")
class ReadLoot(BlockSpec):
    label = "Read Loot (gold/elixir/dark)"
    category = "OCR"
    inputs = []
    outputs = [Port("gold", Kind.Number), Port("elixir", Kind.Number),
               Port("dark", Kind.Number)]

    def run(self, ctx, inputs):
        # Wraps AttackScreen._read_loot (icon-anchored loot OCR on the scout screen).
        screen = ctx.ui_manager.get_screen()
        if screen is None:
            return {"gold": 0, "elixir": 0, "dark": 0}
        attack_cfg = ctx.settings.get("attack", {})
        loot, _conf = AttackScreen(ctx.ui_manager, ctx.settings)._read_loot(screen, attack_cfg)
        return {"gold": loot["gold"], "elixir": loot["elixir"], "dark": loot["dark_elixir"]}


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
