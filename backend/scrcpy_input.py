"""scrcpy-based multi-touch injection.

The Memu touch driver ignores injected multi-touch from inside the guest
(sendevent / evdev writes forward only one contact), but the ANDROID FRAMEWORK
injection path (InputManager, the same one `input tap` uses — which works)
accepts real multi-pointer MotionEvents. scrcpy's server drives exactly that
path through shell privileges.

This module runs scrcpy-server v1.25 on the device (pushed via adb, started
with app_process), connects to it through `adb reverse`, and exposes
`touch()` / `pinch()` on the control channel.

Protocol (scrcpy v1.25): two sockets through adb reverse — video accepted
first, control second; the video socket carries a 1-byte dummy + 68-byte
device meta, then an H.264 stream (drained in a thread). Control messages:
TYPE_INJECT_TOUCH_EVENT = 2, payload: action(1) pointer_id(8) x(4) y(4)
screen_w(2) screen_h(2) pressure(2) buttons(4), all big-endian.
"""
import socket
import struct
import subprocess
import threading
import time

SERVER_JAR = "scrcpy_server_125.jar"
DEVICE_JAR = "/data/local/tmp/scrcpy_server.jar"
VERSION = "1.25"
LOCAL_PORT = 28721
SCREEN_W, SCREEN_H = 1600, 900

ACTION_DOWN, ACTION_UP, ACTION_MOVE = 0, 1, 2


class ScrcpyClient:
    def __init__(self, adb, serial, logger=None):
        self.adb, self.serial, self.log = adb, serial, logger
        self.proc = None
        self.vid = None
        self.ctl = None
        self._drain = None

    def _run(self, args, **kw):
        return subprocess.run([self.adb, "-s", self.serial] + args,
                              capture_output=True, text=True, **kw)

    def start(self):
        self._run(["push", SERVER_JAR, DEVICE_JAR])
        # scrcpy v1.25 default mode: the SERVER LISTENS on
        # localabstract:scrcpy; the host connects to it through
        # `adb reverse localabstract:scrcpy tcp:<port>`. Two connections in
        # order: video, then control. The server needs ~1-2s to start, so
        # the connect retries.
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        local_port = probe.getsockname()[1]
        probe.close()   # OS-guaranteed free, non-excluded port
        launch = ("CLASSPATH=" + DEVICE_JAR +
                  " app_process / com.genymobile.scrcpy.Server " + VERSION +
                  f" log_level=warn max_size=1600")
        self.proc = subprocess.Popen([self.adb, "-s", self.serial, "shell", launch],
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL,
                                     stdin=subprocess.DEVNULL)
        self._run(["reverse", "localabstract:scrcpy", f"tcp:{local_port}"])
        vid = ctl = None
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                vid = socket.create_connection(("127.0.0.1", local_port), timeout=3)
                ctl = socket.create_connection(("127.0.0.1", local_port), timeout=3)
                break
            except OSError:
                try:
                    if vid:
                        vid.close()
                    if ctl:
                        ctl.close()
                except Exception:
                    pass
                vid = ctl = None
                time.sleep(0.5)
        if vid is None or ctl is None:
            raise RuntimeError("scrcpy server did not accept connections")
        self.vid, self.ctl = vid, ctl
        # handshake on the video socket: dummy byte + 68 device-meta bytes
        self.vid.settimeout(3.0)
        got = b""
        try:
            while len(got) < 69:
                chunk = self.vid.recv(69 - len(got))
                if not chunk:
                    break
                got += chunk
        except socket.timeout:
            pass
        self.vid.settimeout(None)
        threading.Thread(target=self._drain_video, daemon=True).start()
        if self.log:
            self.log.info("[scrcpy] server connected (video + control)")

    def _drain_video(self):
        try:
            while True:
                if not self.vid.recv(65536):
                    break
        except OSError:
            pass

    def touch(self, action, pointer_id, x, y, pressure):
        x = max(0, min(SCREEN_W - 1, int(x)))
        y = max(0, min(SCREEN_H - 1, int(y)))
        p16 = int(pressure * 0xFFFF)
        msg = struct.pack(">BBqiiHHHi", 2, action, pointer_id, x, y,
                          SCREEN_W, SCREEN_H, p16, 0)
        self.ctl.sendall(msg)

    def pinch(self, cx, cy, r_from, r_to, steps=10, interval=0.05):
        """Two-finger pinch around (cx, cy): radius r_from -> r_to. For zoom
        OUT the fingers move TOWARD each other (r_from > r_to)."""
        import math
        f0 = (cx - r_from, cy)
        f1 = (cx + r_from, cy)
        self.touch(ACTION_DOWN, 0, f0[0], f0[1], 1.0)
        time.sleep(0.05)
        self.touch(ACTION_DOWN, 1, f1[0], f1[1], 1.0)
        time.sleep(0.05)
        for i in range(1, steps + 1):
            if self.log and self.log.isEnabledFor(10):
                pass
            r = r_from + (r_to - r_from) * i / steps
            a = math.atan2(0, 1)  # horizontal pinch
            f0 = (cx - r, cy)
            f1 = (cx + r, cy)
            self.touch(ACTION_MOVE, 0, f0[0], f0[1], 1.0)
            self.touch(ACTION_MOVE, 1, f1[0], f1[1], 1.0)
            time.sleep(interval)
        self.touch(ACTION_UP, 0, f0[0], f0[1], 0.0)
        self.touch(ACTION_UP, 1, f1[0], f1[1], 0.0)
        time.sleep(0.05)

    def close(self):
        try:
            if self.ctl:
                self.ctl.close()
            if self.vid:
                self.vid.close()
            if self.proc:
                self.proc.terminate()
        except Exception:
            pass


_client = None


def get_client(adb, serial, logger=None):
    """Process-wide scrcpy client singleton (the server stays alive on the
    device for the whole session)."""
    global _client
    if _client is None:
        _client = ScrcpyClient(adb, serial, logger)
        _client.start()
    return _client
