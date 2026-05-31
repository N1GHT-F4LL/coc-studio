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
from engine.composition import required_composition
from screens.home_screen import HomeScreen
from screens.attack_screen import AttackScreen
from screens.battle_screen import BattleScreen
from screens.train_screen import TrainScreen
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


@register("ensure_troops")
class EnsureTroops(BlockSpec):
    """Train the army to match a deploy scenario before attacking.

    Reads the chosen scenario (same name as the ``deploy`` block), derives the
    required troop counts (e.g. Thrower×16, Healer×6, Archer×12), opens the
    Train Troops screen and taps each troop icon that many times. Put this at
    the START of a farm cycle — the previous cycle's army was just consumed, so
    this trains a fresh one for the next attack. Sets ``vars["troops_ready"]``.

    v1 trains TROOPS only (heroes aren't trained; sieges/spells are follow-up).
    Readiness: if ``capacity_region`` + ``target_capacity`` are set, polls OCR
    of the army-capacity number until it reaches the target; otherwise waits
    ``wait_seconds`` (0 = don't wait). Needs army-UI assets captured first — see
    screens/train_screen.py.
    """
    label = "Ensure Troops"
    category = "CoC"
    inputs = [
        Param("scenario", Kind.Text, default="", source="scenarios"),
        Param("troops_only", Kind.Bool, default=False),
        Param("capacity_region", Kind.Region, default=None),
        Param("target_capacity", Kind.Number, default=0),
        Param("tap_delay", Kind.Number, default=0.2),
        Param("threshold", Kind.Number, default=0.7),
        Param("max_wait", Kind.Number, default=180),
        Param("wait_seconds", Kind.Number, default=0),
    ]
    outputs = [Port("ready", Kind.Bool)]

    def run(self, ctx, inputs):
        scenario = (inputs.get("scenario") or "").strip()
        if not scenario:
            ctx.logger.warning("[ensure_troops] no scenario set — skipping (ready=False).")
            ctx.vars["troops_ready"] = False
            return {"ready": False}
        try:
            doc = scenario_store.load_scenario(scenario)
        except FileNotFoundError:
            ctx.logger.error("[ensure_troops] scenario %r not found.", scenario)
            ctx.vars["troops_ready"] = False
            return {"ready": False}

        comp = required_composition(doc)
        ctx.logger.info("[ensure_troops] %s -> %s", scenario, comp.summary())
        if not (comp.troops or comp.spells or comp.sieges):
            ctx.logger.info("[ensure_troops] scenario has nothing to train — nothing to do.")
            ctx.vars["troops_ready"] = True
            return {"ready": True}

        train = TrainScreen(ctx.ui_manager)
        if not train.open():
            ctx.vars["troops_ready"] = False
            return {"ready": False}

        tap_delay = float(inputs.get("tap_delay", 0.2))
        threshold = float(inputs.get("threshold", 0.7))
        troops_only = bool(inputs.get("troops_only", False))

        # Each section: clear it (-> bright roster) -> open its roster -> tap each
        # unit N times. Roster icons need FACE templates (units/roster/<name>),
        # NOT the badge-laden deploy assets (units/troops|spells|siege/<name>).
        sections = [("troop", comp.troops)]
        if not troops_only:
            sections += [("spell", comp.spells), ("siege", comp.sieges)]
        for kind, items in sections:
            if not items or ctx.stopped():
                continue
            train.clear_section(kind)
            train.open_roster(kind)
            for template_key, count in items.items():
                if ctx.stopped():
                    break
                roster_tpl = "units/roster/" + template_key.rsplit("/", 1)[-1]
                train.train_unit(roster_tpl, count, tap_delay=tap_delay, threshold=threshold)

        train.back_home()

        ready = self._wait_ready(ctx, inputs)
        ctx.vars["troops_ready"] = ready
        return {"ready": ready}

    def _wait_ready(self, ctx, inputs):
        """Block until the army is trained, by OCR or a fixed wait."""
        import time

        region = inputs.get("capacity_region")
        target = int(inputs.get("target_capacity", 0) or 0)
        max_wait = float(inputs.get("max_wait", 180) or 0)

        if region and len(region) == 4 and target > 0:
            deadline = time.time() + max_wait
            while time.time() < deadline:
                if ctx.stopped():
                    return False
                screen = ctx.ui_manager.get_screen()
                if screen is not None:
                    used, conf = ctx.ocr_read(screen, tuple(region), min_value=0)
                    if used is not None:
                        ctx.logger.info("[ensure_troops] army %s/%s (conf %.2f)", used, target, conf)
                        if used >= target:
                            return True
                ctx.ui_manager._poll_sleep(3)
            ctx.logger.warning("[ensure_troops] capacity target not reached in %.0fs.", max_wait)
            return False

        wait_s = float(inputs.get("wait_seconds", 0) or 0)
        if wait_s > 0:
            ctx.logger.info("[ensure_troops] waiting %.0fs for training (fixed).", wait_s)
            ctx.ui_manager._poll_sleep(wait_s)
        return True


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
    inputs = [Param("scenario", Kind.Text, default="", source="scenarios")]
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
