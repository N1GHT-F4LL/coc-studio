"""Local vision-language guard for experimental AI-assisted taps.

The first implementation talks to Ollama's local HTTP API. It is intentionally
optional and fail-closed: if Ollama/model/output is unavailable, callers get a
not-found result and no tap is performed.
"""
import base64
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime

import cv2

logger = logging.getLogger(__name__)


@dataclass
class VLMPoint:
    found: bool
    x: int | None = None
    y: int | None = None
    confidence: float = 0.0
    reason: str = ""
    raw: str = ""


def _cfg(settings: dict) -> dict:
    return (settings or {}).get("local_ai", {}) or {}


def enabled(settings: dict) -> bool:
    return bool(_cfg(settings).get("enabled", False))


def _ollama_url(settings: dict) -> str:
    return str(_cfg(settings).get("url") or "http://127.0.0.1:11434/api/generate")


def _model(settings: dict) -> str:
    return str(_cfg(settings).get("model") or "moondream")


def _debug_dir(settings: dict) -> str:
    path = str(_cfg(settings).get("debug_dir") or os.path.join("logs", "vlm_taps"))
    os.makedirs(path, exist_ok=True)
    return path


def _image_b64(frame) -> str:
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise ValueError("failed to encode screen")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in VLM response")
    return json.loads(m.group(0))


def locate_point(frame, target: str, settings: dict, region=None, timeout=45) -> VLMPoint:
    """Ask a local VLM for the center point of ``target`` in ``frame``.

    Expected model response:
      {"found": true, "x": 123, "y": 456, "confidence": 0.82, "reason": "..."}
    Coordinates must be in the original image pixel space.
    """
    if frame is None:
        return VLMPoint(found=False, reason="no screen")
    if not enabled(settings):
        return VLMPoint(found=False, reason="local_ai disabled")

    h, w = frame.shape[:2]
    region_text = "full image"
    if region and len(region) == 4:
        region_text = f"region x1={int(region[0])}, y1={int(region[1])}, x2={int(region[2])}, y2={int(region[3])}"

    prompt = (
        "You are controlling a Clash of Clans emulator screen. "
        f"Image size is {w}x{h}. Find the center pixel of this UI target: {target!r}. "
        f"Only consider the {region_text}. "
        "Return ONLY JSON with keys: found (boolean), x (integer), y (integer), "
        "confidence (0..1), reason (short string). If unsure, set found=false. "
        "Coordinates must use the original image pixel coordinate system."
    )
    payload = {
        "model": _model(settings),
        "prompt": prompt,
        "images": [_image_b64(frame)],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _ollama_url(settings),
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        start = time.time()
        with urllib.request.urlopen(req, timeout=float(timeout)) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        elapsed = time.time() - start
        raw = str(body.get("response") or "")
        doc = _extract_json(raw)
        found = bool(doc.get("found"))
        x = int(doc.get("x")) if doc.get("x") is not None else None
        y = int(doc.get("y")) if doc.get("y") is not None else None
        conf = float(doc.get("confidence") or 0.0)
        reason = str(doc.get("reason") or "")
        logger.info("[VLM] target=%r found=%s conf=%.2f point=(%s,%s) %.1fs %s",
                    target, found, conf, x, y, elapsed, reason)
        if found and (x is None or y is None or x < 0 or y < 0 or x >= w or y >= h):
            return VLMPoint(False, x, y, conf, "point outside image", raw)
        return VLMPoint(found, x, y, conf, reason, raw)
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, TypeError) as e:
        logger.warning("[VLM] failed for %r: %s", target, e)
        return VLMPoint(False, reason=str(e))


def save_debug(frame, target: str, point: VLMPoint, settings: dict, tapped=False) -> str | None:
    if frame is None:
        return None
    out = frame.copy()
    color = (0, 220, 0) if point.found else (0, 0, 255)
    if point.x is not None and point.y is not None:
        cv2.drawMarker(out, (int(point.x), int(point.y)), color, markerType=cv2.MARKER_CROSS,
                       markerSize=34, thickness=3)
        cv2.circle(out, (int(point.x), int(point.y)), 22, color, 2)
    label = f"{target} found={point.found} conf={point.confidence:.2f} tapped={tapped}"
    cv2.putText(out, label[:120], (20, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2, cv2.LINE_AA)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = os.path.join(_debug_dir(settings), f"vlm_{ts}.jpg")
    cv2.imwrite(path, out)
    return path
