"""CoC "big" blocks — each wraps a whole screens/ method.

These give a working farm cycle fast (the M2 parity target vs run_bot). Later
they can be exploded into sub-graphs; for now they are leaf blocks.

Var-gating: in a control-only linear graph (M2) there are no if-edges yet, so
``find_match`` records its result in ``ctx.vars["match_found"]`` and the
downstream ``deploy``/``return_home`` blocks no-op when it's false. This mirrors
the early-return short-circuit of the original ``run_attack_cycle`` and is the
bridge to real if-edges in M5.
"""
from engine.registry import BlockSpec, Param, Port, Kind, register
from screens.home_screen import HomeScreen
from screens.attack_screen import AttackScreen


@register("collect_resources")
class CollectResources(BlockSpec):
    label = "Collect Resources"
    category = "CoC"
    inputs = []
    outputs = []

    def run(self, ctx, inputs):
        HomeScreen(ctx.ui_manager).collect_resources()
        return {}


@register("find_match")
class FindMatch(BlockSpec):
    label = "Find Match"
    category = "CoC"
    inputs = []
    outputs = [Port("found", Kind.Bool)]

    def run(self, ctx, inputs):
        found = AttackScreen(ctx.ui_manager, ctx.settings).find_match()
        ctx.vars["match_found"] = bool(found)
        return {"found": bool(found)}


@register("deploy")
class Deploy(BlockSpec):
    label = "Deploy Troops"
    category = "CoC"
    inputs = []
    outputs = [Port("deployed", Kind.Bool)]

    def run(self, ctx, inputs):
        if not ctx.vars.get("match_found"):
            ctx.logger.info("[deploy] no match held — skipping (match_found is false).")
            return {"deployed": False}
        deployed = AttackScreen(ctx.ui_manager, ctx.settings).deploy()
        return {"deployed": bool(deployed)}


@register("return_home")
class ReturnHome(BlockSpec):
    label = "Return Home"
    category = "CoC"
    inputs = []
    outputs = []

    def run(self, ctx, inputs):
        if not ctx.vars.get("match_found"):
            ctx.logger.info("[return_home] no match held — skipping.")
            return {}
        AttackScreen(ctx.ui_manager, ctx.settings).return_home()
        return {}


@register("request_clan_troops")
class RequestClanTroops(BlockSpec):
    label = "Request Clan Troops"
    category = "CoC"
    inputs = []
    outputs = []

    def run(self, ctx, inputs):
        AttackScreen(ctx.ui_manager, ctx.settings)._request_clan_troops()
        return {}
