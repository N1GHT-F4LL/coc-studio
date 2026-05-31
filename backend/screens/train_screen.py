"""Army / training screen — NEW screen (not a verbatim coc-tools file).

Drives the home-village "Train Troops" army UI so the bot can train troops
manually, one icon at a time, to match a chosen deploy scenario. Mirrors the
HomeScreen/AttackScreen/BattleScreen pattern (subclass of BaseScreen, all
device interaction through ``ui_manager``) and reuses the exact
"find unit icon by its ``units/...`` template then tap it" mechanism from
``BattleScreen._slot_deploy`` — here the icons live in the army troop grid
instead of the in-battle deploy bar.

The army-UI templates below (tabs, screen anchors) do NOT ship with the repo
yet — only ``buttons/home/btn_train_troops`` exists. Capture the rest with the
Asset Studio and the methods light up automatically; until then they degrade
gracefully (open() assumes the tap worked; select_tab() assumes the Troops tab
is already active).
"""
import logging

from .base_screen import BaseScreen
from core.vision import vision

logger = logging.getLogger(__name__)

# Home-village button that opens the army screen (the only asset that exists today).
TRAIN_TROOPS_BUTTON = "buttons/home/btn_train_troops"

# Calibration targets — capture these to enable screen detection + tab switching.
ARMY_ANCHORS = (
    "buttons/army/army_screen",
    "buttons/army/btn_quick_train",
)
TAB_TEMPLATES = {
    "troops": ("buttons/army/btn_troops_tab",),
    "spells": ("buttons/army/btn_spells_tab",),
    "sieges": ("buttons/army/btn_sieges_tab",),
}
# Optional: a "not enough housing space" popup to stop tapping before over-training.
HOUSING_FULL_TEMPLATES = ("buttons/army/popup_not_enough_housing",)
# Buttons that take us back to the village from the army screen.
CLOSE_TEMPLATES = ("buttons/popup/btn_close", "buttons/army/btn_close")


class TrainScreen(BaseScreen):
    def is_current_screen(self):
        found = self.ui_manager.scan_all(
            self._existing_templates(ARMY_ANCHORS),
            use_orb_fallback=False,
        )
        return bool(found)

    def wait_until_entered(self, timeout=5):
        """Poll until the army UI is visible (only if anchors are calibrated)."""
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_current_screen():
                return True
            self.ui_manager._poll_sleep(0.5)
        return False

    def open(self, timeout=8):
        """From the home screen, tap Train Troops to open the army screen."""
        loc = self.ui_manager.wait_until_appears(TRAIN_TROOPS_BUTTON, timeout=timeout, silent=True)
        if not loc:
            logger.warning("[TRAIN] 'Train Troops' button not found on home screen.")
            return False
        self.ui_manager.click(*loc)
        self.ui_manager._poll_sleep(1.0)
        # Confirm only if anchors are calibrated; otherwise trust the tap.
        if any(a in vision.cache for a in ARMY_ANCHORS):
            if not self.wait_until_entered(timeout=5):
                logger.warning("[TRAIN] army screen anchor not detected after tap.")
                return False
        logger.info("[TRAIN] army screen opened.")
        return True

    def select_tab(self, tab="troops"):
        """Tap a tab (Troops/Spells/Sieges). No-op if the tab asset isn't captured."""
        loc = self._wait_until_any_appears(
            TAB_TEMPLATES.get(tab, ()), timeout=3, silent=True, use_orb_fallback=False
        )
        if loc:
            self.ui_manager.click(*loc)
            self.ui_manager._poll_sleep(0.5)
            return True
        return False

    def train_unit(self, template_key, count, tap_delay=0.2, threshold=0.55):
        """Locate a unit icon in the army grid and tap it ``count`` times.

        Each tap queues one unit. Returns the number of taps actually issued
        (fewer if stop was requested or the housing-full popup appeared).
        """
        count = int(count)
        name = template_key.rsplit("/", 1)[-1]
        if count <= 0:
            return 0
        screen = self.ui_manager.get_screen()
        if screen is None:
            logger.warning("[TRAIN] no screen — skipping %s", name)
            return 0
        # Same lookup contract as _slot_deploy: template_key -> vision.cache.
        loc = vision.find_template(
            screen, template_key, threshold=float(threshold), use_orb_fallback=False
        )
        if not loc:
            logger.warning("[TRAIN] icon not found: %s (conf < %.2f) — skipping", name, threshold)
            return 0

        cx, cy = loc
        done = 0
        for _ in range(count):
            if self.ui_manager._stopped():
                break
            # Stop early if the army is full (only when that popup asset is calibrated).
            if any(t in vision.cache for t in HOUSING_FULL_TEMPLATES):
                if self._wait_until_any_appears(
                    HOUSING_FULL_TEMPLATES, timeout=0.2, silent=True, use_orb_fallback=False
                ):
                    logger.info("[TRAIN] %s: army full — stopping at %d/%d", name, done, count)
                    self.close_popups()
                    break
            self.ui_manager.click(cx, cy)
            self.ui_manager._poll_sleep(tap_delay)
            done += 1
        logger.info("[TRAIN] %s ×%d (requested %d)", name, done, count)
        return done

    def back_home(self):
        """Return to the village: close any popup, tap a Close/X if present."""
        self.close_popups()
        loc = self._wait_until_any_appears(
            CLOSE_TEMPLATES, timeout=2, silent=True, use_orb_fallback=False
        )
        if loc:
            self.ui_manager.click(*loc)
            self.ui_manager._poll_sleep(0.6)
        self.close_popups()
