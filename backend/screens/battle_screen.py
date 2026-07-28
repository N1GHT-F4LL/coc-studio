from .base_screen import BaseScreen
from .deploy import TroopDeployer
from core.vision import vision
import logging
import time
import cv2

logger = logging.getLogger(__name__)

BATTLE_TIMEOUT = 180

# Anchors that appear at some point during the attack phase.
BATTLE_ANCHORS = (
    "buttons/battle/btn_end_battle",
    "buttons/battle/btn_surrender",
    "buttons/battle/btn_return_home",
)

RETURN_HOME_TEMPLATES = (
    "buttons/battle/btn_return_home",
)

# For bail/recovery paths: tap whichever exit button is reachable.
EXIT_BATTLE_TEMPLATES = (
    "buttons/battle/btn_return_home",
    "buttons/battle/btn_end_battle",
)

# The mid-battle bail button changes label by deploy state: a white-flag
# "Surrender" while troops are still being deployed, an "End Battle" once the
# whole army is down. They sit in the same spot and both quit the attack, so the
# surrender node accepts EITHER.
SURRENDER_BUTTONS = (
    "buttons/battle/btn_surrender",
    "buttons/battle/btn_end_battle",
)

# Confirm dialog after the bail button: an "are you sure you want to end the
# fight?" popup with Cancel + Okay. The clickable confirm is the green Okay
# button (``btn_surrender_confirm`` is a crop of the whole popup, not a button,
# so its centre lands on empty dialog space — don't tap that).
SURRENDER_CONFIRMS = (
    "buttons/battle/okay",
)

class BattleScreen(BaseScreen):
    def __init__(self, ui_manager):
        super().__init__(ui_manager)
        self._deployer = TroopDeployer(ui_manager, surrender_fn=self.surrender)

    def is_current_screen(self):
        found = self.ui_manager.scan_all(
            self._existing_templates(BATTLE_ANCHORS),
            use_orb_fallback=False,
        )
        return bool(found)

    def wait_until_entered(self, timeout=15):
        """Poll until the battle UI is visible (replaces blind sleep before deploy)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_current_screen():
                return True
            self.ui_manager._poll_sleep(0.5)
        return False

    def deploy_troops(self, deploy_cfg):
        if not self._deployer.deploy_slots(deploy_cfg):
            logger.warning("[DEPLOY] No troop slots matched — skipping deploy.")

    def dump_remaining(self, deploy_cfg, drop_points=None, max_rounds=4, taps_per_slot=6):
        return self._deployer.dump_remaining(
            deploy_cfg, drop_points=drop_points, max_rounds=max_rounds, taps_per_slot=taps_per_slot,
        )

    def wait_for_end(self, timeout=BATTLE_TIMEOUT):
        """Wait for a Return Home button and return its location, or None on timeout."""
        return self._wait_until_any_appears(
            RETURN_HOME_TEMPLATES,
            timeout=timeout,
            use_orb_fallback=False,
        )

    def tap_return_home(self, loc):
        self.ui_manager.click(*loc)
        logger.info("Tapped Return Home.")

    def surrender(self, return_home=True):
        """Give up the current attack: tap the surrender flag, confirm, then
        (optionally) return to the village once the loot screen appears.

        Backs the scenario ``surrender`` node — pair it with a ``delay`` node to
        deploy a few troops, wait, then bail out (e.g. quick resource raids).

        The bail button is a white-flag Surrender while troops are still being
        deployed and an End Battle once the army is fully down, so we accept
        either (``SURRENDER_BUTTONS``)."""
        flag = self._wait_until_any_appears(
            SURRENDER_BUTTONS, timeout=6, silent=True, use_orb_fallback=False)
        if not flag:
            logger.warning("[SURRENDER] no surrender/end-battle button found — battle may have already ended.")
        else:
            self.ui_manager.click(*flag)
            self.ui_manager._poll_sleep(0.6)
            # Both bail paths raise an "are you sure?" confirm (Surrender confirm
            # or the end-early Okay). Several confirm templates can partially
            # match the same dialog (both confirm buttons are green), so pick the
            # HIGHEST-confidence one rather than first-found — otherwise we tap the
            # wrong spot and the dialog stays up.
            confirm = self._wait_for_best_confirm(SURRENDER_CONFIRMS, timeout=4)
            if confirm:
                self.ui_manager.click(*confirm)
                logger.info("[SURRENDER] confirmed — tapped (%d,%d).", *confirm)
                self.ui_manager._poll_sleep(1.0)
            else:
                logger.info("[SURRENDER] no confirm dialog — continuing.")
        if return_home:
            loc = self.wait_for_end(timeout=20)
            if loc:
                self.tap_return_home(loc)
                self.ui_manager._poll_sleep(2)
            else:
                logger.warning("[SURRENDER] Return Home not seen after surrender.")
        return True

    def _wait_for_best_confirm(self, templates, timeout, threshold=0.7):
        """Poll for a confirm dialog and return the centre of the HIGHEST-
        confidence matching template.

        ``_wait_until_any_appears`` returns the first template that clears the
        threshold; when several confirm buttons look alike (two green buttons),
        a weak partial match can win and we tap the wrong spot. Scoring every
        candidate on each frame and taking the best makes the Okay button win on
        the End-Battle dialog and the Surrender confirm win on the white-flag
        dialog. Returns None if no candidate clears the threshold in time."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            screen = self.ui_manager.get_screen()
            if screen is not None:
                gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY) if screen.ndim == 3 else screen
                best = None  # (score, (cx, cy), key)
                for key in templates:
                    tpl = vision.cache.get(key)
                    if tpl is None:
                        continue
                    score, scaled, rmap = vision._find_best_scale(gray, tpl, threshold)
                    if rmap is None or scaled is None or score < threshold:
                        continue
                    _, _, _, max_loc = cv2.minMaxLoc(rmap)
                    bh, bw = scaled.shape[:2]
                    if best is None or score > best[0]:
                        best = (score, (int(max_loc[0] + bw // 2), int(max_loc[1] + bh // 2)), key)
                if best:
                    logger.info("[SURRENDER] confirm match %s conf=%.2f", best[2].rsplit("/", 1)[-1], best[0])
                    return best[1]
            self.ui_manager._poll_sleep(0.4)
        return None

    def bail(self):
        """Best-effort recovery: tap Return Home if visible, then close popups."""
        self.bail_via_exit_buttons(EXIT_BATTLE_TEMPLATES, log_tag="battle ")

