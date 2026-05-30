"""Vision primitives — thin wraps over core.vision / ui_manager."""
from engine.registry import BlockSpec, Param, Port, Kind, register
from screens.home_screen import HomeScreen
from screens.attack_screen import AttackScreen
from screens.battle_screen import BattleScreen


@register("is_home")
class IsHome(BlockSpec):
    label = "Is Home Screen"
    category = "Vision"
    inputs = []
    outputs = [Port("yes", Kind.Bool)]

    def run(self, ctx, inputs):
        return {"yes": bool(HomeScreen(ctx.ui_manager).is_current_screen())}


@register("is_attack")
class IsAttack(BlockSpec):
    label = "Is Attack Screen"
    category = "Vision"
    inputs = []
    outputs = [Port("yes", Kind.Bool)]

    def run(self, ctx, inputs):
        return {"yes": bool(AttackScreen(ctx.ui_manager, ctx.settings).is_current_screen())}


@register("is_battle")
class IsBattle(BlockSpec):
    label = "Is Battle Screen"
    category = "Vision"
    inputs = []
    outputs = [Port("yes", Kind.Bool)]

    def run(self, ctx, inputs):
        return {"yes": bool(BattleScreen(ctx.ui_manager).is_current_screen())}


@register("wait_template")
class WaitTemplate(BlockSpec):
    label = "Wait For Template"
    category = "Vision"
    inputs = [
        Param("template", Kind.Template),
        Param("timeout", Kind.Number, default=5),
        Param("threshold", Kind.Number, default=0.7),
    ]
    outputs = [Port("coord", Kind.Coord), Port("found", Kind.Bool)]

    def run(self, ctx, inputs):
        loc = ctx.ui_manager.wait_until_appears(
            inputs["template"],
            timeout=float(inputs.get("timeout", 5)),
            threshold=float(inputs.get("threshold", 0.7)),
        )
        return {"coord": loc, "found": loc is not None}


@register("is_screen")
class IsScreen(BlockSpec):
    label = "Is Screen (anchors)"
    category = "Vision"
    inputs = [Param("anchors", Kind.Text), Param("threshold", Kind.Number, default=0.7)]
    outputs = [Port("matched", Kind.Bool)]

    def run(self, ctx, inputs):
        anchors = inputs.get("anchors") or []
        if isinstance(anchors, str):
            anchors = [a.strip() for a in anchors.split(",") if a.strip()]
        found = ctx.ui_manager.scan_all(
            anchors, use_orb_fallback=False, threshold=float(inputs.get("threshold", 0.7))
        )
        return {"matched": len(found) == len(anchors) and bool(anchors)}


@register("find_template")
class FindTemplate(BlockSpec):
    label = "Find Template"
    category = "Vision"
    inputs = [Param("template", Kind.Template), Param("threshold", Kind.Number, default=0.7)]
    outputs = [Port("coord", Kind.Coord), Port("found", Kind.Bool)]

    def run(self, ctx, inputs):
        screen = ctx.ui_manager.get_screen()
        if screen is None:
            return {"coord": None, "found": False}
        loc = ctx.vision.find_template(
            screen, inputs["template"],
            threshold=float(inputs.get("threshold", 0.7)),
            use_orb_fallback=False,
        )
        return {"coord": loc, "found": loc is not None}
