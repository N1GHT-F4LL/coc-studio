"""Display mixin — screen capture and resolution/density enforcement.

Owns everything about the device's *pixels*: screencap decoding, reading the
current ``wm size`` / ``wm density``, and locking the display to a known
geometry. Split out of the former ``core/device.py`` god-module; behaviour
unchanged.
"""
import subprocess
import time
import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class DisplayMixin:
    """Requires AdbTransportMixin (``_adb_cmd``, ``_run_adb``)."""

    def get_screen_size(self):
        """Return (width, height) reported by `wm size`. Prefers override over physical."""
        if not self.available or not self.connected:
            return None
        res = self._run_adb(['shell', 'wm', 'size'])
        if res is None or res.returncode != 0:
            return None
        text = res.stdout or ""
        # Override line takes precedence over Physical when both are present.
        for prefix in ("Override size:", "Physical size:"):
            for line in text.splitlines():
                line = line.strip()
                if line.startswith(prefix):
                    try:
                        wh = line.split(":", 1)[1].strip().lower()
                        w, h = wh.split("x")
                        return (int(w), int(h))
                    except Exception:
                        return None
        return None

    def get_screen_density(self):
        """Return DPI reported by `wm density`. Prefers override over physical."""
        if not self.available or not self.connected:
            return None
        res = self._run_adb(['shell', 'wm', 'density'])
        if res is None or res.returncode != 0:
            return None
        text = res.stdout or ""
        for prefix in ("Override density:", "Physical density:"):
            for line in text.splitlines():
                line = line.strip()
                if line.startswith(prefix):
                    try:
                        return int(line.split(":", 1)[1].strip())
                    except Exception:
                        return None
        return None

    def enforce_resolution(self, target_resolution, target_density=None, package_name="com.supercell.clashofclans"):
        """
        Lock the device to a known display geometry via `wm size` / `wm density`.

        If the target app is running and size needs to change, force-stop it
        first so its relaunch picks up the new layout cleanly (CoC does not
        re-layout robustly on live resolution change).

        target_resolution: "WIDTHxHEIGHT" string, e.g. "1600x900".
        target_density: integer DPI, or None to leave density untouched.
        Returns True when the target size is in effect afterwards.
        """
        if not self.available or not self.connected:
            return False
        try:
            tw_str, th_str = target_resolution.lower().split("x")
            tw, th = int(tw_str), int(th_str)
        except Exception:
            logger.error(f"Invalid target_resolution '{target_resolution}'. Use WIDTHxHEIGHT (e.g. 1600x900).")
            return False

        current_size = self.get_screen_size()
        current_density = self.get_screen_density()
        size_needs_change = current_size != (tw, th)
        density_needs_change = target_density is not None and current_density != target_density

        if not (size_needs_change or density_needs_change):
            logger.debug(f"Display already at {tw}x{th} @ density {current_density}.")
            return True

        logger.info(
            f"Enforcing display: size {current_size} -> {tw}x{th}, density {current_density} -> {target_density}"
        )

        if size_needs_change and self.is_app_running(package_name):
            logger.warning(f"{package_name} is running; force-stopping before resolution change.")
            self._run_adb(['shell', 'am', 'force-stop', package_name])
            time.sleep(1.0)

        if size_needs_change:
            res = self._run_adb(['shell', 'wm', 'size', f"{tw}x{th}"])
            if res is None or res.returncode != 0:
                logger.warning(f"Failed to set wm size to {tw}x{th}.")
                return False

        if density_needs_change:
            res = self._run_adb(['shell', 'wm', 'density', str(target_density)])
            if res is None or res.returncode != 0:
                logger.warning(f"Failed to set wm density to {target_density}; continuing with size change only.")

        time.sleep(0.5)
        actual = self.get_screen_size()
        if actual != (tw, th):
            logger.warning(f"After wm size, screen is {actual} (expected {tw}x{th}).")
            return False
        logger.info(
            f"Display locked to {tw}x{th}" + (f" @ density {target_density}" if target_density else "")
        )
        return True

    def get_screen(self):
        if not self.available or not self.connected:
            return None
        try:
            pipe = subprocess.Popen(
                self._adb_cmd(['exec-out', 'screencap', '-p']),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            image_bytes = pipe.stdout.read()
            if not image_bytes:
                return None
            image_array = np.frombuffer(image_bytes, dtype=np.uint8)
            screen = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
            return screen
        except FileNotFoundError:
            logger.error("adb binary not found when attempting to capture screen.")
            return None
