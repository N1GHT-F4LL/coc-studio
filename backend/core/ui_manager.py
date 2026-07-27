import time
import os
import logging
from datetime import datetime
import cv2
from .vision import vision
from . import tap_debug

logger = logging.getLogger(__name__)

class UIManager:
    def __init__(self, humanize, device):
        self.humanize = humanize
        self.device = device
        self.stop_event = None  # set by run_bot; checked in all poll loops
        self.pause_event = None
        self.tap_debug_settings = None
        self.tap_debug_emit = None
        self._tap_debug_count = 0

    def configure_tap_debug(self, settings=None, emit=None):
        self.tap_debug_settings = settings
        self.tap_debug_emit = emit
        self._tap_debug_count = 0

    def _stopped(self):
        return self.stop_event is not None and self.stop_event.is_set()

    def _wait_if_paused(self):
        while (
            self.pause_event is not None
            and
            self.pause_event.is_set()
            and not self._stopped()
        ):
            if self.stop_event is not None:
                self.stop_event.wait(0.2)
            else:
                time.sleep(0.2)

    def _poll_sleep(self, seconds=0.5):
        """Sleep for `seconds`, but wake immediately if stop is requested."""
        self._wait_if_paused()
        if self.stop_event is not None:
            self.stop_event.wait(seconds)
        else:
            time.sleep(seconds)
        self._wait_if_paused()

    def wait_until_appears(self, template_name, timeout=5, silent=False, use_orb_fallback=True, threshold=0.7):
        """Poll until template appears or timeout expires; returns (cx, cy) or None."""
        logger.debug(f"Waiting for '{template_name}'...")

        start = time.time()
        screen = None
        while time.time() - start < timeout:
            if self._stopped():
                return None
            self._wait_if_paused()
            screen = self.device.get_screen()
            if screen is None:
                self._poll_sleep()
                continue
            loc = vision.find_template(
                screen,
                template_name,
                threshold=threshold,
                use_orb_fallback=use_orb_fallback,
            )
            if loc:
                logger.debug(f"Found '{template_name}' at {loc} in {time.time() - start:.1f}s")
                return loc
            self._poll_sleep()

        if not silent:
            logger.warning(f"Timeout waiting for '{template_name}'")
        else:
            logger.debug(f"Timeout waiting for '{template_name}'")

        # Reuse the last captured frame — no extra screencap needed.
        try:
            if screen is not None:
                debug_dir = os.path.join('coc_bot', 'logs', 'debug')
                os.makedirs(debug_dir, exist_ok=True)
                ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                out_path = os.path.join(debug_dir, f"timeout_{template_name}_{ts}.png")
                cv2.imwrite(out_path, screen)
                logger.debug(f"Wrote debug screenshot: {out_path}")
        except Exception as e:
            logger.exception(f"Failed to write debug screenshot: {e}")
        return None

    def get_screen(self):
        self._wait_if_paused()
        return self.device.get_screen()

    def click(self, x, y, label=None, meta=None):
        self._wait_if_paused()
        jx, jy = self.humanize.get_jittered_coords(x, y)
        logger.debug(f"Tapping {jx}, {jy}")
        before = None
        after = None
        record_tap = (
            tap_debug.enabled(self.tap_debug_settings)
            and self._tap_debug_count < tap_debug.max_per_run(self.tap_debug_settings)
        )
        if record_tap:
            before = self.device.get_screen()
        self.device.tap(jx, jy)
        if record_tap:
            self._tap_debug_count += 1
            delay = tap_debug.after_delay(self.tap_debug_settings)
            if tap_debug.capture_after(self.tap_debug_settings):
                self._poll_sleep(delay)
                after = self.device.get_screen()
            path = tap_debug.save(
                before,
                requested=(x, y),
                actual=(jx, jy),
                label=label,
                settings=self.tap_debug_settings,
                after_frame=after,
                meta=meta,
            )
            if path and self.tap_debug_emit:
                self.tap_debug_emit({
                    "type": "log",
                    "level": "INFO",
                    "name": "tap_debug",
                    "msg": f"tap overlay: {path}",
                })

    def drag(self, x1, y1, x2, y2, duration_ms=350, label=None, meta=None):
        """Press-and-drag from (x1,y1) to (x2,y2). Uses humanized coords and
        records debug frames similarly to `click` when enabled.
        """
        self._wait_if_paused()
        sx, sy = self.humanize.get_jittered_coords(x1, y1)
        ex, ey = self.humanize.get_jittered_coords(x2, y2)
        logger.debug(f"Drag {sx},{sy} -> {ex},{ey} dur={duration_ms}ms")
        record_tap = (
            tap_debug.enabled(self.tap_debug_settings)
            and self._tap_debug_count < tap_debug.max_per_run(self.tap_debug_settings)
        )
        before = None
        after = None
        if record_tap:
            before = self.device.get_screen()
        # Use device.swipe to perform press+move+release; duration controls hold time.
        try:
            # For a simple two-point drag, device.swipe/_curved_swipe is sufficient.
            self.device.swipe([(sx, sy), (ex, ey)], duration_ms=duration_ms)
        except Exception:
            logger.exception("Drag failed")
        if record_tap:
            self._tap_debug_count += 1
            delay = tap_debug.after_delay(self.tap_debug_settings)
            if tap_debug.capture_after(self.tap_debug_settings):
                self._poll_sleep(delay)
                after = self.device.get_screen()
            path = tap_debug.save(
                before,
                requested=(x1, y1),
                actual=((sx, sy), (ex, ey)),
                label=label,
                settings=self.tap_debug_settings,
                after_frame=after,
                meta=meta,
            )
            if path and self.tap_debug_emit:
                self.tap_debug_emit({
                    "type": "log",
                    "level": "INFO",
                    "name": "tap_debug",
                    "msg": f"tap overlay: {path}",
                })

    def drag_multi(self, moves, duration_ms=350, label=None, meta=None):
        """Perform simultaneous drags.

        `moves` is a list of ((sx,sy),(ex,ey)) pairs. Emits debug frames similar
        to `drag` when enabled.
        """
        self._wait_if_paused()
        record_tap = (
            tap_debug.enabled(self.tap_debug_settings)
            and self._tap_debug_count < tap_debug.max_per_run(self.tap_debug_settings)
        )
        before = None
        after = None
        if record_tap:
            before = self.device.get_screen()
        # Humanize each end/start coordinate
        # Determine if moves are endpoint pairs or full per-finger path lists
        # If each entry is a list of points -> use multi_touch_swipe_paths
        is_path_mode = False
        if moves and isinstance(moves[0], (list, tuple)) and moves[0] and isinstance(moves[0][0], (list, tuple)):
            is_path_mode = True

        try:
            if is_path_mode:
                # moves is list of per-finger paths: each path is list of (x,y)
                paths = []
                for path in moves:
                    sampled = [self.humanize.get_jittered_coords(int(p[0]), int(p[1])) for p in path]
                    paths.append(sampled)
                self.device.multi_touch_swipe_paths(paths, duration_ms=duration_ms)
            else:
                pairs = []
                for (sx, sy), (ex, ey) in moves:
                    sxx, syy = self.humanize.get_jittered_coords(sx, sy)
                    exx, eyy = self.humanize.get_jittered_coords(ex, ey)
                    pairs.append(((sxx, syy), (exx, eyy)))
                self.device.multi_touch_swipe(pairs, duration_ms=duration_ms)
        except Exception:
            logger.exception("Multi-drag failed")
        if record_tap:
            self._tap_debug_count += 1
            delay = tap_debug.after_delay(self.tap_debug_settings)
            if tap_debug.capture_after(self.tap_debug_settings):
                self._poll_sleep(delay)
                after = self.device.get_screen()
            path = tap_debug.save(
                before,
                requested=[p for p in moves],
                actual=pairs,
                label=label,
                settings=self.tap_debug_settings,
                after_frame=after,
                meta=meta,
            )
            if path and self.tap_debug_emit:
                self.tap_debug_emit({
                    "type": "log",
                    "level": "INFO",
                    "name": "tap_debug",
                    "msg": f"tap overlay: {path}",
                })

    def click_if_exists_quick(self, template_name, timeout=0.3):
        """Quick click if element exists (for popup scanning with minimal wait)."""
        logger.debug(f"Quick checking if '{template_name}' exists...")
        loc = self.wait_until_appears(template_name, timeout=timeout, silent=True)
        if loc:
            self.click(loc[0], loc[1])
            return True
        return False

    def scan_all(self, template_names, use_orb_fallback=False, threshold=0.7):
        """Capture the screen once and find one instance of each template.

        Returns {name: (x, y)} for every template that matched. All templates
        are checked against the same single screenshot so the result reflects
        one consistent point in time.
        """
        screen = self.device.get_screen()
        if screen is None:
            return {}
        screen_gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        found = {}
        for name in template_names:
            loc = vision.find_template(screen_gray, name, threshold=threshold, use_orb_fallback=use_orb_fallback)
            if loc:
                found[name] = loc
        return found
