"""ADB transport mixin — command execution, recovery, and device selection.

Owns everything about *how* commands reach the device: building adb command
lines, running them with the flaky-transport auto-recovery (kill-server /
start-server kick), shell-health probing, serial failover, and picking the
target device. Split out of the former ``core/device.py`` god-module; all
behaviour is unchanged.
"""
import subprocess
import time
import logging

logger = logging.getLogger(__name__)


class AdbTransportMixin:
    """Requires the host class to provide: adb_path, serial, strict_serial,
    available, connected, last_status_reason, profile, endpoint."""

    def _adb_cmd(self, args):
        if not self.available:
            raise FileNotFoundError("adb binary not found in PATH")
        cmd = [self.adb_path]
        if self.serial:
            cmd.extend(['-s', self.serial])
        cmd.extend(args)
        return cmd

    def _run_adb(self, args, text=True, _recovered=False):
        if not self.available:
            return None
        try:
            res = subprocess.run(
                self._adb_cmd(args),
                capture_output=True,
                text=text,
            )
            # Auto-failover for flaky BlueStacks ADB transport.
            # If current serial shell is closed, try other ready serials.
            if (not self.strict_serial) and args and args[0] == 'shell' and self._is_shell_transport_closed(res):
                failover = self._run_shell_with_failover(args, text=text)
                if failover is not None:
                    return failover
            # Transparent transport recovery: shell-closed is a known BlueStacks
            # quirk that survives across calls until the adb server is restarted.
            # Try once per command to kick the transport and retry.
            if (not _recovered) and args and args[0] == 'shell' and self._is_shell_transport_closed(res):
                logger.warning("ADB shell transport closed. Attempting recovery (kill-server/start-server)...")
                if self.try_recover_adb_transport(profile=self.profile, endpoint=self.endpoint):
                    return self._run_adb(args, text=text, _recovered=True)
            return res
        except FileNotFoundError:
            self.connected = False
            self.last_status_reason = "adb_missing"
            return None

    def _is_shell_transport_closed(self, res):
        if res is None:
            return False
        msg = ((res.stdout or "") + " " + (res.stderr or "")).lower()
        return "error: closed" in msg or "device not found" in msg

    def _list_ready_serials_raw(self):
        """
        Read ready device serials directly from `adb devices` without using self.serial.
        """
        if not self.available:
            return []
        try:
            res = subprocess.run([self.adb_path, 'devices'], capture_output=True, text=True)
        except Exception:
            return []
        if res.returncode != 0:
            return []
        serials = []
        for line in (res.stdout or "").splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                serials.append(parts[0])
        return serials

    def shell_health_check(self, serial=None):
        """
        Check whether adb shell is usable for a serial.
        """
        if not self.available:
            return False
        target = serial or self.serial
        if not target:
            return False
        for _ in range(3):
            try:
                res = subprocess.run(
                    [self.adb_path, "-s", target, "shell", "id"],
                    capture_output=True,
                    text=True,
                )
            except Exception:
                continue
            if res.returncode != 0:
                time.sleep(0.2)
                continue
            out = ((res.stdout or "") + " " + (res.stderr or "")).lower()
            if "uid=" in out and "error: closed" not in out:
                return True
            time.sleep(0.2)
        return False

    def pick_healthy_serial(self, preferred_serial=None):
        """
        Choose the best serial by shell health.
        """
        ready = self._list_ready_serials_raw()
        if not ready:
            return None

        # Prefer configured serial if its shell is healthy.
        if preferred_serial and preferred_serial in ready and self.shell_health_check(preferred_serial):
            return preferred_serial

        # Otherwise pick first healthy serial.
        for serial in ready:
            if self.shell_health_check(serial):
                return serial
        return None

    def try_recover_adb_transport(self, profile=None, endpoint=None):
        """
        Best-effort transport recovery for flaky emulator ADB shell.
        """
        if not self.available:
            return False
        try:
            subprocess.run([self.adb_path, "kill-server"], capture_output=True, text=True)
            subprocess.run([self.adb_path, "start-server"], capture_output=True, text=True)
            if endpoint:
                subprocess.run([self.adb_path, "connect", endpoint], capture_output=True, text=True)
            if profile:
                from .profiles import PROFILE_ENDPOINTS
                for ep in PROFILE_ENDPOINTS.get(profile, []):
                    subprocess.run([self.adb_path, "connect", ep], capture_output=True, text=True)
        except Exception:
            return False
        time.sleep(0.5)
        return True

    def _run_shell_with_failover(self, shell_args, text=True):
        """
        Try shell command on alternative ready serials when current serial transport is closed.
        """
        candidates = self._list_ready_serials_raw()
        if not candidates:
            return None

        current = self.serial
        for serial in candidates:
            if serial == current:
                continue
            try:
                cmd = [self.adb_path, '-s', serial] + shell_args
                res = subprocess.run(cmd, capture_output=True, text=text)
            except Exception:
                continue
            if res.returncode == 0 and not self._is_shell_transport_closed(res):
                self.serial = serial
                logger.warning(f"ADB shell transport on '{current}' was closed. Switched to '{serial}'.")
                return res
        return None

    def _has_usable_device(self, devices_output):
        lines = [line.strip() for line in devices_output.splitlines()[1:] if line.strip()]
        if not lines:
            self.last_status_reason = "no_devices"
            return False

        if self.serial:
            for line in lines:
                if line.startswith(f"{self.serial}\tdevice"):
                    self.last_status_reason = "ok"
                    return True
            self.last_status_reason = "serial_not_found_or_unauthorized"
            return False

        for line in lines:
            if line.endswith("\tdevice"):
                self.last_status_reason = "ok"
                return True

        self.last_status_reason = "unauthorized_or_offline"
        return False

    def list_devices(self):
        """
        Return parsed output of `adb devices`:
        [{"serial": "...", "state": "device|offline|unauthorized"}]
        """
        if not self.available:
            return []
        res = self._run_adb(['devices'])
        if res is None or res.returncode != 0:
            self.last_status_reason = "adb_command_failed"
            return []

        devices = []
        lines = [line.strip() for line in res.stdout.splitlines()[1:] if line.strip()]
        for line in lines:
            parts = line.split()
            if len(parts) >= 2:
                devices.append({"serial": parts[0], "state": parts[1]})
        return devices

    def start_adb_server(self):
        if not self.available:
            return False
        res = self._run_adb(['start-server'])
        return bool(res and res.returncode == 0)

    def connect_device(self, endpoint):
        if not self.available:
            return False
        res = self._run_adb(['connect', endpoint])
        if res is None:
            return False
        out = (res.stdout or "") + (res.stderr or "")
        out = out.lower()
        return ("connected to" in out) or ("already connected to" in out)

    def select_device(self, preferred_serial=None, auto_select_single=True):
        """
        Pick a target device and assign self.serial.
        Returns True when a usable target is selected.
        """
        devices = self.list_devices()
        ready_devices = [d for d in devices if d["state"] == "device"]

        if preferred_serial:
            for d in ready_devices:
                if d["serial"] == preferred_serial:
                    self.serial = preferred_serial
                    return True
            self.last_status_reason = "preferred_serial_not_ready"
            return False

        if auto_select_single and len(ready_devices) == 1:
            self.serial = ready_devices[0]["serial"]
            logger.info(f"Auto-selected ADB device: {self.serial}")
            return True

        if len(ready_devices) == 0:
            self.last_status_reason = "no_ready_device"
            return False

        # Multiple ready devices but no explicit serial configured.
        self.last_status_reason = "multiple_devices_require_serial"
        logger.error("Multiple ADB devices detected. Please set device.serial in settings.json")
        for d in ready_devices:
            logger.error(f"- {d['serial']}")
        return False

    def _check_connection(self):
        if not self.available:
            logger.debug("Skipping connection check: adb not available.")
            self.connected = False
            self.last_status_reason = "adb_missing"
            return False

        res = self._run_adb(['devices'])
        if res is None or res.returncode != 0:
            self.connected = False
            self.last_status_reason = "adb_command_failed"
            logger.warning("Failed to query ADB devices.")
            return False

        self.connected = self._has_usable_device(res.stdout)
        if not self.connected:
            logger.warning(f"No usable ADB device detected ({self.last_status_reason}).")
        return self.connected

    def ensure_connection(self, retries=3, retry_delay=1.0):
        for attempt in range(1, retries + 1):
            if self._check_connection():
                if attempt > 1:
                    logger.debug(f"ADB device detected on attempt {attempt}/{retries}.")
                return True
            if attempt < retries:
                logger.debug(f"Waiting for ADB device ({attempt}/{retries})...")
                time.sleep(retry_delay)
        return False
