"""Device control + live screen streaming.

REST:
  GET  /api/device/status   -> current connection state
  POST /api/device/connect  -> bootstrap the device (non-interactive)

WebSocket:
  /ws/device                -> binary JPEG frames of the live screen

The browser uses the WS feed for the live device view and for coordinate
picking; it never issues ADB itself. All blocking adb capture runs in a
thread so the event loop stays responsive.
"""
import asyncio
import logging

from fastapi import APIRouter, Body, HTTPException, WebSocket, WebSocketDisconnect

from device_manager import manager, load_settings, save_settings

logger = logging.getLogger(__name__)
router = APIRouter()

# Emulator/device profiles bootstrap_device understands (mirrors
# core/bootstrap.py choose_profile_interactive). value -> display label.
DEVICE_PROFILES = [
    ("ldplayer", "LDPlayer"),
    ("bluestacks", "BlueStacks"),
    ("nox", "Nox"),
    ("mumu", "MuMu"),
    ("android_emulator", "Android Emulator"),
    ("usb_or_existing", "USB / existing adb device"),
    ("custom_endpoint", "Custom ADB endpoint"),
]
_PROFILE_KEYS = {k for k, _ in DEVICE_PROFILES}

# Default stream cadence. The client may override via ?fps= on the WS URL.
DEFAULT_FPS = 4
MIN_FPS = 1
MAX_FPS = 15


@router.get("/api/device/status")
def device_status():
    return manager.status()


@router.get("/api/device/profiles")
def device_profiles():
    """List selectable profiles + the one currently configured in settings."""
    cfg = load_settings().get("device", {})
    return {
        "profiles": [{"value": v, "label": lbl} for v, lbl in DEVICE_PROFILES],
        "current": cfg.get("profile", "usb_or_existing"),
        "endpoint": cfg.get("endpoint", ""),
    }


@router.post("/api/device/profile")
def set_device_profile(body: dict = Body(...)):
    """Persist the chosen profile (+ optional custom endpoint) to settings.json.

    Takes effect on the next connect — the bootstrap reads device.profile.
    """
    profile = body.get("profile")
    if profile not in _PROFILE_KEYS:
        raise HTTPException(status_code=400, detail="unknown profile")
    settings = load_settings()
    dev = settings.setdefault("device", {})
    dev["profile"] = profile
    if profile == "custom_endpoint":
        dev["endpoint"] = (body.get("endpoint") or "").strip()
    logger.info("device profile set to %r", profile)
    save_settings(settings)
    return {"ok": True, "profile": profile, "endpoint": dev.get("endpoint", "")}


@router.post("/api/device/connect")
async def device_connect():
    # Bootstrap may launch an emulator and block for seconds — offload it.
    ok, reason = await asyncio.to_thread(manager.connect, True)
    return {"ok": ok, "reason": reason, "status": manager.status()}


@router.websocket("/ws/device")
async def device_stream(ws: WebSocket):
    await ws.accept()

    # Parse desired FPS from query (?fps=N), clamped.
    try:
        fps = int(ws.query_params.get("fps", DEFAULT_FPS))
    except (TypeError, ValueError):
        fps = DEFAULT_FPS
    fps = max(MIN_FPS, min(MAX_FPS, fps))
    interval = 1.0 / fps

    logger.info("Device stream client connected (fps=%s)", fps)
    try:
        while True:
            jpeg = await asyncio.to_thread(manager.capture_jpeg, 70)
            if jpeg is None:
                # Not connected / capture failed — tell the client, back off.
                await ws.send_json({"type": "no_frame", "reason": manager.last_reason})
                await asyncio.sleep(0.5)
                continue
            await ws.send_bytes(jpeg)
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        logger.info("Device stream client disconnected")
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Device stream error: %s", e)
        try:
            await ws.close()
        except Exception:
            pass
