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

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from device_manager import manager

logger = logging.getLogger(__name__)
router = APIRouter()

# Default stream cadence. The client may override via ?fps= on the WS URL.
DEFAULT_FPS = 4
MIN_FPS = 1
MAX_FPS = 15


@router.get("/api/device/status")
def device_status():
    return manager.status()


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
