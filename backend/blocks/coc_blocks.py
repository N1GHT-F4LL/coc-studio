"""CoC "big" blocks — each wraps a whole screens/ method.

These give a working farm cycle fast (the M2 parity target vs run_bot). Later
they can be exploded into sub-graphs; for now they are leaf blocks.

Var-gating: in a control-only linear graph (M2) there are no if-edges yet, so
``find_match`` records its result in ``ctx.vars["match_found"]`` and the
downstream ``deploy``/``return_home`` blocks no-op when it's false. This mirrors
the early-return short-circuit of the original ``run_attack_cycle`` and is the
bridge to real if-edges in M5.
"""
import time

from engine.registry import BlockSpec, Param, Port, Kind, register
from screens.home_screen import HomeScreen
from screens.attack_screen import AttackScreen
from screens.battle_screen import BattleScreen
from device_manager import save_settings, COC_PACKAGE
import scenario_store


@register("ensure_home")
class EnsureHome(BlockSpec):
    """Make CoC ready and land on the village home screen (run_bot startup).

    Wraps device.ensure_coc_ready (launch/foreground CoC) + the home-detection,
    popup-dismiss, zoom-out and game-restart recovery from coc_bot/main.py. Put
    this at the start of a farm graph so the cycle doesn't act on the wrong app
    (e.g. the BlueStacks store) or a popped-up screen.
    """
    label = "Ensure Home"
    category = "CoC"
    inputs = [Param("zoom_out", Kind.Bool, default=True),
              Param("timeout", Kind.Number, default=10)]
    outputs = [Port("home", Kind.Bool)]

    def run(self, ctx, inputs):
        dev = ctx.device
        ui = ctx.ui_manager
        if not dev.ensure_coc_ready(COC_PACKAGE, ctx.settings, save_settings, ctx.logger):
            ctx.logger.warning("[ensure_home] CoC not ready (install/launch failed).")
            ctx.vars["home"] = False
            return {"home": False}

        home = HomeScreen(ui)
        zoom = bool(inputs.get("zoom_out", True))

        def settle():
            for _ in range(4):
                home.close_popups()
                ui._poll_sleep(0.6)
            if zoom:
                dev.pinch("out", span_pixels=600, repeats=1)
                ui._poll_sleep(1.0)

        deadline = time.time() + float(inputs.get("timeout", 10))
        while time.time() < deadline:
            if ctx.stopped():
                ctx.vars["home"] = False
                return {"home": False}
            if home.is_current_screen():
                ctx.logger.info("[ensure_home] home screen detected.")
                settle()
                ctx.vars["home"] = True
                return {"home": True}
            ui._poll_sleep(1)

        # Recovery: close popups then restart the game (run_bot HOME_DETECT path).
        ctx.logger.warning("[ensure_home] not home — restarting game.")
        home.close_popups()
        if dev.restart_game(COC_PACKAGE):
            ui._poll_sleep(15)
            if home.is_current_screen():
                settle()
                ctx.vars["home"] = True
                return {"home": True}
        ctx.logger.error("[ensure_home] could not reach home screen.")
        ctx.vars["home"] = False
        return {"home": False}


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
    # Empty scenario -> use settings active_scenario (AttackScreen.deploy path).
    # A scenario name -> run that migrated scenario (data/scenarios/<name>.json).
    inputs = [Param("scenario", Kind.Text, default="")]
    outputs = [Port("deployed", Kind.Bool)]

    def run(self, ctx, inputs):
        if not ctx.vars.get("match_found"):
            ctx.logger.info("[deploy] no match held — skipping (match_found is false).")
            return {"deployed": False}

        scenario = (inputs.get("scenario") or "").strip()
        if not scenario:
            deployed = AttackScreen(ctx.ui_manager, ctx.settings).deploy()
            return {"deployed": bool(deployed)}

        # Scenario path: wait for battle, pick a variant, run the same deploy bar
        # logic (BattleScreen.deploy_troops -> _slot_deploy) for parity.
        battle = BattleScreen(ctx.ui_manager)
        if not battle.wait_until_entered(timeout=15):
            ctx.logger.warning("[deploy] battle screen not detected — bailing.")
            return {"deployed": False}
        doc = scenario_store.load_scenario(scenario)
        nodes, variant_name = scenario_store.chosen_variant_nodes(doc)
        deploy_cfg = dict(ctx.settings.get("attack", {}).get("deploy", {}))
        deploy_cfg["nodes"] = nodes
        ctx.logger.info("[deploy] scenario=%s variant=%s nodes=%d",
                        scenario, variant_name, len(nodes))
        battle.deploy_troops(deploy_cfg)
        return {"deployed": True}


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
