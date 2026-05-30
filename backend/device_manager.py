"""Process-wide device/vision state.

Wraps the reused ``core`` modules (Device, UIManager, vision, ocr) behind a
single connect/capture surface the API layer can call. The browser never
touches ADB — this is the only place that does.

Design notes:
- Bootstrap is the existing ``core.bootstrap.bootstrap_device`` run in
  ``non_interactive`` mode (returns the configured profile, no stdin prompts).
- ``get_screen`` shells out to adb (blocking); callers in async code must run
  ``capture_jpeg`` via ``asyncio.to_thread``.
- Asset preloading uses ``vision.load_assets`` exactly once (REQUIREMENT §7:
  no ``cv2.imread`` in loops).
"""
import json
import logging
import threading

import cv2

import app_paths
from core.humanize import Humanize
from core.ui_manager import UIManager
from core.vision import vision
from core.bootstrap import bootstrap_device
from core.ocr import warmup_ocr

logger = logging.getLogger(__name__)

COC_PACKAGE = "com.supercell.clashofclans"


def load_settings():
    with open(app_paths.SETTINGS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_settings(settings):
    with open(app_paths.SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


class DeviceManager:
    """Holds the connected Device + UIManager for the whole process."""

    def __init__(self):
        self._lock = threading.RLock()
        self.device = None
        self.ui_manager = None
        self.humanize = None
        self._assets_loaded = False
        self.last_reason = "not_connected"

    # -- lifecycle ---------------------------------------------------------
    def ensure_assets(self):
        if not self._assets_loaded:
            vision.load_assets(app_paths.ASSETS_DIR)
            self._assets_loaded = True
            logger.info("Assets preloaded from %s", app_paths.ASSETS_DIR)

    def connect(self, non_interactive=True):
        """Bootstrap the device. Returns (ok: bool, reason: str).

        Idempotent: if already connected, revalidates the existing transport
        instead of re-launching the emulator.
        """
        with self._lock:
            if self.device is not None and self.device.connected:
                if self.device.ensure_connection():
                    self.last_reason = "already_connected"
                    return True, self.last_reason

            settings = load_settings()
            self.humanize = Humanize(settings)
            device = bootstrap_device(
                settings, save_settings, logger, non_interactive=non_interactive
            )
            if device is None:
                self.last_reason = "adb_unavailable"
                return False, self.last_reason

            self.device = device
            self.ui_manager = UIManager(self.humanize, device)
            self.ensure_assets()
            self.last_reason = "connected" if device.connected else "device_unreachable"
            return device.connected, self.last_reason

    # -- capture -----------------------------------------------------------
    def capture_bgr(self):
        """Return the current screen as a BGR numpy array, or None."""
        with self._lock:
            if self.device is None:
                return None
            return self.device.get_screen()

    def capture_jpeg(self, quality=70):
        """Return current screen JPEG-encoded, or None if unavailable."""
        frame = self.capture_bgr()
        if frame is None:
            return None
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
        if not ok:
            return None
        return buf.tobytes()

    # -- introspection -----------------------------------------------------
    def status(self):
        with self._lock:
            dev = self.device
            return {
                "connected": bool(dev and dev.connected),
                "available": bool(dev and getattr(dev, "available", False)),
                "serial": getattr(dev, "serial", None) if dev else None,
                "profile": getattr(dev, "profile", None) if dev else None,
                "assets_loaded": self._assets_loaded,
                "reason": self.last_reason,
            }


# Process-wide singleton.
manager = DeviceManager()
