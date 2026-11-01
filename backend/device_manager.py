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
from core.device import Device, PROFILE_ENDPOINTS
from core.bootstrap import bootstrap_device, connect_with_profile, ensure_emulator_running, is_emulator_running
from core.ocr import warmup_ocr, read_number_with_confidence

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
        self._ocr_warm = False
        self.last_reason = "not_connected"

    # -- lifecycle ---------------------------------------------------------
    def ensure_assets(self):
        if not self._assets_loaded:
            vision.load_assets(app_paths.ASSETS_DIR)
            self._assets_loaded = True
            logger.info("Assets preloaded from %s", app_paths.ASSETS_DIR)

    def ensure_ocr(self):
        """Warm up the easyocr reader once. Heavy (~seconds) — only on run path.

        M1 connect() deliberately skips this; OCR is only needed when a graph
        actually reads loot numbers.
        """
        if not self._ocr_warm:
            warmup_ocr()
            self._ocr_warm = True
            logger.info("OCR reader warmed up")

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

    def scan(self):
        """List adb devices for the configured profile WITHOUT launching an
        emulator. Returns [{serial, state}]. Tries the profile's known endpoints
        (or the custom endpoint) so a freshly-started emulator gets connected.
        """
        with self._lock:
            cfg = load_settings().get("device", {})
            profile = cfg.get("profile", "usb_or_existing")
            endpoint = cfg.get("endpoint", "")
            dev = self.device or Device(
                adb_path=cfg.get("adb_path") or None, profile=profile, endpoint=endpoint
            )
            if not getattr(dev, "available", False):
                self.last_reason = "adb_unavailable"
                return []
            # Nudge the known endpoints so emulators that are up but not yet in
            # `adb devices` get attached (mirrors connect_with_profile).
            connect_with_profile(dev, profile, endpoint)
            return dev.list_devices()

    def launch_emulator(self):
        """Launch the configured profile's emulator if it isn't running."""
        with self._lock:
            cfg = load_settings().get("device", {})
            profile = cfg.get("profile", "usb_or_existing")
            if profile not in PROFILE_ENDPOINTS or profile in ("usb_or_existing", "custom_endpoint"):
                return {"launched": False, "running": False, "reason": "profile has no emulator"}
            override = cfg.get("emulator_path") or None
            ensure_emulator_running(profile, logger, override_path=override)
            return {"launched": True, "running": is_emulator_running(profile)}

    def disconnect(self):
        """Drop the in-process device reference (does NOT kill the emulator or
        adb-server). A subsequent connect() re-bootstraps cleanly."""
        with self._lock:
            self.device = None
            self.ui_manager = None
            self.last_reason = "disconnected"
            return True

    def set_serial(self, serial):
        """Persist the chosen serial to settings; revalidate if connected."""
        with self._lock:
            settings = load_settings()
            settings.setdefault("device", {})["serial"] = serial
            save_settings(settings)
            if self.device is not None:
                self.device.serial = serial
                self.device.ensure_connection(retries=1)
            return True

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
