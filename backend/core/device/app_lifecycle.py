"""App lifecycle mixin — install checks, launch, foreground, restart.

Owns everything about the *target app* on the device: whether CoC is
installed/running/foreground, resolving launch components, launching and
restarting the game, and the high-level ``ensure_coc_ready`` recovery flow.
Split out of the former ``core/device.py`` god-module; behaviour unchanged.
"""
import time
import logging

from .profiles import COC_MAIN_ACTIVITY

logger = logging.getLogger(__name__)


class AppLifecycleMixin:
    """Requires AdbTransportMixin (``_run_adb``, ``_is_shell_transport_closed``,
    ``find_serial_with_package`` helpers live here too)."""

    def wake_screen(self):
        if not self.available or not self.connected:
            return
        res = self._run_adb(['shell', 'dumpsys', 'power'])
        if res and ("mHoldingDisplaySuspendBlocker=false" in res.stdout or "Display Power: state=OFF" in res.stdout):
            self._run_adb(['shell', 'input', 'keyevent', '26'])
            time.sleep(1)

    def is_app_running(self, package_name="com.supercell.clashofclans"):
        """Check if app has an active process or is in foreground."""
        if not self.available or not self.connected:
            return False
        try:
            # Fast path: app is foreground.
            if self.is_app_foreground(package_name):
                return True

            # Process check (more reliable than broad dumpsys activity parsing).
            res_pid = self._run_adb(['shell', 'pidof', package_name])
            if res_pid and (res_pid.stdout or "").strip():
                return True

            # Fallback for devices where pidof is unavailable.
            res_ps = self._run_adb(['shell', 'ps'])
            if res_ps and package_name in (res_ps.stdout or ""):
                return True

            return False
        except Exception as e:
            logger.debug(f"Failed to check if app is running: {e}")
            return False

    def is_app_foreground(self, package_name="com.supercell.clashofclans"):
        """Check if app is in foreground (active/focused window)."""
        if not self.available or not self.connected:
            return False
        try:
            res = self._run_adb(['shell', 'dumpsys', 'window', 'windows'])
            if res is None:
                return False
            # Look for mCurrentFocus which shows the currently focused app
            if package_name in res.stdout and "mCurrentFocus" in res.stdout:
                # More specific check: see if package appears near mCurrentFocus
                for line in res.stdout.split('\n'):
                    if 'mCurrentFocus' in line and package_name in line:
                        logger.debug(f"App {package_name} is in foreground")
                        return True
            logger.debug(f"App {package_name} is NOT in foreground")
            return False
        except Exception as e:
            logger.debug(f"Failed to check if app is foreground: {e}")
            return False

    def resolve_launch_component(self, package_name):
        """
        Resolve best launcher component for a package.
        Returns component string: <package>/<activity> or None.
        """
        if not self.available or not self.connected:
            return None

        # Preferred: package manager resolver.
        res = self._run_adb(['shell', 'cmd', 'package', 'resolve-activity', '--brief', package_name])
        if res is not None and res.returncode == 0:
            for line in reversed((res.stdout or "").splitlines()):
                line = line.strip()
                if line.startswith(package_name + "/"):
                    return line

        # Fallback for environments where cmd package is unreliable.
        return f"{package_name}/{COC_MAIN_ACTIVITY}"

    def bring_app_to_foreground(self, package_name="com.supercell.clashofclans"):
        """Bring app to foreground if running but backgrounded."""
        if not self.available or not self.connected:
            logger.warning("Cannot bring app to foreground: no active ADB device.")
            return False

        logger.info(f"Bringing {package_name} to foreground...")
        component = self.resolve_launch_component(package_name)

        # Strategy 0: explicit known launcher activity (most reliable for CoC).
        if component:
            self._run_adb(['shell', 'am', 'start', '-n', component])
            time.sleep(2)
            if self.is_app_foreground(package_name):
                return True

        # Strategy 1: monkey quick launch
        self._run_adb(['shell', 'monkey', '-p', package_name, '1'])
        time.sleep(2)
        if self.is_app_foreground(package_name):
            return True

        # Strategy 2: launcher intent
        if component:
            self._run_adb(['shell', 'am', 'start', '-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.LAUNCHER', '-n', component])
        else:
            self._run_adb(['shell', 'am', 'start', '-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.LAUNCHER', '-p', package_name])
        time.sleep(2)
        if self.is_app_foreground(package_name):
            return True

        logger.warning("Could not bring app to foreground.")
        return False

    def is_package_installed(self, package_name):
        if not self.available or not self.connected:
            return None
        # Primary check.
        res = self._run_adb(['shell', 'pm', 'list', 'packages', package_name])
        if res is not None and res.returncode == 0 and package_name in (res.stdout or ""):
            return True

        # Fallback: some BlueStacks builds intermittently close pm shell command.
        res_ds = self._run_adb(['shell', 'dumpsys', 'package', package_name])
        if res_ds is None:
            self.last_status_reason = "package_check_unavailable"
            return None
        if res_ds.returncode != 0:
            if self._is_shell_transport_closed(res) or self._is_shell_transport_closed(res_ds):
                self.last_status_reason = "adb_shell_closed"
                return None
            return False
        out = res_ds.stdout or ""
        return f"Package [{package_name}]" in out or f"package={package_name}" in out

    def find_serial_with_package(self, package_name):
        """
        Try all ready ADB devices and return first serial where package is installed.
        Returns None if not found or package state cannot be verified.
        """
        devices = self.list_devices()
        ready = [d["serial"] for d in devices if d.get("state") == "device"]
        original_serial = self.serial
        try:
            for serial in ready:
                self.serial = serial
                state = self.is_package_installed(package_name)
                if state is True:
                    return serial
        finally:
            self.serial = original_serial
        return None

    def launch_game(self, package_name="com.supercell.clashofclans"):
        if not self.available or not self.connected:
            logger.warning("Cannot launch game: no active ADB device.")
            return False

        install_state = self.is_package_installed(package_name)
        if install_state is None:
            logger.error("Cannot verify app installation due to unstable ADB shell connection (error: closed).")
            logger.error("Please restart BlueStacks and ADB, then run the bot again.")
            return False
        if not install_state:
            logger.error("Clash of Clans is not installed on the selected emulator/device. Please install it, then run the bot again.")
            return False

        logger.info(f"Launching {package_name}...")
        component = self.resolve_launch_component(package_name)

        # Strategy 0: explicit known activity
        if component:
            self._run_adb(['shell', 'am', 'start', '-n', component])
            time.sleep(4)
            if self.is_app_running(package_name):
                return True

        # Strategy 1: monkey launcher
        self._run_adb(['shell', 'monkey', '-p', package_name, '-c', 'android.intent.category.LAUNCHER', '1'])
        time.sleep(4)
        if self.is_app_running(package_name):
            return True

        # Strategy 2: monkey direct open
        self._run_adb(['shell', 'monkey', '-p', package_name, '1'])
        time.sleep(4)
        if self.is_app_running(package_name):
            return True

        # Strategy 3: explicit launch intent
        if component:
            self._run_adb(['shell', 'am', 'start', '-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.LAUNCHER', '-n', component])
        else:
            self._run_adb(['shell', 'am', 'start', '-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.LAUNCHER', '-p', package_name])
        time.sleep(4)
        if self.is_app_running(package_name):
            return True

        logger.error("Launch attempts completed but app is still not running.")
        return False

    def restart_game(self, package_name="com.supercell.clashofclans"):
        """
        Force-stop the app and relaunch it. Used as a recovery path when the
        bot is stuck on a non-recognized state (e.g. inactivity disconnect
        popup) and `close_popups` cannot escape it. Returns True when the app
        is running afterwards.
        """
        if not self.available or not self.connected:
            logger.warning("Cannot restart game: no active ADB device.")
            return False
        logger.info(f"Restarting {package_name} (force-stop + launch)...")
        self._run_adb(['shell', 'am', 'force-stop', package_name])
        time.sleep(1.5)
        return self.launch_game(package_name)

    def ensure_coc_ready(self, package_name, settings, save_settings, logger):
        """
        Ensure CoC is installed, launched, and foregrounded.
        Returns True when ready, False otherwise.
        """
        install_state = self.is_package_installed(package_name)
        if install_state is None:
            logger.error("Cannot verify Clash of Clans installation because ADB shell connection is unstable.")
            logger.error("Action: restart BlueStacks, then run `adb kill-server`, `adb start-server`, and run the bot again.")
            return False

        if not install_state:
            alt_serial = self.find_serial_with_package(package_name)
            if alt_serial and alt_serial != self.serial:
                logger.warning(f"CoC not found on current serial. Switching to: {alt_serial}")
                self.serial = alt_serial
                settings.setdefault("device", {})
                settings["device"]["serial"] = alt_serial
                save_settings(settings)
                install_state = self.is_package_installed(package_name)

            if not install_state:
                logger.error("Clash of Clans is not installed on the selected emulator/device. Please install it, then run the bot again.")
                return False

        if self.is_app_running(package_name):
            logger.info("CoC is running.")
            if not self.is_app_foreground(package_name):
                logger.warning("CoC is running but in background. Bringing to foreground...")
                if not self.bring_app_to_foreground(package_name):
                    logger.error("CoC is running but cannot be brought to foreground. Stop bot.")
                    return False
            return True

        logger.warning("CoC is not running. Launching game...")
        if self.launch_game(package_name):
            return True

        alt_serial = self.find_serial_with_package(package_name)
        if alt_serial and alt_serial != self.serial:
            logger.warning(f"Launch failed on current serial. Trying fallback serial: {alt_serial}")
            self.serial = alt_serial
            settings.setdefault("device", {})
            settings["device"]["serial"] = alt_serial
            save_settings(settings)
            return self.launch_game(package_name)
        return False
