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

# TẦNG dừng có kiểm soát (design 2026-11-01): số chu kỳ attack LIÊN TIẾP kết
# thúc bất thường (battle timeout / không xác nhận về làng) trước khi dừng
# run. Reset về 0 khi một chu kỳ kết thúc bình thường. KHÔNG tự restart app.
MAX_NO_PROGRESS_RUNS = 3

from engine.registry import BlockSpec, Param, Port, Kind, register
from engine.composition import required_composition
from core.vision import vision
from screens.home_screen import HomeScreen
from screens.attack_screen import AttackScreen
from screens.battle_screen import BattleScreen
from screens.train_screen import TrainScreen
from device_manager import save_settings, COC_PACKAGE
from zoom_out import multi_zoom_out
import popup_guard
import scenario_store

# System popups (Another device / Connection lost / Client error! / rate
# dialog) are handled ENTIRELY by the popup_guard module (Simplicity bot
# mechanism, POPUP_HANDLING_ANALYSIS.md): strict template detection +
# boot_recovery relaunch — the old tap-the-button reconnect handling is gone
# because those popups have no live session behind them and cannot be
# dismissed in-game. See popup_guard.guard_and_recover for the guard pattern.


def ensure_village_zoom(ctx):
    """Guarantee the home village is zoomed all the way out BEFORE find_match
    taps Attack (user spec 2026-10-29: zoom must precede 'Tapped Attack!').

    All collect/plan coordinates assume the fully zoomed-out view, and the
    camera's zoom state after a battle return is not trustworthy, so the zoom
    is re-established EVERY cycle instead of once per Run:
      - ``return_home`` clears the ``village_zoomed`` session flag after a
        battle,
      - ``ensure_home.settle`` re-zooms (and sets the flag) on the next cycle,
      - THIS hook is the last line of defence: a cycle arriving at find_match
        with no valid zoom is zoomed RIGHT HERE, immediately before the
        Attack tap. No-op when the flag is already valid or we are not on the
        village (find_match will bail on its own).
    """
    if scenario_store.get_session_flag("village_zoomed"):
        ctx.logger.info("[find_match] village zoom verified (camera already maxed this cycle).")
        return
    if not HomeScreen(ctx.ui_manager).is_current_screen():
        return
    ctx.wait_if_paused()
    ctx.logger.info("ZOOMING OUT . . .")
    serial = (getattr(ctx.device, "serial", None)
              or (ctx.settings.get("device", {}) or {}).get("serial"))
    if multi_zoom_out(serial):
        scenario_store.set_session_flag("village_zoomed", True)
        ctx.logger.info("[find_match] village zoomed out (u2 pinch) — ready to attack.")
    else:
        ctx.logger.warning("[find_match] zoom-out did not land — attacking at the current zoom.")


@register("mv_rotation")
class MvRotation(BlockSpec):
    """Multi-Village rotation — first node of the farm cycle.

    No-op unless data/multi_village.json has enabled=true and the switch
    interval has elapsed. When due: rotate to the next enabled+configured
    village via the Supercell ID switcher (FLAG_SECURE — desktop self-capture
    OCR locates the account row by name, see multi_village.py), apply that
    village's saved scenario + farm thresholds, and emit an mv_active event so
    the web UI points its editor at the village the bot is really farming.

    Refuses to run when an enabled village has NO saved config (nothing to
    farm it with — acceptance #10 scoped to what actually blocks rotation).
    A village that is merely not `confirmed` (no verified Apply switch yet)
    is NOT a blocker: every switch verifies the account (wait_home + the
    wrong-village identity check) and the first successful switch captures
    its home snapshot. Single-village mode (enabled=false) never reaches any
    of this code.
    """
    label = "MV Rotation"
    category = "CoC"
    inputs = []
    outputs = [Port("switched", Kind.Number)]

    def run(self, ctx, inputs):
        import multi_village as mv
        cfg = mv.load_config()
        if not cfg.get("enabled"):
            return {"switched": 0}

        # enabled + no config -> nothing to farm it with -> refuse, naming it.
        bad = [v for v in cfg.get("villages", [])
               if v.get("enabled") and not v.get("config")]
        if bad:
            names = ", ".join(f"Village_{v['idx']} ({v.get('name')})"
                              for v in bad)
            ctx.logger.error("[MV] enabled village(s) missing config: %s — run "
                             "refuses to start. Open the Multi-Village tab, Load "
                             "each one, set the scenario + thresholds and Save "
                             "(Apply is optional — the first rotation switch "
                             "verifies the account).", names)
            raise RuntimeError(f"Multi-Village: village(s) without config: {names}")

        state = mv.get_state()
        if state["current_village_idx"] is None:
            # fresh backend: assume the game sits on the first enabled village
            # and align the live settings with its saved config. Persisted
            # runtime state (multi_village.json) survives restarts, so this
            # only fires once per genuinely-new position.
            first = mv.enabled_villages(cfg)
            if first:
                mv.assume_village(first[0]["idx"], ctx)
        if state["current_village_idx"] is not None:
            mv.note_cycle(state["current_village_idx"])   # the previous cycle ran here

        unconfirmed = [v for v in cfg.get("villages", [])
                       if v.get("enabled") and v.get("config")
                       and not v.get("confirmed")]
        if unconfirmed and not ctx.vars.get("mv_unconfirmed_warned"):
            ctx.vars["mv_unconfirmed_warned"] = True
            names = ", ".join(f"Village_{v['idx']} ({v.get('name')})"
                              for v in unconfirmed)
            ctx.logger.warning("[MV] not confirmed yet (no verified Apply switch — "
                               "the first rotation switch verifies them): %s.", names)

        idx = mv.do_rotation(ctx)
        if idx is None:
            # every village failed this window — escalate like a dead cycle
            runs = int(ctx.vars.get("noprogress_runs", 0)) + 1
            ctx.vars["noprogress_runs"] = runs
            ctx.logger.error("[MV] all switch attempts failed this window "
                             "(%d/%d) — run stops for review.",
                             runs, MAX_NO_PROGRESS_RUNS)
            if runs >= MAX_NO_PROGRESS_RUNS and ctx.stop_event is not None:
                ctx.stop_event.set()
            return {"switched": -1}
        if idx:
            ctx.emit({"type": "mv_active", "idx": idx,
                      "name": (mv.village(mv.load_config(), idx) or {}).get("name", "")})
        # Settings verify (user 2026-11-19): TRƯỚC ensure_home "home screen
        # detected" — mở Settings panel và khớp avatar face của làng hiện tại
        # (assets/scid/v<idx>.png do user crop). Sai account → switch lại ĐÚNG
        # làng expected. Skip = không xác định được (không trên village screen /
        # panel không mở / chưa có face) — không bao giờ restart ở bước này.
        cur = mv.get_state()["current_village_idx"]
        if cur is not None:
            status = mv.settings_verify_face(cur)
            if status == "mismatch":
                ctx.logger.warning(
                    "[MV] settings verify: the device is NOT on village %s — "
                    "switching back to the expected account.", cur)
                if mv.switch_to_village(cur):
                    ctx.logger.info("[MV] corrective switch to village %s done.", cur)
                else:
                    ctx.logger.error("[MV] corrective switch to village %s FAILED — "
                                     "the next cycle retries after ensure_home.", cur)
            elif status == "match":
                ctx.logger.info("[MV] settings verify: village %s account confirmed.", cur)
        return {"switched": idx}


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
        # Loop-head guard (Simplicity bot_loop pattern): a system popup gets a
        # full relaunch here, then the normal flow below waits out the reboot
        # and re-establishes home — no abort needed at this level.
        popup_guard.guard_and_recover(ctx.logger,
                                      abort_log="Connection lost detected—recovering…")
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
            if zoom and not scenario_store.get_session_flag("village_zoomed"):
                # Zoom the village to MAX ONCE PER RUN SESSION with a real
                # two-finger pinch-in injected through uiautomator2 (Simplicity
                # bot mechanism, ZOOM_OUT_ANALYSIS.md) — replaces the host
                # mouse-wheel hack. The ATX agent injects via the Android
                # framework's InputManager (the path Memu honours for
                # multi-pointer) and nothing steals the Windows focus or
                # touches the host cursor. The flag resets on Stop/Start,
                # after an in-session game restart, AND after every battle
                # (return_home) — so each cycle re-zooms before its Attack
                # tap (user guarantee 2026-10-29; find_match re-checks it as
                # the last line of defence via ensure_village_zoom).
                ctx.wait_if_paused()        # respect the run's Pause
                ctx.logger.info("ZOOMING OUT . . .")
                serial = getattr(dev, "serial", None) or \
                    (ctx.settings.get("device", {}) or {}).get("serial")
                if multi_zoom_out(serial):
                    scenario_store.set_session_flag("village_zoomed", True)
                    ctx.logger.info("[ensure_home] village zoomed out (u2 pinch).")
                else:
                    ctx.logger.warning("[ensure_home] zoom-out did not land — "
                                       "continuing at the game's current zoom.")

        def poll_home(timeout):
            deadline = time.time() + float(timeout)
            while time.time() < deadline:
                if ctx.stopped():
                    return None
                # The Star Bonus popup covers the village and would keep home
                # detection failing until the restart path fires — tap its
                # green Okay right here, then re-poll.
                if popup_guard.dismiss_star_bonus(ctx.logger):
                    continue
                if home.is_current_screen():
                    return True
                # The full-screen treasure-chest event covers the village right
                # after a game restart when chests are pending — smash it IN
                # PLACE (bounded loop) and keep polling with a fresh budget
                # instead of paying a force-stop/launch cycle for one overlay.
                if popup_guard.treasure_chest_visible(ui.get_screen()):
                    ctx.logger.warning("[ensure_home] treasure-chest event screen "
                                       "up — smashing chests in place (no restart).")
                    popup_guard.smash_treasure_chests(ctx.logger)
                    deadline = time.time() + max(float(timeout), 30.0)
                    continue
                ui._poll_sleep(1)
            return False

        # poll_home returns True (home), False (timed out), or None (stopped).
        # A cooperative stop must abort immediately, NOT fall through to the
        # game-restart recovery below (which force-stops + relaunches CoC).
        res = poll_home(inputs.get("timeout", 10))
        if res:
            ctx.logger.info("[ensure_home] home screen detected.")
            settle()
            ctx.vars["home"] = True
            return {"home": True}
        if res is None:
            ctx.vars["home"] = False
            return {"home": False}

        # The full-screen treasure-chest event (Skip bottom-right) covers the
        # village by itself right after a game restart when chests are pending.
        # Smash it IN PLACE (bounded tap loop) instead of paying a 1-2 min
        # force-stop/launch cycle for one overlay.
        if popup_guard.treasure_chest_visible(ui.get_screen()):
            ctx.logger.warning("[ensure_home] treasure-chest event screen up — "
                               "smashing chests in place (no restart).")
            popup_guard.smash_treasure_chests(ctx.logger)
            res = poll_home(30)
            if res:
                ctx.logger.info("[ensure_home] home reached after smashing chests.")
                settle()
                ctx.vars["home"] = True
                return {"home": True}
            ctx.logger.warning("[ensure_home] still not home after smashing chests.")

        # Last chest-aware chance before paying for a restart: the post-smash
        # transition to home (or a slow game load) can outlast the poll budget.
        res = poll_home(20)
        if res:
            ctx.logger.info("[ensure_home] home screen detected (late settle).")
            settle()
            ctx.vars["home"] = True
            return {"home": True}

        # Recovery: close popups then restart the game (run_bot HOME_DETECT path).
        ctx.logger.warning("[ensure_home] not home — restarting game.")
        scenario_store.set_session_flag("village_zoomed", False)  # zoom resets with the game
        home.close_popups()
        if dev.restart_game(COC_PACKAGE):
            ui._poll_sleep(15)
            if poll_home(60):
                ctx.logger.info("[ensure_home] home reached after restart.")
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
        Param("selection", Kind.Text, default="random", choices=["random", "rotate"],
              label="Variant selection"),
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
        # Sub-task guard: recover + abort half-done work (the next cycle redoes
        # it cleanly — Simplicity one_cycle pattern).
        if popup_guard.guard_and_recover(ctx.logger):
            ctx.vars["troops_ready"] = False
            return {"ready": False}
        scenario = (ctx.vars.get("mv_scenario") if ctx.vars else None) or (inputs.get("scenario") or "").strip()
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

        # Pick ONE variant and train exactly it, then record the choice so the
        # deploy block uses the SAME variant (otherwise training counts the
        # MAX across variants while deploy picks one at random — over-training
        # and possibly overflowing the camp). Compose from just this variant.
        # selection="rotate" cycles variants in listed order (round-robin,
        # persisted across restarts) instead of weighted-random.
        if (inputs.get("selection") or "random") == "rotate":
            variant = scenario_store.pick_variant_rotating(doc, scenario)
        else:
            variant = scenario_store.pick_variant(doc)
        chosen_name = variant.get("name", "?")
        ctx.vars["chosen_variant"] = chosen_name
        comp = required_composition({"variants": [variant]})
        ctx.logger.info("[ensure_troops] %s variant=%s -> %s", scenario, chosen_name, comp.summary())
        if not (comp.troops or comp.spells or comp.sieges):
            ctx.logger.info("[ensure_troops] scenario has nothing to train — nothing to do.")
            ctx.vars["troops_ready"] = True
            return {"ready": True}

        # Roster training matches a face by the template's bare stem
        # (units/roster/<stem>), so two templates that differ only by folder
        # collide — warn rather than silently mistrain.
        from collections import defaultdict
        by_stem = defaultdict(list)
        for key in (*comp.troops, *comp.spells, *comp.sieges):
            by_stem[key.rsplit("/", 1)[-1]].append(key)
        for stem, keys in by_stem.items():
            if len(keys) > 1:
                ctx.logger.warning(
                    "[ensure_troops] %s share roster face %r — training can't tell "
                    "them apart; rename one.", keys, "units/roster/" + stem)

        train = TrainScreen(ctx.ui_manager)
        tap_delay = float(inputs.get("tap_delay", 0.2))
        threshold = float(inputs.get("threshold", 0.7))
        troops_only = bool(inputs.get("troops_only", False))

        # Open the army screen ONCE, then switch sections IN PLACE. Per section:
        # clear it (if non-empty), open its bright add-roster, tap each unit N
        # times, then collapse the roster by tapping an empty spot so the next
        # section's panel opens cleanly.
        #
        # Verified on device: clearing a section returns to the My Army overview
        # with the roster CLOSED (not left open, as previously assumed), so we
        # ALWAYS open_roster after clearing. And leaving the previous roster open
        # is what made in-place switching flaky, so close_roster (tap-outside)
        # between sections is required — the menu X can't be used because it
        # scrolls out of view once a roster pushes the menu up.
        #
        # Roster icons need FACE templates (units/roster/<name>), NOT the
        # badge-laden deploy assets (units/troops|spells|siege/<name>).
        sections = [("troop", comp.troops)]
        if not troops_only:
            sections += [("spell", comp.spells), ("siege", comp.sieges)]

        # "N/M" count label of each trainable section, measured LIVE on the
        # army screen (calib/verify_probe.py): labels sit ~90px above their
        # section's card row — troop 352/352 @ (777,211), spell 11/11 @
        # (766,434), siege @ (1319,432). The bottom-row 55/55 / 4/4 / 2/2
        # labels belong to other UI (recipes/pets), NOT the sections.
        verify_regions = {
            "troop": (700, 190, 855, 232),
            "spell": (715, 413, 820, 455),
            "siege": (1275, 411, 1365, 453),
        }

        def read_section_count(kind, retries=3):
            """OCR the section's 'N/M' count -> (n, total), either may be None.
            The label crop is upscaled 3x for OCR; stylized 1s often read as
            I/l so they are normalized before parsing; a lost slash is
            recovered by halving an even-length digit string.

            Waits for the army screen to be on the frame first (2026-11-18: a
            frame caught mid slide-in — or on the wrong screen entirely — OCRs
            empty, and the count verify then None/None-cleared a CORRECT army;
            measured live: the label can sit outside the calibrated region for
            the first ~1s after the screen opens)."""
            import re as _re
            import cv2 as _cv2
            r = verify_regions.get(kind)
            if not r:
                return None, None
            for _attempt in range(retries):
                screen = ctx.ui_manager.get_screen()
                if screen is None:
                    ctx.ui_manager._poll_sleep(0.8)
                    continue
                if not train.is_current_screen():
                    ctx.logger.info("[ensure_troops] %s: count read deferred — army screen "
                                    "not on the frame yet.", kind)
                    ctx.ui_manager._poll_sleep(1.0)
                    continue
                crop = screen[r[1]:r[3], r[0]:r[2]]
                up = _cv2.resize(crop, None, fx=3, fy=3, interpolation=_cv2.INTER_CUBIC)
                rgb = _cv2.cvtColor(up, _cv2.COLOR_BGR2RGB)
                from core.ocr import _get_reader
                txt = " ".join(str(t) for _b, t, c in _get_reader().readtext(rgb) if c > 0.3)
                norm = (txt.upper().replace(" ", "")
                        .translate(str.maketrans({"I": "1", "L": "1", "|": "1",
                                                  "O": "0", "S": "5", "B": "8"})))
                m = _re.search(r"(\d+)\s*/\s*(\d+)", norm)
                if m:
                    return int(m.group(1)), int(m.group(2))
                digits = _re.sub(r"\D", "", norm)
                if len(digits) >= 2 and len(digits) % 2 == 0:
                    h = len(digits) // 2
                    return int(digits[:h]), int(digits[h:])
                ctx.ui_manager._poll_sleep(0.8)   # panel may still be animating
            return None, None

        # Camp card rows on the army screen (1600x900), measured on a live
        # frame (calib/army_verify_probe.png): cards sit BELOW each section's
        # N/M label. Counts alone CANNOT verify an army — the game's Saved
        # Recipes auto-refill keeps the camp full with a DIFFERENT army that
        # reads the very same N/N. So each expected unit's card is matched in
        # its section's row. 2026-11-18 (user directive): verification checks
        # the DEDICATED folder assets/units/verify/<unit>.png — faces cropped
        # from the camp card row itself (the deploy assets in units/troops|
        # spells|siege render differently and miss: balloon scored 0.32 on the
        # real camp row). Verify faces are captured at the row's native size,
        # so no per-section rescale. A MISSING verify face only skips that
        # unit's card check (with a capture hint) — it never fails the army.
        CARD_REGIONS = {
            "troop": (20, 225, 1250, 380),
            "spell": (560, 440, 1120, 600),
            "siege": (1140, 440, 1520, 610),
        }
        CARD_MATCH_THRESHOLD = 0.70

        def composition_ok(kind, items):
            """True if every expected unit's card is present in the section's
            camp card row (verify faces from assets/units/verify, native
            scale). Units without a captured verify face are SKIPPED (warned),
            never treated as missing cards. Returns (ok, checked) — ``checked``
            = how many units were actually verified by a verify face; callers
            may only vouch by composition when EVERY planned unit was checked."""
            import cv2 as _cv2
            reg = CARD_REGIONS.get(kind)
            if not reg:
                return True, 0
            x1, y1, x2, y2 = reg
            screen = ctx.ui_manager.get_screen()
            if screen is None:
                return False, 0
            crop = _cv2.cvtColor(screen[y1:y2, x1:x2], _cv2.COLOR_BGR2GRAY)
            checked = 0
            for tpl_key in items:
                name = tpl_key.rsplit("/", 1)[-1]
                verify_key = f"units/verify/{name}"
                tpl = vision.cache.get(verify_key)
                if tpl is None:
                    ctx.logger.warning("[ensure_troops] %s: no verify face assets/units/verify/%s.png "
                                       "— card check skipped for this unit (capture it via the "
                                       "Assets tab, 'Verify (army cards)' category).",
                                       kind, name)
                    continue
                checked += 1
                th, tw = tpl.shape[:2]
                if th >= crop.shape[0] or tw >= crop.shape[1]:
                    ctx.logger.warning("[ensure_troops] %s: verify face %s is %dx%d — larger than "
                                       "the card row %dx%d; recapture it tighter.",
                                       kind, name, tw, th, crop.shape[1], crop.shape[0])
                    return False, checked
                res = _cv2.matchTemplate(crop, tpl, _cv2.TM_CCOEFF_NORMED)
                _, mv, _, _ = _cv2.minMaxLoc(res)
                if mv < CARD_MATCH_THRESHOLD:
                    ctx.logger.info("[ensure_troops] %s: %s card missing (conf %.2f < %.2f) — "
                                    "camp holds different units.", kind, name,
                                    mv, CARD_MATCH_THRESHOLD)
                    return False, checked
            return True, checked

        # Totals the correct army of THIS scenario+variant reads on its labels
        # (recorded after a training pass). Verification must match these
        # EXACTLY — but totals alone are necessary, never sufficient: the
        # composition card check above carries the real verdict.
        army_totals = scenario_store.get_army_totals(scenario, chosen_name) or {}
        trained_kinds = set()

        def ensure_army():
            """Be on the army screen.

            System popups are handled by the run watchdog and the block-level
            guard (popup_guard) — no in-game tapping here; if a popup covers
            the screen the section check below simply fails and is skipped."""
            if train.is_current_screen():
                return True
            return train.open()

        if not ensure_army():           # home -> army screen (once)
            ctx.vars["troops_ready"] = False
            return {"ready": False}

        # ---- camp-capacity scaling --------------------------------------
        # Not every account has the camp this plan was designed for
        # (designed_capacity in the scenario JSON). Scale the troop counts to
        # the REAL capacity read from the section label (the 50:50 dragon:
        # balloon count ratio survives scaling), fill whatever housing is left
        # with archers, and cache the scaled army for the rest of this Run
        # session (RunHub clears the cache on Stop / Start).
        designed = doc.get("designed_capacity")
        _, cap = read_section_count("troop")
        cached = army_totals if (army_totals and army_totals.get("capacity") == cap) else None
        scaled_counts = None
        if cap and designed and cap != designed and not cached:
            f = cap / float(designed)
            scaled_counts = {tpl: max(1, round(cnt * f)) for tpl, cnt in comp.troops.items()}
            ctx.logger.info("[ensure_troops] camp reads %d but the plan was designed for %d — "
                            "scaling troops x%.2f: %s", cap, designed, f,
                            {k.rsplit('/', 1)[-1]: v for k, v in scaled_counts.items()})
        fill_units = []
        if cached and cached.get("counts"):
            sections[0] = ("troop", dict(cached["counts"]))
            fill_units = list(cached.get("fill_units") or [])
        elif scaled_counts:
            sections[0] = ("troop", scaled_counts)

        reached_all = True              # could we open the army for every section?
        trained_all = True              # did every requested unit receive all taps?
        for kind, items in sections:
            if not items or ctx.stopped():
                continue
            if not ensure_army():       # recover if a popup bounced us home
                ctx.logger.warning("[ensure_troops] could not reach army screen for %s — skipping.", kind)
                reached_all = False
                continue
            n, total = read_section_count(kind)
            need = army_totals.get(kind)
            ctx.logger.info("[ensure_troops] verify %s count: %s/%s (trained army should read %s)",
                            kind, n, total, need)
            comp_items = {k: v for k, v in items.items() if k not in fill_units}
            comp_ok, comp_checked = composition_ok(kind, comp_items)
            if need is not None and n is not None and n == total == need and comp_ok:
                ctx.logger.info("[ensure_troops] %s: matches the trained army — keeping it.", kind)
                continue
            if (need is None and n is not None and n == total and n > 0 and comp_ok
                    and scaled_counts is None and comp_checked == len(comp_items) and comp_items):
                # No snapshot yet, but the camp holds EXACTLY the planned units
                # (every one verified by a camp-row face) — vouch by COMPOSITION
                # and record the snapshot instead of training again. The old
                # "training once to vouch" could never record a troop snapshot
                # (the queue drains after the post-training count read), so
                # troops were cleared + retrained EVERY cycle (2026-11-18).
                ctx.logger.info("[ensure_troops] %s: full %s/%s + composition verified "
                                "(%d/%d cards) — keeping it and recording the snapshot.",
                                kind, n, total, comp_checked, len(comp_items))
                snap = dict(army_totals) if army_totals else {}
                snap[kind] = n
                scenario_store.set_army_totals(scenario, chosen_name, snap)
                continue
            if need is None and n is not None and n == total and n > 0 and comp_ok:
                ctx.logger.info("[ensure_troops] %s: full (%s/%s) but no trained-army snapshot "
                                "for this variant yet — training once to vouch for it.", kind, n, total)
            elif need is not None and n == total == need and not comp_ok:
                ctx.logger.info("[ensure_troops] %s: counts match but the camp holds the WRONG units "
                                "(game recipe refill?) — retraining.", kind)
            else:
                ctx.logger.info("[ensure_troops] %s: doesn't match the trained army — (re)training.", kind)
            train.clear_section(kind)
            train.open_roster(kind)
            for template_key, count in items.items():
                if ctx.stopped():
                    break
                roster_tpl = "units/roster/" + template_key.rsplit("/", 1)[-1]
                # Prefer the dedicated roster face; fall back to the deploy asset
                # (template_key) so a unit without a captured face still gets
                # scrolled + matched instead of bailing early.
                tapped = train.train_unit(roster_tpl, count, tap_delay=tap_delay,
                                          threshold=threshold, fallback_template=template_key)
                if tapped < int(count):
                    trained_all = False
                    ctx.logger.warning(
                        "[ensure_troops] %s trained %d/%d - army is not ready; "
                        "capture units/roster/%s if template matching missed it.",
                        template_key, tapped, int(count), template_key.rsplit("/", 1)[-1])
                if tapped == 0 and "super_troops" in template_key:
                    ctx.logger.warning(
                        "[ensure_troops] %s trained 0 — a super troop only shows in the "
                        "roster once BOOSTED in-game; if it is boosted, capture a "
                        "units/roster/ face via the Assets tab.",
                        template_key.rsplit("/", 1)[-1])
            if kind == "troop" and scaled_counts is not None:
                # Scaled army: whatever housing the scaled counts left over is
                # filled with archers (1 housing each) until the label reads
                # full — self-correcting, no housing tables needed.
                for _ in range(3):
                    if ctx.stopped():
                        break
                    n_now, cap_now = read_section_count("troop")
                    if n_now is None or cap_now is None or n_now >= cap_now:
                        break
                    ctx.logger.info("[ensure_troops] filling %d leftover camp slot(s) with archers...",
                                    cap_now - n_now)
                    before = n_now
                    train.train_unit("units/roster/archer", cap_now - n_now,
                                     tap_delay=tap_delay, threshold=threshold,
                                     fallback_template="units/troops/archer")
                    ctx.ui_manager._poll_sleep(1.0)
                    n_after, _ = read_section_count("troop")
                    if n_after is None or n_after <= before:
                        break
                    scaled_counts["units/troops/archer"] = \
                        scaled_counts.get("units/troops/archer", 0) + (n_after - before)
                    if n_after >= cap_now:
                        break
            train.close_roster()        # collapse before the next section
            trained_kinds.add(kind)

        # Record what THIS army reads on its count labels right after training,
        # so later cycles can verify against the exact totals (a full army with
        # different totals = wrong army and must be retrained). Scaled armies
        # also cache their per-unit counts + capacity for the same purpose.
        if trained_kinds:
            snap = dict(army_totals) if army_totals else {}
            for kind in trained_kinds:
                n, total = read_section_count(kind)
                if n is not None and n == total and n > 0:
                    snap[kind] = n
                    ctx.logger.info("[ensure_troops] snapshot %s total = %s.", kind, n)
                else:
                    ctx.logger.info("[ensure_troops] %s reads %s/%s after training — snapshot "
                                    "not updated (counts may exclude the queue).", kind, n, total)
            if scaled_counts is not None and "troop" in trained_kinds:
                snap["counts"] = dict(scaled_counts)
                snap["capacity"] = snap.get("troop")
                snap["fill_units"] = [k for k in scaled_counts if k not in comp.troops]
            if snap:
                scenario_store.set_army_totals(scenario, chosen_name, snap)

        train.back_home()               # X -> home (once, at the end)

        # A fixed/no wait_ready can't observe training, so don't claim readiness
        # if a section never reached the army screen (e.g. a persistent popup).
        ready = self._wait_ready(ctx, inputs) and reached_all and trained_all
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
        if popup_guard.guard_and_recover(ctx.logger):
            return {}
        HomeScreen(ctx.ui_manager).collect_resources()
        return {}


@register("find_match")
class FindMatch(BlockSpec):
    label = "Find Match"
    category = "CoC"
    # description: see blocks/__init__.py DESCRIPTIONS (single source of copy).
    inputs = [
        Param("min_gold", Kind.Number, default=0, label="Min gold"),
        Param("min_elixir", Kind.Number, default=0, label="Min elixir"),
        Param("min_dark_elixir", Kind.Number, default=0, label="Min dark elixir"),
        Param("scout_delay", Kind.Number, default=1.0, label="Scout settle (s)"),
    ]
    outputs = [Port("found", Kind.Bool)]

    def run(self, ctx, inputs):
        # Sub-task guard: the loot scan must not run on a popup-covered screen.
        if popup_guard.guard_and_recover(ctx.logger):
            ctx.vars["match_found"] = False
            return {"found": False}
        # The zoom guarantee: never tap Attack on a non-max-zoomed village
        # (zooms right here when the session flag is not valid).
        ensure_village_zoom(ctx)
        # Block params override the loot thresholds in settings.json's "farm"
        # section (the screens layer reads them from there). A param that's absent
        # (old graph saved before these fields existed) leaves the settings value
        # intact; a present param — including 0 — wins.
        farm = dict(ctx.settings.get("farm", {}))
        for key in ("min_gold", "min_elixir", "min_dark_elixir"):
            v = inputs.get(key)
            if v is None or v == "":
                continue
            try:
                farm[key] = int(v)
            except (TypeError, ValueError):
                ctx.logger.warning("[find_match] ignoring non-numeric %s=%r", key, v)
        attack = dict(ctx.settings.get("attack", {}))
        sd = inputs.get("scout_delay")
        if sd not in (None, ""):
            try:
                attack["scout_settle"] = max(0.0, float(sd))
            except (TypeError, ValueError):
                ctx.logger.warning("[find_match] ignoring non-numeric scout_delay=%r", sd)
        settings = {**ctx.settings, "farm": farm, "attack": attack}
        ctx.logger.info(
            "[find_match] loot thresholds gold>=%s elixir>=%s dark>=%s",
            farm.get("min_gold", 0), farm.get("min_elixir", 0), farm.get("min_dark_elixir", 0),
        )
        found = AttackScreen(ctx.ui_manager, settings).find_match()
        ctx.vars["match_found"] = bool(found)
        return {"found": bool(found)}


@register("deploy")
class Deploy(BlockSpec):
    label = "Deploy Troops"
    category = "CoC"
    # Empty scenario -> use settings active_scenario (AttackScreen.deploy path).
    # A scenario name -> run that migrated scenario (data/scenarios/<name>.json).
    inputs = [
        Param("scenario", Kind.Text, default="", source="scenarios"),
        Param("selection", Kind.Text, default="random", choices=["random", "rotate"],
              label="Variant selection"),
        Param("zoom_out", Kind.Bool, default=True, label="Zoom out (max, centered)"),
        Param("tap_interval", Kind.Number, default=0,
              label="Tap interval (s)"),  # 0 = burst (pattern nodes); spell
        # nodes declare their own interval in the scenario JSON
        Param("select_delay", Kind.Number, default=0.2, label="Select delay (s)"),
        Param("humanize", Kind.Bool, default=True, label="Humanize drops"),
    ]
    outputs = [Port("deployed", Kind.Bool)]

    def run(self, ctx, inputs):
        # Sub-task guard: never deploy through a popup or right after a
        # mid-deploy relaunch — abort and let the next cycle redo the attack.
        if popup_guard.guard_and_recover(ctx.logger):
            ctx.vars["match_found"] = False
            return {"deployed": False}
        if not ctx.vars.get("match_found"):
            ctx.logger.info("[deploy] no match held — skipping (match_found is false).")
            return {"deployed": False}

        scenario = (ctx.vars.get("mv_scenario") if ctx.vars else None) or (inputs.get("scenario") or "").strip()
        if not scenario:
            deployed = AttackScreen(ctx.ui_manager, ctx.settings).deploy()
            return {"deployed": bool(deployed)}

        # Scenario path: wait for battle, pick a variant, run the same deploy bar
        # logic (BattleScreen.deploy_troops -> _slot_deploy) for parity.
        battle = BattleScreen(ctx.ui_manager)
        if not battle.wait_until_entered(timeout=15):
            ctx.logger.warning("[deploy] battle screen not detected — bailing.")
            return {"deployed": False}
        # The battle inherits the village zoom (set once per session by
        # ensure_home's host-wheel zoom) — no zoom here, so the user's
        # foreground window is never touched during deployment.
        doc = scenario_store.load_scenario(scenario)
        # Reuse the variant ensure_troops trained for (set in ctx.vars); fall back
        # to a fresh pick if it ran without ensure_troops (weighted-random, or
        # round-robin when selection="rotate").
        nodes, variant_name = scenario_store.variant_nodes_by_name(
            doc, ctx.vars.get("chosen_variant"),
            selection=(inputs.get("selection") or "random"))
        deploy_cfg = dict(ctx.settings.get("attack", {}).get("deploy", {}))
        deploy_cfg["nodes"] = nodes
        deploy_cfg["variant"] = variant_name
        # Pattern deploy: the variant's calibrated base centre steers the
        # outward humanize jitter — data from the scenario, never code.
        centre = None
        for v in doc.get("variants", []):
            if v.get("name") == variant_name:
                centre = (v.get("calibration") or {}).get("centre")
                break
        if centre:
            deploy_cfg["base_centre"] = list(centre)
        # Deploy-speed overrides (present param wins; absent keeps settings/defaults).
        for key in ("tap_interval", "select_delay"):
            v = inputs.get(key)
            if v is None or v == "":
                continue
            try:
                deploy_cfg[key] = max(0.0, float(v))
            except (TypeError, ValueError):
                ctx.logger.warning("[deploy] ignoring non-numeric %s=%r", key, v)
        if "humanize" in inputs and inputs.get("humanize") is not None:
            deploy_cfg["humanize"] = bool(inputs.get("humanize"))
        ctx.logger.info("[deploy] scenario=%s variant=%s nodes=%d tap=%.3fs select=%.3fs",
                        scenario, variant_name, len(nodes),
                        deploy_cfg.get("tap_interval", 0.15), deploy_cfg.get("select_delay", 0.3))
        battle.deploy_troops(deploy_cfg)
        return {"deployed": True}


@register("return_home")
class ReturnHome(BlockSpec):
    label = "Return Home"
    category = "CoC"
    inputs = [Param("settle_delay", Kind.Number, default=3, label="Settle delay (s)")]
    outputs = [Port("home", Kind.Bool)]

    def run(self, ctx, inputs):
        home = HomeScreen(ctx.ui_manager)
        # Sub-task guard: recover + abort — the battle-end wait must not run
        # while the game is being relaunched under us.
        if popup_guard.guard_and_recover(ctx.logger):
            ctx.vars["home"] = False
            return {"home": False}
        if not ctx.vars.get("match_found"):
            ctx.logger.info("[return_home] no match held — skipping.")
            # nothing was attacked; just report where we actually are
            ctx.vars["home"] = home.is_current_screen()
            return {"home": ctx.vars["home"]}

        settings = ctx.settings
        v = inputs.get("settle_delay")
        if v not in (None, ""):
            try:
                attack = dict(ctx.settings.get("attack", {}))
                attack["return_settle"] = max(0.0, float(v))
                settings = {**ctx.settings, "attack": attack}
            except (TypeError, ValueError):
                ctx.logger.warning("[return_home] ignoring non-numeric settle_delay=%r", v)
        attack_ok = AttackScreen(ctx.ui_manager, settings).return_home()
        ok = self._ensure_back_home(ctx)
        # The village camera state after a battle is not trustworthy, so drop
        # the zoom-valid flag: the NEXT cycle re-establishes max zoom before
        # its Attack tap (ensure_home.settle, or find_match as the fallback).
        scenario_store.set_session_flag("village_zoomed", False)
        # TẦNG dừng có kiểm soát (design 2026-11-01): đếm chu kỳ attack liên
        # tiếp kết thúc bất thường; vượt MAX_NO_PROGRESS_RUNS -> dừng run SẠCH
        # (stop_event hợp tác + log lỗi rõ ràng) — KHÔNG tự restart app.
        abnormal = (not attack_ok) or (not ok)
        if abnormal:
            runs = int(ctx.vars.get("noprogress_runs", 0)) + 1
            ctx.vars["noprogress_runs"] = runs
            ctx.logger.warning(f"[NOPROGRESS] abnormal cycle {runs}/"
                               f"{MAX_NO_PROGRESS_RUNS} (battle timeout or no "
                               "confirmed village return).")
            if runs >= MAX_NO_PROGRESS_RUNS:
                # 2026-11-19 (user: a dead stop doing NOTHING is unacceptable —
                # the run must self-recover): 3 abnormal cycles -> FULL recovery
                # (force-restart the game into a known-clean state) and CONTINUE
                # the run; the counter resets so the next abnormal streak gets
                # its own recovery. The next cycle's ensure_home re-lands and
                # re-verifies home.
                ctx.logger.error(
                    f"[NOPROGRESS] {runs} consecutive cycles ended abnormally — "
                    "full recovery: restarting Clash of Clans and CONTINUING the "
                    "run (no manual Run press needed).")
                try:
                    popup_guard.boot_recovery()
                except Exception as e:
                    ctx.logger.warning(f"[NOPROGRESS] recovery restart failed ({e}) — "
                                       "the next cycle's ensure_home will retry.")
                ctx.vars["noprogress_runs"] = 0
                ctx.logger.info("[NOPROGRESS] recovery done — the next cycle "
                                "re-lands via ensure_home.")
        else:
            if ctx.vars.pop("noprogress_runs", None) is not None:
                ctx.logger.info("[NOPROGRESS] normal cycle — counter reset.")
            ctx.vars["noprogress_runs"] = 0
        ctx.vars["home"] = ok
        return {"home": ok}

    def _ensure_back_home(self, ctx, verify_timeout=25):
        """After the return attempt, CONFIRM we are on the village screen. If
        not (battle-end timeout, stuck popup, black screen...), restart the
        game immediately and confirm home once more — instead of letting the
        graph continue from an unknown state."""
        ui, dev = ctx.ui_manager, ctx.device
        home = HomeScreen(ui)

        def poll_home(timeout):
            deadline = time.time() + timeout
            while time.time() < deadline:
                if ctx.stopped():
                    return False
                screen = ui.get_screen()
                if screen is not None and popup_guard.treasure_chest_visible(screen):
                    ctx.logger.warning("[return_home] treasure chest overlay up — "
                                       "smashing the earned chest (no game restart).")
                    popup_guard.smash_treasure_chests()
                    continue
                if home.is_current_screen():
                    return True
                home.close_popups()
                ui._poll_sleep(2)
            return False

        if poll_home(verify_timeout):
            ctx.logger.info("[return_home] back on the home screen.")
            return True
        # 2026-11-19 (user: restart-through-the-chest-overlay was wasteful — the
        # battle just EARNED a chest and the treasure-event overlay pops right
        # over the village after the attack): when the overlay is up, SMASH the
        # chest in place and re-check home — NEVER restart the game through it.
        # The overlay is detected by its Skip anchor, which is tool-agnostic:
        # it works whether the event shows the hammer OR the rolling pin, so no
        # per-tool templates are needed here.
        screen = ui.get_screen()
        if screen is not None and popup_guard.treasure_chest_visible(screen):
            ctx.logger.warning("[return_home] treasure chest overlay is up — smashing "
                               "the earned chest instead of restarting the game.")
            popup_guard.smash_treasure_chests()
            if poll_home(verify_timeout):
                ctx.logger.info("[return_home] back on the home screen (post-smash).")
                return True
        # 2026-11-19: a JUST-restarted game needs longer than verify_timeout to
        # load — restarting again mid-load only compounds the stall (the
        # 3-abnormal cascade: battle timeout -> cleanup restart -> return_home
        # restart 15s later -> still loading -> "could not reach home").
        if popup_guard.recent_recovery(seconds=90) and poll_home(90):
            ctx.logger.info("[return_home] home reached after the recent restart "
                            "(extended poll).")
            return True
        ctx.logger.warning("[return_home] NOT back on the village after return — restarting game.")
        if dev.restart_game(COC_PACKAGE):
            ui._poll_sleep(15)
            if poll_home(60):
                ctx.logger.info("[return_home] home reached after restart.")
                return True
        ctx.logger.error("[return_home] could not reach home even after restart.")
        return False


@register("treasure_event")
class TreasureEvent(BlockSpec):
    """If the Treasure event banner is active (hammer OR rolling-pin icon on
    the bottom banner strip — the event alternates the banner art), tap the
    chest open (4 taps) and press Return Home — a
    silent no-op when the event is not running (Simplicity treasure_event).
    Place after return_home in the farm cycle."""
    label = "Treasure Event"
    category = "CoC"
    inputs = []
    outputs = []

    def run(self, ctx, inputs):
        popup_guard.treasure_event()
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
