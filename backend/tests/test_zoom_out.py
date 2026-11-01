"""Unit tests for zoom_out.py — host-side only, no device, everything mocked.

Run:  cd backend && ..\\.venv\\Scripts\\python.exe tests\\test_zoom_out.py

Covers the acceptance criteria of the uiautomator2 zoom-out spec:
  1. pinch_in raises RPCUnknownError(INJECT_EVENTS) 3x then succeeds ->
     True, device.shell('input tap 5 5') exactly 3x, backoff 0.35->0.525->0.7875
  2. pinch_in always raises -> False after exactly retries+1 tries, no raise
  3. multi_zoom_out(addr='') -> message + False, u2.connect never called
  4. multi_zoom_out(count=3) -> exactly 3 _safe_pinch_in calls, interval
     sleeps between them (u2.connect mocked)
  5. CLI without a configured host -> clean message, no traceback
"""
import contextlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import zoom_out
from uiautomator2.exceptions import RPCUnknownError

passed = 0
failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS {name}")
    else:
        failed += 1
        print(f"  FAIL {name}")


class FakeTime:
    """Stand-in for the stdlib time module inside zoom_out — records sleeps."""

    def __init__(self):
        self.sleeps = []

    def sleep(self, seconds):
        self.sleeps.append(seconds)


class FakeUIObj:
    """pinch_in replays a script: items are results; an Exception item raises."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def pinch_in(self, percent=100, steps=20):
        self.calls += 1
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class AlwaysFailUIObj:
    def __init__(self):
        self.calls = 0

    def pinch_in(self, percent=100, steps=20):
        self.calls += 1
        raise RPCUnknownError(
            "java.lang.SecurityException: Injecting to another application "
            "requires INJECT_EVENTS permission")


class FakeDevice:
    def __init__(self):
        self.shells = []

    def shell(self, cmd):
        self.shells.append(cmd)


INJECT_ERR = RPCUnknownError(
    "java.lang.SecurityException: Injecting to another application "
    "requires INJECT_EVENTS permission")


def test_safe_pinch_in_inject_events_retry():
    print("[1] INJECT_EVENTS x3 then success")
    ft = FakeTime()
    real_time = zoom_out.time
    zoom_out.time = ft
    try:
        ui = FakeUIObj([INJECT_ERR, INJECT_ERR, INJECT_ERR, True])
        dev = FakeDevice()
        ok = zoom_out._safe_pinch_in(ui, retries=5, backoff=0.35, device=dev)
        check("returns True", ok is True)
        check("pinch attempted 4x (3 misses + 1 hit)", ui.calls == 4)
        check("input tap 5 5 poked exactly 3x",
              dev.shells == ["input tap 5 5"] * 3)
        expected = [0.35, 0.35 * 1.5, 0.35 * 1.5 * 1.5]   # 0.35 -> 0.525 -> 0.7875
        check("backoff chain 0.35 -> 0.525 -> 0.7875",
              len(ft.sleeps) == 3 and all(abs(a - b) < 1e-9 for a, b in zip(ft.sleeps, expected)))
        check("cap not hit yet (all < 2.0)", all(s < 2.0 for s in ft.sleeps))
    finally:
        zoom_out.time = real_time


def test_safe_pinch_in_always_fails():
    print("[2] always failing -> False after retries+1 tries")
    ft = FakeTime()
    real_time = zoom_out.time
    zoom_out.time = ft
    try:
        ui = AlwaysFailUIObj()
        ok = zoom_out._safe_pinch_in(ui, retries=5, backoff=0.35, device=None)
        check("returns False (no raise)", ok is False)
        check("exactly retries+1 (6) tries", ui.calls == 6)
        check("backoff capped at 2.0", ft.sleeps[-1] == 2.0 and len(ft.sleeps) == 6)
    finally:
        zoom_out.time = real_time


def test_multi_zoom_out_no_host():
    print("[3] multi_zoom_out(addr='') -> message + False, no connect")
    connect_calls = []

    class Guard:
        @staticmethod
        def connect(addr):
            connect_calls.append(addr)
            raise AssertionError("u2.connect must not be called")

    real_u2 = zoom_out.u2
    zoom_out.u2 = Guard
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = zoom_out.multi_zoom_out(addr="")
        check("returns False", ok is False)
        check("u2.connect never called", connect_calls == [])
        check("no-host message printed",
              "No emulator host set before calling multi_zoom_out()" in buf.getvalue())
    finally:
        zoom_out.u2 = real_u2


def test_multi_zoom_out_count():
    print("[4] multi_zoom_out(count=3) -> 3 attempts + interval sleeps")
    connect_calls = []

    class FakeU2:
        @staticmethod
        def connect(addr):
            connect_calls.append(addr)
            return lambda: None          # d() -> root (unused; pinch is mocked)

    pinch_calls = []

    def fake_safe_pinch(root, percent=100, steps=20, retries=5, backoff=0.35, device=None):
        pinch_calls.append((root, percent, steps, device))
        return True

    real_u2, real_sp, real_time = zoom_out.u2, zoom_out._safe_pinch_in, zoom_out.time
    ft = FakeTime()
    try:
        zoom_out.u2 = FakeU2
        zoom_out._safe_pinch_in = fake_safe_pinch
        zoom_out.time = ft
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = zoom_out.multi_zoom_out(addr="127.0.0.1:21503", count=3, interval=0.5)
        check("returns True (>=1 success)", ok is True)
        check("u2.connect called once with the serial",
              connect_calls == ["127.0.0.1:21503"])
        check("_safe_pinch_in called exactly 3x", len(pinch_calls) == 3)
        check("interval slept between attempts only (2x 0.5)",
              ft.sleeps == [0.5, 0.5])
        check("device passed through", all(d is not None for _, _, _, d in pinch_calls))
    finally:
        zoom_out.u2, zoom_out._safe_pinch_in, zoom_out.time = real_u2, real_sp, real_time


def test_cli_no_host():
    print("[5] CLI with no configured host -> clean message, no traceback")
    connect_calls = []

    class Guard:
        @staticmethod
        def connect(addr):
            connect_calls.append(addr)
            raise AssertionError("u2.connect must not be called")

    real_u2, real_default = zoom_out.u2, zoom_out._default_serial
    zoom_out.u2 = Guard
    zoom_out._default_serial = lambda: None
    try:
        buf = io.StringIO()
        argv_backup = sys.argv
        sys.argv = ["zoom_out.py"]
        try:
            with contextlib.redirect_stdout(buf):
                zoom_out._cli()          # must return without raising
            check("_cli() returns cleanly (no traceback)", True)
        except Exception as e:
            check(f"_cli() raised unexpectedly: {e}", False)
        finally:
            sys.argv = argv_backup
        check("no-host message printed",
              "No emulator host set before calling multi_zoom_out()" in buf.getvalue())
        check("u2.connect never called", connect_calls == [])
    finally:
        zoom_out.u2, zoom_out._default_serial = real_u2, real_default


def test_default_serial_reads_settings():
    print("[+] _default_serial reads coc-studio settings.json (config equivalent)")
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "data", "settings.json"), "r", encoding="utf-8") as f:
        expected = (json.load(f).get("device", {}) or {}).get("serial")
    check("serial matches settings.json", zoom_out._default_serial() == expected)


if __name__ == "__main__":
    test_safe_pinch_in_inject_events_retry()
    test_safe_pinch_in_always_fails()
    test_multi_zoom_out_no_host()
    test_multi_zoom_out_count()
    test_cli_no_host()
    test_default_serial_reads_settings()
    print(f"\n=== {passed} passed, {failed} failed ===")
    sys.exit(1 if failed else 0)
