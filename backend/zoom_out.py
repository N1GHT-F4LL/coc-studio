"""Zoom-out for Clash of Clans: two-finger pinch-in injected via uiautomator2.

Reference: ``ZOOM_OUT_ANALYSIS.md`` (reverse-engineered from the Simplicity
bot, ``extracted/pyz/zoom_out.pyc``). In CoC, camera zoom-out == two fingers
collapsing toward the screen centre == ``UiObject.pinch_in``. The gesture is
injected by the on-device ATX agent (app-uiautomator.apk) through the Android
framework's InputManager — the same injection path ``input tap`` uses, which
is the path emulators (Memu included) actually honour for multi-pointer.
Nothing here touches the Windows host: no mouse simulation, no AutoHotkey,
no single-finger swipe.

Why the retry dance: Android REFUSES injected touch while a REAL finger is on
the screen — the agent's performMultiPointerGesture then fails with a
SecurityException about INJECT_EVENTS, surfacing over JSON-RPC as
RPCUnknownError. The bot must never crash on that: poke a harmless corner tap
to release the stray touch, back off exponentially and retry instead.

First connect installs the ATX agent into the emulator automatically (a
one-time ~seconds APK push) — tolerate transient RPC errors while it boots.
"""
import sys
import time

import uiautomator2 as u2
from uiautomator2.exceptions import RPCUnknownError

__all__ = ["multi_zoom_out"]


def _default_serial():
    """The bot's configured emulator serial — coc-studio's settings.json
    ``device.serial`` (the original bot's ``main.host`` equivalent).
    Returns None when unavailable so callers fall back to the no-host path."""
    try:
        import json
        import app_paths
        with open(app_paths.SETTINGS_PATH, "r", encoding="utf-8") as f:
            return (json.load(f).get("device", {}) or {}).get("serial") or None
    except Exception:
        return None


def _safe_pinch_in(uiobj, percent: int = 100, steps: int = 20, retries: int = 5,
                   backoff: float = 0.35, device=None) -> bool:
    """pinch_in with exponential backoff; NEVER raises.

    Total tries = 1 initial attempt + ``retries`` retries — pinned by the
    acceptance test ("trả False sau đúng retries+1 lần thử"). NOTE: the
    disassembly reconstruction in ZOOM_OUT_ANALYSIS.md shows
    ``range(1, retries + 1)`` (i.e. ``retries`` tries); the acceptance
    criteria are the contract here, hence retries+1.

    INJECT_EVENTS / SecurityException / performMultiPointerGesture in the RPC
    message means Android rejected the injected gesture because a real finger
    is on the screen — best-effort ``input tap 5 5`` (a harmless corner poke
    that releases the stray touch) via ``device``, then back off (×1.5 per
    miss, 2.0s cap) and retry. Every other failure also just retries.
    """
    delay = backoff
    for _attempt in range(1, retries + 2):
        try:
            uiobj.pinch_in(percent=percent, steps=steps)
            return True
        except RPCUnknownError as e:
            msg = str(e)
            if ('INJECT_EVENTS' in msg or 'SecurityException' in msg
                    or 'performMultiPointerGesture' in msg):
                if device is not None:
                    try:
                        device.shell('input tap 5 5')
                    except Exception:
                        pass
            time.sleep(delay)
            delay = min(delay * 1.5, 2.0)
        except Exception:
            time.sleep(delay)
            delay = min(delay * 1.5, 2.0)
    return False


def multi_zoom_out(addr=None, percent: int = 100, steps: int = 20, count: int = 3,
                   interval: float = 0.5, retries: int = 5, backoff: float = 0.35) -> bool:
    """Run ``count`` pinch-in gestures (zoom-out) on the emulator at ``addr``.

    ``addr=None`` reads the configured serial (``_default_serial``). Returns
    True when AT LEAST ONE pinch landed; False otherwise. Never raises — the
    whole body is guarded so a zoom problem can never kill the farm loop.
    """
    if addr is None:
        addr = _default_serial()
    if not addr:
        print('No emulator host set before calling multi_zoom_out()')
        return False
    any_success = False
    try:
        d = u2.connect(addr)
        root = d()                       # root UiObject = the whole screen
        for i in range(count):
            ok = _safe_pinch_in(root, percent=percent, steps=steps,
                                retries=retries, backoff=backoff, device=d)
            if ok:
                any_success = True
            else:
                print('⚠️ zoom-out attempt skipped after retries (likely due to user touch).')
            if i < count - 1:
                time.sleep(interval)
    except Exception as e:
        print(f'zoom-out aborted safely: {e}')
        return False
    return any_success


def _cli() -> None:
    """CLI: ``python zoom_out.py [addr] [percent] [steps] [count] [interval]``.

    Defaults: configured serial, 100, 20, 3, 0.5. With no serial configured
    anywhere, prints the no-host message and exits cleanly."""
    args = sys.argv[1:]
    addr = args[0] if len(args) > 0 else None
    try:
        percent = int(args[1]) if len(args) > 1 else 100
        steps = int(args[2]) if len(args) > 2 else 20
        count = int(args[3]) if len(args) > 3 else 3
        interval = float(args[4]) if len(args) > 4 else 0.5
    except ValueError:
        print('usage: python zoom_out.py [addr] [percent] [steps] [count] [interval]')
        return
    multi_zoom_out(addr=addr, percent=percent, steps=steps, count=count, interval=interval)


if __name__ == '__main__':
    # The ⚠️ prints would raise UnicodeEncodeError on a cp1252 console —
    # force UTF-8 exactly like backend/main.py does.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    try:
        _cli()
    except Exception:
        sys.exit(0)
