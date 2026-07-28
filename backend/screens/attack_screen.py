from .base_screen import BaseScreen
from .battle_screen import BattleScreen, EXIT_BATTLE_TEMPLATES
from .loot import LootReader
import logging
import random

logger = logging.getLogger(__name__)

MAX_SKIP = 50

FIND_A_MATCH_TEMPLATES = (
    "buttons/attack/btn_find_a_match_1",
    "buttons/attack/btn_find_a_match_2",
)
NEXT_ENEMY_TEMPLATES = (
    "buttons/attack/btn_next_enemy",
)
START_MATCH_TEMPLATES = (
    "buttons/attack/btn_start_match",
    "buttons/attack/btn_attack_now",
)
FIND_A_MATCH_THRESHOLD = 0.65


class AttackScreen(BaseScreen):
    """Owns the attack flow: match finding (scout → loot check → skip/accept),
    deploy, and return home. Loot OCR internals live in ``screens/loot.py``
    (``LootReader``); this class only decides from the numbers it returns."""

    def __init__(self, ui_manager, settings):
        super().__init__(ui_manager)
        self.settings = settings
        self._loot_reader = LootReader()

    def is_current_screen(self):
        matches = self.ui_manager.scan_all(FIND_A_MATCH_TEMPLATES)
        return any(matches.values())

    def _request_clan_troops(self):
        # If an uncollected "Full" bubble covers the request button, collect it first
        self.ui_manager.click(301, 340)
        self.ui_manager._poll_sleep(0.4)

        if not self._tap_if_found(["buttons/attack/btn_request"]):
            logger.warning("Request button not found.")
            return
        self.ui_manager._poll_sleep(1)

        if not self._tap_if_found(["buttons/attack/btn_send"]):
            logger.warning("Send button not found.")
            self.close_popups()
            return
        self.ui_manager._poll_sleep(1.5)
        logger.info("Clan troops requested.")
        self.close_popups()

    def run_attack_cycle(self):
        self.find_match()
        self.deploy()
        self.return_home()

    def find_match(self):
        attack_cfg = self.settings.get("attack", {})
        farm = self.settings.get("farm", {})

        if not self._wait_until_appears("buttons/attack/btn_attack", timeout=10):
            logger.error("Attack button not found.")
            return False
        self.ui_manager.click(1505, 27)
        self.ui_manager._poll_sleep(2)
        loc = self._wait_until_any_appears(
            FIND_A_MATCH_TEMPLATES,
            timeout=12,
            validator=self._is_find_match_loc_valid,
        )
        if not loc:
            logger.error("Find a Match button not found.")
            return False
        self.ui_manager.click(*loc)
        self.ui_manager._poll_sleep(3)
        # Shield guard: tap only when the confirmation is actually visible
        self._tap_if_found(["buttons/attack/btn_okay"])
        self._tap_start_match_attack()

        skipped = 0
        while skipped <= MAX_SKIP:
            if self.ui_manager._stopped():
                logger.warning("Stop requested during match finding.")
                return False
            # Wait for either the loot panel (a base to judge) or Next
            # (matchmaking finding one). Cap the wait so a lost session /
            # reconnection popup can't hang the loop forever.
            scout_loc = self._wait_until_any_appears(NEXT_ENEMY_TEMPLATES, timeout=30)
            if not scout_loc:
                logger.error("Scout screen not detected — bailing out.")
                self._bail()
                return False

            screen = self.ui_manager.get_screen()
            if screen is None:
                return False
            loot, conf = self._loot_reader.read(screen, attack_cfg)
            logger.info(f"[LOOT] gold={loot['gold']} ({conf['gold']:.2f}) "
                        f"elixir={loot['elixir']} ({conf['elixir']:.2f}) "
                        f"de={loot['dark_elixir']} ({conf['dark_elixir']:.2f})")
            if self._meets_threshold(loot, farm):
                logger.info("[LOOT] Target accepted.")
                return True

            skipped += 1
            self.ui_manager.click(*scout_loc)
            self.ui_manager._poll_sleep(3)

        logger.error(f"Max skips ({MAX_SKIP}) reached.")
        return False

    def deploy(self):
        battle = BattleScreen(self.ui_manager)
        if not battle.wait_until_entered():
            self.return_home()
            return
        attack_cfg = self.settings.get("attack", {})
        deploy_cfg = attack_cfg.get("deploy", {})
        scenario_name = deploy_cfg.get("scenario") or deploy_cfg.get("plan")
        if scenario_name:
            from core.scenario import load_scenario
            logger.info(f"[DEPLOY] Loading scenario: {scenario_name}")
            deploy_cfg = load_scenario(scenario_name, fallback=deploy_cfg)
        else:
            logger.info("[DEPLOY] No scenario selected — using default config.")
        if deploy_cfg.get("enabled", True):
            try:
                battle.deploy_troops(deploy_cfg)
            except Exception as e:
                logger.error(f"[DEPLOY] Failed: {e} — bailing out of battle.")
                battle.bail()
                return
        battle.wait_for_end()

    def return_home(self):
        battle = BattleScreen(self.ui_manager)
        if battle.tap_return_home():
            logger.info("Returned to base.")
        else:
            self.close_popups()

    def _read_loot(self, screen, attack_cfg):
        return self._loot_reader.read(screen, attack_cfg)

    def _meets_threshold(self, loot, farm):
        use_or = farm.get("logic_or", False)
        checks = [
            loot["gold"] >= farm.get("min_gold", 200000),
            loot["elixir"] >= farm.get("min_elixir", 200000),
            loot["dark_elixir"] >= farm.get("min_dark_elixir", 0),
        ]
        return any(checks) if use_or else all(checks)

    def _tap_start_match_attack(self):
        """Multiplayer matchmaking can show an extra Attack! confirmation."""
        self._tap_if_found(START_MATCH_TEMPLATES)

    def _bail(self):
        """Best-effort recovery: tap Return Home if reachable, then close popups."""
        self.bail_via_exit_buttons(EXIT_BATTLE_TEMPLATES)

    def _is_find_match_loc_valid(self, loc):
        x, y = loc
        return x >= 200 and y >= 600

    def _is_next_enemy_loc_valid(self, loc):
        x, y = loc
        return x >= 1200 and y >= 700
