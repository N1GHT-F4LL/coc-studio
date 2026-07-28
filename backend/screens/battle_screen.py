from .base_screen import BaseScreen
from .deploy import TroopDeployer
from core.vision import vision
import logging
import time
import cv2

logger = logging.getLogger(__name__)

BATTLE_TIMEOUT = 180          # max seconds to wait for battle to end

BATTLE_ANCHORS = (
    "icons/battle/battlefield",
    "icons/battle/battle_loading",
    "buttons/battle/btn_surrender",
)
RETURN_HOME_TEMPLATES = (
    "buttons/battle/btn_return_home",
    "buttons/attack/btn_return_home",
    "buttons/train/btn_return_home",
)
EXIT_BATTLE_TEMPLATES = RETURN_HOME_TEMPLATES + (
    "buttons/battle/btn_end_battle",
)
SURRENDER_BUTTONS = (
    "buttons/battle/btn_surrender",
    "buttons/battle/btn_end_battle",
)
SURRENDER_CONFIRMS = (
    "buttons/battle/btn_okay",
    "buttons/common/btn_okay",
)


class BattleScreen(BaseScreen):
    """Owns the battle lifecycle: detect entry, wait for end, surrender, bail,
    return home. The deploy phase (troop bar matching + drop strategies) is
    delegated to ``TroopDeployer`` in ``screens/deploy.py`` — the public
    ``deploy_troops`` / ``dump_remaining`` API is unchanged."""

    def __init__(self, ui_manager):
        super().__init__(ui_manager)
        self._deployer = TroopDeployer(ui_manager, surrender_fn=self.surrender)

    def is_current_screen(self):
        matches = self.ui_manager.scan_all(BATTLE_ANCHORS)
        return any(matches.values())

    def wait_until_entered(self, timeout=15):
        start = time.time()
        while time.time() - start < timeout:
            if self.is_current_screen():
                logger.info("Entered battle screen.")
                return True
            time.sleep(0.5)
        logger.warning("Battle screen not detected.")
        return False

    def deploy_troops(self, deploy_cfg):
        if not self._deployer.deploy_slots(deploy_cfg):
            logger.warning("[DEPLOY] No troop slots matched — skipping deploy.")

    def dump_remaining(self, deploy_cfg, drop_points=None, max_rounds=4, taps_per_slot=6):
        return self._deployer.dump_remaining(
            deploy_cfg, drop_points=drop_points, max_rounds=max_rounds, taps_per_slot=taps_per_slot,
        )

    def wait_for_end(self, timeout=BATTLE_TIMEOUT):
        start = time.time()
        while time.time() - start < timeout:
            if self.ui_manager._stopped():
                logger.warning("Stop requested while waiting for battle end.")
                return False
            screen = self.ui_manager.get_screen()
            if screen is None:
                return False
            for key in RETURN_HOME_TEMPLATES:
                if key in vision.cache and vision.find_template(screen, key, threshold=0.7, use_orb_fallback=False):
                    logger.info("Battle ended — Return Home detected.")
                    return True
            self.ui_manager._poll_sleep(2)
        logger.warning("Battle did not finish within timeout.")
        return False

    def tap_return_home(self):
        if self._tap_any(RETURN_HOME_TEMPLATES):
            time.sleep(5)
            return True
        return False

    def surrender(self, return_home=True):
        """End the fight: tap Surrender/End Battle, confirm with OK, then (if
        asked) tap Return Home. Called mid-deploy by the scenario's surrender
        node to stop the fight early (e.g. after loot is taken), and as an
        escape hatch when the match drags on. Every tap is conditional — a
        missing button just logs and moves on."""
        if self._tap_any(SURRENDER_BUTTONS):
            logger.info("[BATTLE] Surrender tapped.")
            time.sleep(0.8)
        else:
            logger.warning("[BATTLE] surrender: no Surrender/End Battle button found.")

        if self._wait_for_best_confirm(SURRENDER_CONFIRMS, timeout=3):
            logger.info("[BATTLE] Surrender confirmed.")
            time.sleep(1.5)
        else:
            logger.warning("[BATTLE] surrender: no confirmation button found.")

        if return_home:
            self.tap_return_home()

    def _wait_for_best_confirm(self, candidates, timeout=3):
        """Poll for the surrender-confirm dialog and tap the STRONGEST visible
        OK. Both OK templates can match at once (they overlap visually); picking
        by best match-score avoids tapping the wrong one, and re-checking each
        iteration handles the dialog appearing a moment after Surrender."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.ui_manager._stopped():
                return False
            screen = self.ui_manager.get_screen()
            if screen is None:
                return False
            gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
            best = None  # (score, cx, cy)
            for key in candidates:
                tpl = vision.cache.get(key)
                if tpl is None:
                    continue
                score, scaled, result_map = vision._find_best_scale(
                    gray, tpl, threshold=0.6, scales=(0.8, 0.9, 1.0, 1.1, 1.2),
                )
                if result_map is None or scaled is None:
                    continue
                _, _, _, max_loc = cv2.minMaxLoc(result_map)
                th, tw = scaled.shape[:2]
                cx, cy = int(max_loc[0] + tw // 2), int(max_loc[1] + th // 2)
                if best is None or score > best[0]:
                    best = (score, cx, cy)
            if best is not None:
                self.ui_manager.click(best[1], best[2])
                return True
            time.sleep(0.3)
        return False

    def bail(self):
        """Best-effort recovery after a broken find/deploy cycle: tap whichever
        exit button is reachable (Return Home preferred, End Battle as fallback),
        settle, then close popups. Used by deploy_troops's exception path."""
        self.bail_via_exit_buttons(EXIT_BATTLE_TEMPLATES, log_tag="battle ")
