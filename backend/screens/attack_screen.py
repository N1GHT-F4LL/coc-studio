from .base_screen import BaseScreen
from .battle_screen import BattleScreen, EXIT_BATTLE_TEMPLATES
from .loot import LootReader
import logging
import random

logger = logging.getLogger(__name__)

# How many consecutive bases to skip before giving up the cycle.
MAX_SKIP = 50

FIND_A_MATCH_TEMPLATES = (
    "buttons/attack/btn_find_a_match",
)
NEXT_ENEMY_TEMPLATES = ("buttons/attack/btn_next_enemy",)
START_MATCH_TEMPLATES = ("buttons/attack/btn_attack",)
FIND_A_MATCH_THRESHOLD = 0.65

class AttackScreen(BaseScreen):
    def __init__(self, ui_manager, settings):
        super().__init__(ui_manager)
        self.settings = settings
        self._loot_reader = LootReader()

    def _read_loot(self, screen, attack_cfg):
        return self._loot_reader.read(screen, attack_cfg)

    def is_current_screen(self):
        found = self.ui_manager.scan_all(
            self._existing_templates(FIND_A_MATCH_TEMPLATES),
            use_orb_fallback=False,
        )
        return bool(found)

    def _request_clan_troops(self):
        avail = self.ui_manager.wait_until_appears(
            "buttons/attack/btn_request_clan_castle_available",
            timeout=3, silent=True, use_orb_fallback=False,
        )
        if avail:
            logger.info("Requesting clan troops from Clan Castle.")
            self.ui_manager.click(*avail)
            self.ui_manager._poll_sleep(1.0)
            self.close_popups()
            return
        unavail = self.ui_manager.wait_until_appears(
            "buttons/attack/btn_request_clan_castle_unavailable",
            timeout=2, silent=True, use_orb_fallback=False,
        )
        if unavail:
            logger.info("Clan Castle request on cooldown — skipping.")
        else:
            logger.info("Clan Castle appears full — skipping request.")

    def run_attack_cycle(self):
        """Full farm attack cycle: find match -> evaluate loot -> attack -> deploy -> return.

        Called from the main loop when on the home screen. Returns when back on the
        home screen (or after a bail-out recovery). A missing template is treated as
        "not ready" and the cycle exits cleanly without crashing the bot.

        Thin orchestrator over find_match/deploy/return_home — each of which is also
        exposed as a standalone block in coc-studio. Behaviour is identical to the
        original monolithic cycle: a falsy step short-circuits the rest (the old
        ``return`` after ``self._bail()``).
        """
        if not self.find_match():
            return
        if not self.deploy():
            return
        self.return_home()

    def find_match(self):
        """Steps 1–5: tap Attack -> Find a Match -> start match -> scout -> OCR/skip.

        Returns True once a base meeting the loot threshold is held (ready to
        deploy), or False after a bail-out recovery / when not ready.
        """
        farm = self.settings.get("farm", {})
        attack_cfg = self.settings.get("attack", {})
        # Correct game flow:
        # Home Attack -> Find a Match -> Attack! (start matchmaking) -> Scout -> OCR/Next.

        # --- step 1: tap the Attack! button on the home screen ---
        loc = self.ui_manager.wait_until_appears(
            "buttons/home/btn_attack",
            timeout=5,
            silent=True,
        )
        if not loc:
            logger.debug("Attack button not found; skipping attack cycle.")
            return False
        self.ui_manager.click(*loc)
        logger.info("Tapped Attack! button.")

        # --- step 2: wait for the Find a Match preparation screen ---
        loc = self._wait_until_any_appears(
            FIND_A_MATCH_TEMPLATES,
            timeout=15,
            threshold=FIND_A_MATCH_THRESHOLD,
            use_orb_fallback=False,
            validator=self._is_find_match_loc_valid,
        )
        if not loc:
            logger.warning("Find a Match button not found - bailing out of attack cycle.")
            self._bail()
            return False

        if self.settings.get("actions", {}).get("request_clan_troops", False):
            self._request_clan_troops()

        self.ui_manager.click(*loc)
        logger.info("Tapped Find a Match.")

        # Step 3: tap green Attack! button to start finding an opponent.
        if not self._tap_start_match_attack():
            logger.warning("Start-match Attack button not found after Find a Match - bailing.")
            self._bail()
            return False

        # Wait until matchmaking lands on a real opponent scout screen.
        scout_loc = self._wait_until_any_appears(
            NEXT_ENEMY_TEMPLATES,
            timeout=35,
            use_orb_fallback=False,
        )
        if not scout_loc:
            logger.warning("Scout screen not detected after Find a Match - bailing.")
            self._bail()
            return False
        skips = 0
        scout_settle = float(attack_cfg.get("scout_settle", 1.0))
        while skips <= MAX_SKIP:
            # Ensure scout UI has settled before OCR.
            self.ui_manager._poll_sleep(scout_settle)

            screen = self.ui_manager.get_screen()
            if screen is None:
                logger.warning("No screen after match load - bailing.")
                self._bail()
                return False

            # --- step 4: OCR the loot numbers ---
            loot, conf = self._read_loot(screen, attack_cfg)
            logger.info(
                f"Enemy loot  gold={loot['gold']:,} (c={conf['gold']:.2f})  "
                f"elixir={loot['elixir']:,} (c={conf['elixir']:.2f})  "
                f"dark={loot['dark_elixir']:,} (c={conf['dark_elixir']:.2f})"
            )

            # --- step 5: decide hold attack or skip base ---
            if self._meets_threshold(loot, farm):
                logger.info("Loot meets threshold - keeping this base and attacking.")
                break

            logger.info("Loot below threshold - skipping base.")
            loc = self._wait_until_any_appears(
                NEXT_ENEMY_TEMPLATES,
                timeout=5,
                use_orb_fallback=False,
                validator=self._is_next_enemy_loc_valid,
            )
            if not loc:
                logger.warning("Next button not found - bailing.")
                self._bail()
                return False
            self.ui_manager.click(*loc)
            logger.debug("Tapped Next Enemy.")
            ready = self._wait_until_any_appears(
                NEXT_ENEMY_TEMPLATES,
                timeout=20,
                silent=True,
                use_orb_fallback=False,
            )
            if not ready:
                logger.warning("Scout screen not ready after Next Enemy - bailing.")
                self._bail()
                return False
            skips += 1
        else:
            logger.warning(f"Reached max skips ({MAX_SKIP}) - bailing.")
            self._bail()
            return False

        return True

    def deploy(self):
        """Step 6: enter the battle, pick a scenario variant, deploy troops.

        Returns True after troops are deployed, or False after a bail-out when
        the battle screen never appears.
        """
        attack_cfg = self.settings.get("attack", {})
        # --- step 5: wait for battle screen, deploy troops, wait for end ---
        battle = BattleScreen(self.ui_manager)
        if not battle.wait_until_entered(timeout=15):
            logger.warning("Battle screen not detected after loot threshold — bailing.")
            self._bail()
            return False

        deploy_cfg = dict(attack_cfg.get("deploy", {}))
        active = deploy_cfg.get("active_scenario")
        if active:
            try:
                from core.scenario import load_scenario
                scenario = load_scenario(active)
                variants = scenario.get("variants") or [{"nodes": [{"id": "n0", "after": [], "delay": 0, "slots": scenario.get("slots", [])}]}]
                chosen = random.choices(variants, weights=[v.get("weight", 1) for v in variants])[0]
                # Backward compat: old variant with "slots" key instead of "nodes"
                if "slots" in chosen and "nodes" not in chosen:
                    chosen = dict(chosen)
                    chosen["nodes"] = [{"id": "n0", "after": [], "delay": 0, "slots": chosen.pop("slots")}]
                deploy_cfg["nodes"] = chosen.get("nodes", [])
                logger.info(f"[SCENARIO] Variant: {chosen.get('name', '?')}  weight={chosen.get('weight', 1)}  nodes={len(deploy_cfg['nodes'])}")
            except FileNotFoundError:
                logger.warning(f"[SCENARIO] '{active}.json' not found — using settings slots")
        battle.deploy_troops(deploy_cfg)
        return True

    def return_home(self):
        """Step 7: wait for battle end, tap Return Home, settle, close popups.

        Returns True on a clean return, or False after a bail-out when the
        battle-end button times out.
        """
        battle = BattleScreen(self.ui_manager)
        loc = battle.wait_for_end()
        if not loc:
            logger.warning("Battle end timeout.")
            battle.bail()
            return False

        battle.tap_return_home(loc)
        settle = float(self.settings.get("attack", {}).get("return_settle", 3))
        self.ui_manager._poll_sleep(settle)
        self.close_popups()
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _meets_threshold(self, loot, farm):
        return (
            loot["gold"] >= farm.get("min_gold", 0)
            and loot["elixir"] >= farm.get("min_elixir", 0)
            and loot["dark_elixir"] >= farm.get("min_dark_elixir", 0)
        )

    def _tap_start_match_attack(self):
        loc = self._wait_until_any_appears(
            START_MATCH_TEMPLATES,
            timeout=5,
            use_orb_fallback=False,
        )
        if not loc:
            return False
        self.ui_manager.click(*loc)
        return True

    def _bail(self):
        """Best-effort recovery: tap Return Home if visible, then close popups."""
        self.bail_via_exit_buttons(EXIT_BATTLE_TEMPLATES)

    def _is_find_match_loc_valid(self, loc):
        x, y = loc
        # Find a Match is expected in the lower-left panel area.
        return 100 <= x <= 700 and 520 <= y <= 860

    def _is_next_enemy_loc_valid(self, loc):
        x, y = loc
        # Next Enemy appears on the right side during scout screen.
        return 900 <= x <= 1595 and 280 <= y <= 860

