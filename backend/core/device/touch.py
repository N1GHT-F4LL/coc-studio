"""Touch/input mixin — taps, swipes, and multi-touch pinch via sendevent.

Owns everything about *injecting input*: simple ``input tap/swipe`` commands
and the raw sendevent multi-touch protocol used for pinch-zoom and curved
swipes. Split out of the former ``core/device.py`` god-module; behaviour
unchanged.
"""
import time
import logging

logger = logging.getLogger(__name__)


class TouchInputMixin:
    """Requires AdbTransportMixin (``_run_adb``) and DisplayMixin
    (``get_screen_size``)."""

    def _pixel_to_event(self, px, py, max_x_evt, max_y_evt, sw, sh):
        ex = max(0, min(max_x_evt, int(px * max_x_evt / sw)))
        ey = max(0, min(max_y_evt, int(py * max_y_evt / sh)))
        return ex, ey

    def _find_touch_input_device(self):
        """
        Find the multi-touch event device (e.g. /dev/input/event4 on BlueStacks).
        Returns (path, max_x, max_y) or (None, None, None).
        Looks for a device exposing ABS_MT_POSITION_X.
        """
        if not self.available or not self.connected:
            return (None, None, None)
        res = self._run_adb(['shell', 'getevent', '-pl'])
        if res is None or res.returncode != 0:
            return (None, None, None)
        current_path = None
        current_has_mt_x = False
        current_max_x = None
        current_max_y = None
        for line in (res.stdout or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("add device"):
                # Flush previous if it was MT-capable
                if current_path and current_has_mt_x:
                    return (current_path, current_max_x, current_max_y)
                # Start new device block
                parts = stripped.split(":", 1)
                current_path = parts[1].strip() if len(parts) > 1 else None
                current_has_mt_x = False
                current_max_x = None
                current_max_y = None
            elif "ABS_MT_POSITION_X" in stripped:
                current_has_mt_x = True
                # Parse max from "ABS_MT_POSITION_X     : value 0, min 0, max 32767, ..."
                try:
                    current_max_x = int(stripped.split("max")[1].split(",")[0].strip())
                except Exception:
                    current_max_x = None
            elif "ABS_MT_POSITION_Y" in stripped:
                try:
                    current_max_y = int(stripped.split("max")[1].split(",")[0].strip())
                except Exception:
                    current_max_y = None
        if current_path and current_has_mt_x:
            return (current_path, current_max_x, current_max_y)
        return (None, None, None)

    def pinch(self, direction='out', center=None, span_pixels=400, steps=15, repeats=1):
        """
        Multi-touch pinch via sendevent (Protocol A: two fingers separated by
        SYN_MT_REPORT, frames separated by SYN_REPORT). Used to zoom the CoC
        village in/out so collectors at the edges become visible.

        direction:    'out' fingers move toward center (zoom out),
                      'in'  fingers move apart from center (zoom in)
        center:       (x, y) pixel center; defaults to screen midpoint
        span_pixels:  far-finger distance from center (closer end = 1/4 of this)
        steps:        number of interpolated frames
        repeats:      consecutive pinches (each lifts fingers between). Useful
                      because CoC clamps zoom-out at a max level, so a few
                      repeats reliably hits the floor regardless of starting zoom.
        Returns True on success.
        """
        if not self.available or not self.connected:
            return False

        event_dev, max_x_evt, max_y_evt = self._find_touch_input_device()
        if not event_dev:
            logger.warning("No multi-touch input device found; cannot pinch.")
            return False

        size = self.get_screen_size()
        if not size:
            logger.warning("Cannot pinch: failed to read screen size.")
            return False
        sw, sh = size
        cx, cy = center or (sw // 2, sh // 2)

        # BlueStacks Virtual Touch and most MT devices use a normalized 0..max
        # coordinate space rather than raw pixels. Map accordingly.
        max_x_evt = max_x_evt or sw
        max_y_evt = max_y_evt or sh

        if direction == 'out':
            start_d, end_d = span_pixels, max(20, span_pixels // 5)
        else:
            start_d, end_d = max(20, span_pixels // 5), span_pixels

        EV_ABS = 3
        EV_SYN = 0
        ABS_MT_POSITION_X = 0x35
        ABS_MT_POSITION_Y = 0x36
        SYN_REPORT = 0
        SYN_MT_REPORT = 2

        def build_script():
            cmds = []
            def se(t, c, v):
                cmds.append(f"sendevent {event_dev} {t} {c} {v}")
            for i in range(steps + 1):
                t = i / max(1, steps)
                d = int(start_d + (end_d - start_d) * t)
                x1, y1 = self._pixel_to_event(cx - d, cy, max_x_evt, max_y_evt, sw, sh)
                x2, y2 = self._pixel_to_event(cx + d, cy, max_x_evt, max_y_evt, sw, sh)
                se(EV_ABS, ABS_MT_POSITION_X, x1)
                se(EV_ABS, ABS_MT_POSITION_Y, y1)
                se(EV_SYN, SYN_MT_REPORT, 0)
                se(EV_ABS, ABS_MT_POSITION_X, x2)
                se(EV_ABS, ABS_MT_POSITION_Y, y2)
                se(EV_SYN, SYN_MT_REPORT, 0)
                se(EV_SYN, SYN_REPORT, 0)
                cmds.append("sleep 0.04")
            # Lift all fingers: empty frame (no MT reports before SYN).
            se(EV_SYN, SYN_REPORT, 0)
            return ";".join(cmds)

        logger.info(
            f"Pinch {direction} x{repeats}: device={event_dev} center=({cx},{cy}) "
            f"span={start_d}->{end_d} steps={steps}"
        )
        script = build_script()
        for r in range(repeats):
            res = self._run_adb(['shell', script])
            if res is None or res.returncode != 0:
                logger.warning(f"Pinch sendevent script returned non-zero on repeat {r + 1}.")
                return False
            if r < repeats - 1:
                # Let CoC settle so the next pinch starts from a stable camera.
                time.sleep(0.3)
        return True

    def _curved_swipe(self, path, duration_ms=300):
        if not self.available or not self.connected:
            return False
        event_dev, max_x_evt, max_y_evt = self._find_touch_input_device()
        if not event_dev:
            return False
        size = self.get_screen_size()
        if not size:
            return False
        sw, sh = size
        max_x_evt = max_x_evt or sw
        max_y_evt = max_y_evt or sh

        EV_ABS, EV_SYN = 3, 0
        ABS_MT_POSITION_X, ABS_MT_POSITION_Y = 0x35, 0x36
        SYN_REPORT, SYN_MT_REPORT = 0, 2

        sleep_per = max(0.016, duration_ms / 1000 / max(1, len(path) - 1))
        cmds = []
        def se(t, c, v): cmds.append(f"sendevent {event_dev} {t} {c} {v}")

        for px, py in path:
            ex, ey = self._pixel_to_event(px, py, max_x_evt, max_y_evt, sw, sh)
            se(EV_ABS, ABS_MT_POSITION_X, ex)
            se(EV_ABS, ABS_MT_POSITION_Y, ey)
            se(EV_SYN, SYN_MT_REPORT, 0)
            se(EV_SYN, SYN_REPORT, 0)
            cmds.append(f"sleep {sleep_per:.3f}")
        se(EV_SYN, SYN_REPORT, 0)

        script = ";".join(cmds)
        res = self._run_adb(['shell', script])
        return res is not None and res.returncode == 0

    def tap(self, x, y):
        if not self.available or not self.connected:
            logger.debug("tap skipped: no active ADB device.")
            return
        try:
            self._run_adb(['shell', 'input', 'tap', str(x), str(y)])
        except FileNotFoundError:
            logger.error("adb binary not found when attempting to tap.")

    def swipe(self, path):
        if len(path) < 2:
            return
        if len(path) > 2 and self._curved_swipe(path):
            return
        start, end = path[0], path[-1]
        if not self.available or not self.connected:
            logger.debug("swipe skipped: no active ADB device.")
            return
        try:
            self._run_adb(['shell', 'input', 'swipe',
                           str(start[0]), str(start[1]),
                           str(end[0]), str(end[1]), '300'])
        except FileNotFoundError:
            logger.error("adb binary not found when attempting to swipe.")
