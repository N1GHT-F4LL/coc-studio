"""Army / training screen — NEW screen (not a verbatim coc-tools file).

Drives the home-village "Train Troops" army UI to train troops MANUALLY, one
icon at a time, to match a chosen deploy scenario. Subclass of BaseScreen; all
device interaction via ``ui_manager``.

Flow that was reverse-engineered on a live TH18 device (see scripts/*calib):
  1. tap home "Train Troops" -> the My Army screen opens.
  2. CLEAR the troops: tap the troops-section trash (``buttons/attack/btn_delete_troop``,
     the top-most of the 3 trash icons) -> confirm "Okay". Army troops go to 0/cap
     and the add-roster at the bottom becomes BRIGHT (addable).
  3. ADD each troop: the bright roster icons are matchable by a FACE-ONLY template
     (``units/roster/<name>``) -- crucially NOT the old ``units/troops/<name>`` asset,
     which carries the army-count/level badges and a different render and matches at
     only ~0.5. With a face crop from the bright roster, find_template peaks ~1.0 at
     the right tile (next-best ~0.65), so it localises reliably. Each tap adds one
     troop (1 tap = +1). If a troop isn't on screen, scroll the roster and retry.

Capture the ``units/roster/<name>`` face templates with scripts/capture_face.py.
"""
import logging

from .base_screen import BaseScreen
from core.vision import vision

logger = logging.getLogger(__name__)

TRAIN_TROOPS_BUTTON = "buttons/home/btn_train_troops"   # exists in assets
DELETE_TROOP_TEMPLATE = "buttons/attack/btn_delete_troop"  # exists; 1 per section

# The "Remove troops?" confirm dialog has no asset for its green Okay button, so
# we locate it by colour in the dialog band, with a measured fallback.
OKAY_FALLBACK = (973, 539)
OKAY_COLOUR_BAND = (470, 600, 760, 1180)  # y1,y2,x1,x2 to search for the green button

# Per-section coords (calibrated on a 1600x900 TH18 layout). Each section has a
# panel tap (opens its bright add-roster, "Tap to edit") and a trash button
# (clears that section). troop/spell/siege are the trainable sections.
SECTIONS = {
    "troop": {"panel": (1100, 290), "trash": (1544, 209)},
    "spell": {"panel": (935, 455), "trash": (1223, 431)},
    "siege": {"panel": (1420, 478), "trash": (1544, 431)},
}

# Roster scroll: swipe within the bottom palette to reveal off-screen units.
ROSTER_SWIPE = ((1400, 790), (300, 790))
MAX_ROSTER_SCROLLS = 5


class TrainScreen(BaseScreen):
    def is_current_screen(self):
        # The trash icons only exist on the army screen; any match => we're here.
        return bool(vision.find_all_matches(
            self.ui_manager.get_screen(), DELETE_TROOP_TEMPLATE, threshold=0.7
        )) if self.ui_manager.get_screen() is not None else False

    def open(self, timeout=8):
        """From the home screen, tap Train Troops to open the army screen.

        Robust to being left on the army screen from a previous section: if the
        home Train Troops button isn't visible, close back to home and retry once.
        """
        loc = self.ui_manager.wait_until_appears(TRAIN_TROOPS_BUTTON, timeout=timeout, silent=True)
        if not loc:
            self.back_home()
            self.ui_manager._poll_sleep(0.6)
            loc = self.ui_manager.wait_until_appears(TRAIN_TROOPS_BUTTON, timeout=timeout, silent=True)
        if not loc:
            logger.warning("[TRAIN] 'Train Troops' button not found on home screen.")
            return False
        self.ui_manager.click(*loc)
        self.ui_manager._poll_sleep(1.2)
        logger.info("[TRAIN] army screen opened.")
        return True

    def clear_section(self, kind):
        """Empty a section (troop/spell/siege) by tapping its trash + confirming.

        The trash only exists when the section has units; we tap the trash
        match nearest the section's known position, then confirm. No-op (returns
        False) if the section is already empty.
        """
        cfg = SECTIONS.get(kind)
        if not cfg:
            return False
        screen = self.ui_manager.get_screen()
        if screen is None:
            return False
        matches = vision.find_all_matches(screen, DELETE_TROOP_TEMPLATE, threshold=0.7, min_distance=30)
        if not matches:
            logger.info("[TRAIN] %s already empty (no trash).", kind)
            return False
        tx0, ty0 = cfg["trash"]
        tx, ty = min(matches, key=lambda p: (p[0] - tx0) ** 2 + (p[1] - ty0) ** 2)
        if (tx - tx0) ** 2 + (ty - ty0) ** 2 > 120 ** 2:
            logger.info("[TRAIN] %s trash not present — assuming empty.", kind)
            return False
        self.ui_manager.click(tx, ty)
        self.ui_manager._poll_sleep(0.8)
        self._tap_okay()
        self.ui_manager._poll_sleep(0.8)
        logger.info("[TRAIN] %s cleared.", kind)
        return True

    def open_roster(self, kind="troop"):
        """Tap a section panel ('Tap to edit') to reveal its bright add-roster."""
        cfg = SECTIONS.get(kind)
        if not cfg:
            return
        self.ui_manager.click(*cfg["panel"])
        self.ui_manager._poll_sleep(0.8)

    def _tap_okay(self):
        """Confirm the 'Remove troops?' dialog (green Okay, located by colour)."""
        loc = self._find_green_button() or OKAY_FALLBACK
        self.ui_manager.click(*loc)

    def _find_green_button(self):
        import numpy as np
        import cv2
        screen = self.ui_manager.get_screen()
        if screen is None:
            return None
        y1, y2, x1, x2 = OKAY_COLOUR_BAND
        hsv = cv2.cvtColor(screen[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (35, 80, 80), (85, 255, 255))
        ys, xs = np.where(mask > 0)
        if len(xs) < 500:
            return None
        return (int(xs.mean()) + x1, int(ys.mean()) + y1)

    def train_unit(self, roster_template, count, tap_delay=0.2, threshold=0.7):
        """Find a troop's face in the bright roster and tap it ``count`` times.

        ``roster_template`` is a ``units/roster/<name>`` face template. If the
        troop isn't visible, the roster is scrolled and the search retried.
        Returns the number of taps issued.
        """
        count = int(count)
        name = roster_template.rsplit("/", 1)[-1]
        if count <= 0:
            return 0
        if roster_template not in vision.cache:
            logger.warning("[TRAIN] no face template %s — capture it with scripts/capture_face.py", roster_template)
            return 0

        loc = self._locate_in_roster(roster_template, threshold)
        if not loc:
            logger.warning("[TRAIN] %s not found in roster after scrolling — skipping.", name)
            return 0

        cx, cy = loc
        done = 0
        for _ in range(count):
            if self.ui_manager._stopped():
                break
            self.ui_manager.click(cx, cy)
            self.ui_manager._poll_sleep(tap_delay)
            done += 1
        logger.info("[TRAIN] %s ×%d (requested %d) at (%d,%d)", name, done, count, cx, cy)
        return done

    def _locate_in_roster(self, roster_template, threshold):
        """find_template the troop; scroll the roster up to MAX_ROSTER_SCROLLS if missing."""
        for attempt in range(MAX_ROSTER_SCROLLS + 1):
            screen = self.ui_manager.get_screen()
            if screen is not None:
                loc = vision.find_template(screen, roster_template, threshold=threshold, use_orb_fallback=False)
                if loc:
                    return loc
            if attempt < MAX_ROSTER_SCROLLS and not self.ui_manager._stopped():
                (sx, sy), (ex, ey) = ROSTER_SWIPE
                self.ui_manager.device.swipe([(sx, sy), (ex, ey)])
                self.ui_manager._poll_sleep(0.8)
        return None

    def back_home(self):
        """Leave the army screen back to the village (tap the X / close popups)."""
        loc = self._wait_until_any_appears(
            ("buttons/popup/btn_close",), timeout=2, silent=True, use_orb_fallback=False
        )
        if loc:
            self.ui_manager.click(*loc)
            self.ui_manager._poll_sleep(0.8)
        self.close_popups()
