"""Device package — the public ``Device`` class, composed from mixins.

Formerly a single ~900-line ``core/device.py`` god-module; now split by
responsibility:

- ``profiles.py``       — emulator profile constants (endpoints/exes/processes)
- ``transport.py``      — ADB command execution, recovery, device selection
- ``app_lifecycle.py``  — install/launch/foreground/restart of the target app
- ``display.py``        — screencap + resolution/density enforcement
- ``touch.py``          — tap/swipe/pinch input injection

The public surface is unchanged: ``from core.device import Device`` (plus the
``PROFILE_*`` constants, re-exported here for ``core/bootstrap.py`` and
``device_manager.py``) works exactly as before.
"""
import logging
import shutil

from .profiles import (
    PROFILE_ENDPOINTS,
    PROFILE_EXECUTABLES,
    PROFILE_PROCESS_NAMES,
    COC_MAIN_ACTIVITY,
)
from .transport import AdbTransportMixin
from .app_lifecycle import AppLifecycleMixin
from .display import DisplayMixin
from .touch import TouchInputMixin

__all__ = [
    "Device",
    "PROFILE_ENDPOINTS",
    "PROFILE_EXECUTABLES",
    "PROFILE_PROCESS_NAMES",
    "COC_MAIN_ACTIVITY",
]

logger = logging.getLogger(__name__)


class Device(AdbTransportMixin, AppLifecycleMixin, DisplayMixin, TouchInputMixin):
    def __init__(self, serial=None, strict_serial=True, adb_path=None, profile=None, endpoint=None):
        self.serial = serial
        self.strict_serial = strict_serial
        # Detect adb binary path early to avoid FileNotFoundError on subprocess.
        self.adb_path = adb_path or shutil.which("adb")
        self.available = bool(self.adb_path)
        self.connected = False
        self.last_status_reason = "unknown"
        # Stored so the transparent shell-recovery path can reconnect the
        # right endpoints after kill-server/start-server.
        self.profile = profile
        self.endpoint = endpoint
        if not self.available:
            logger.warning("'adb' not found in PATH. Device operations will be disabled.")
            logger.info("To enable device control, install Android platform-tools and add 'adb' to your PATH.")
        # Note: avoid performing heavy side-effects at import-time.
        # Initialization will not automatically check connection or wake the
        # screen; callers should invoke those explicitly if desired.
