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
# ``panel`` must land inside the section's CONTENT frame (the box right of the
# count, e.g. "0/11"); tapping it opens that section's bright add-roster. The
# left edge near the "Tap to edit" label does NOT reliably trigger it, so use the
# frame centre (this bit the spell section, which is empty in the normal farm
# flow — the previous army was just consumed — and so can't be opened via clear).
SECTIONS = {
    "troop": {"panel": (1100, 290), "trash": (1544, 209)},
    "spell": {"panel": (1072, 470), "trash": (1223, 431)},
    "siege": {"panel": (1420, 478), "trash": (1544, 431)},
}

# Roster scroll: swipe HORIZONTALLY within the bottom palette to reveal
# off-screen units (the roster is a single long horizontal strip). Enough scrolls
# to reach units far down the strip — e.g. super troops sit well past the regular
# troops, so a handful of swipes never reached them.
ROSTER_SWIPE = ((1250, 790), (650, 790))
MAX_ROSTER_SCROLLS = 12

# Empty spot to tap to collapse an open add-roster (above the palette, clear of
# every section box and button). Returns to the My Army overview without leaving
# the army screen.
ROSTER_CLOSE_TAP = (800, 130)


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
        self._roster_offset = 0   # freshly opened roster sits at its start
        self.ui_manager._poll_sleep(0.8)

    def close_roster(self):
        """Collapse an open add-roster by tapping an empty spot on the army screen.

        The bright bottom roster is dismissed by tapping outside any section box
        or the palette (not via the menu X, which scrolls out of view once a
        roster pushes the menu up). This returns us to the My Army overview while
        STAYING on the army screen, so the next section's panel opens cleanly —
        switching sections in place was otherwise flaky because the previous
        roster stayed open. Verified on device: tap-outside collapses the roster
        and each section's face then matches ~1.0 (archer/rage/log_launcher)."""
        self.ui_manager.click(*ROSTER_CLOSE_TAP)
        self.ui_manager._poll_sleep(0.6)

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

    def train_unit(self, roster_template, count, tap_delay=0.2, threshold=0.7,
                   fallback_template=None):
        """Find a troop's face in the bright roster and tap it ``count`` times.

        ``roster_template`` is a ``units/roster/<name>`` face template. When that
        face hasn't been captured, fall back to ``fallback_template`` — the
        deploy asset (``units/<folder>/<name>``) — so the roster is still
        scrolled and matched against the original icon instead of bailing with
        no scroll at all. The deploy asset carries count/level badges and a
        different render, so it matches the bright roster less cleanly; we hold the
        SAME threshold for it (NOT a lenient one) — lowering it just lets a badged
        icon false-match a different troop on the first screen and tap that,
        never scrolling to the real unit. If the fallback can't clear the bar the
        whole strip is scrolled and "not found" is reported, which is the signal
        to capture a dedicated roster face. Returns the number of taps issued.
        """
        count = int(count)
        name = roster_template.rsplit("/", 1)[-1]
        if count <= 0:
            return 0

        template, thr = roster_template, threshold
        if template not in vision.cache:
            if fallback_template and fallback_template in vision.cache:
                # Badged deploy icon vs the roster's face render is ambiguous, so a
                # LOOSE threshold false-matches a wrong troop on the first screen and
                # stops there (never scrolling). Demand a STRICT match instead: the
                # first screen won't clear it, so the whole strip is scrolled, and we
                # only tap on a confident hit (else not-found -> capture a roster face).
                logger.info("[TRAIN] no roster face %s — fallback to deploy asset %s at a strict "
                            "threshold (will scroll the strip; capture a roster face if it misses).",
                            roster_template, fallback_template)
                template, thr = fallback_template, max(threshold, 0.8)
            else:
                logger.warning("[TRAIN] no face template %s (no deploy asset to fall back on) "
                               "— capture it via the Assets tab.", roster_template)
                return 0

        loc = self._locate_in_roster(template, thr)
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
        """find_template the troop; scroll the roster up to MAX_ROSTER_SCROLLS if missing.

        Each unit in a section is searched by a separate call, so the strip may be
        scrolled FORWARD from finding a previous (later) unit — which leaves an
        earlier unit off-screen behind us. Rewind to the strip's start first
        (undoing the swipes we've tracked), then scan forward, so every search
        starts from the front regardless of pick order.
        """
        self._rewind_roster()
        for attempt in range(MAX_ROSTER_SCROLLS + 1):
            screen = self.ui_manager.get_screen()
            if screen is not None:
                loc = vision.find_template(screen, roster_template, threshold=threshold, use_orb_fallback=False)
                if loc:
                    return loc
            if attempt < MAX_ROSTER_SCROLLS and not self.ui_manager._stopped():
                (sx, sy), (ex, ey) = ROSTER_SWIPE
                self.ui_manager.device.swipe([(sx, sy), (ex, ey)])
                self._roster_offset = getattr(self, "_roster_offset", 0) + 1
                self.ui_manager._poll_sleep(0.8)
        return None

    def _rewind_roster(self):
        """Scroll the roster back to its start, reversing the forward swipes taken
        for a previous unit so the next search begins from the front."""
        n = getattr(self, "_roster_offset", 0)
        if n <= 0:
            return
        (sx, sy), (ex, ey) = ROSTER_SWIPE
        for _ in range(n):
            if self.ui_manager._stopped():
                break
            self.ui_manager.device.swipe([(ex, ey), (sx, sy)])   # reversed = scroll back
            self.ui_manager._poll_sleep(0.8)
        self._roster_offset = 0

    def back_home(self, max_taps=4):
        """Leave the army screen back to the village.

        The army screen + an open add-roster are two stacked layers, so a single
        X doesn't always reach home (this stranded the siege re-entry: after
        training spells we were still on the army screen and Train Troops wasn't
        visible). Tap the close X until the army screen is gone, then clear any
        leftover popups.
        """
        for _ in range(max_taps):
            if not self.is_current_screen():
                break
            loc = self._wait_until_any_appears(
                ("buttons/popup/btn_close",), timeout=2, silent=True, use_orb_fallback=False
            )
            if loc:
                self.ui_manager.click(*loc)
            self.ui_manager._poll_sleep(0.8)
        self.close_popups()
