"""Experimental local AI endpoints.

These endpoints are for calibrating local VLM pointing without building a graph.
They are disabled by default through settings.local_ai.enabled=false.
"""
from fastapi import APIRouter, Body, HTTPException

from core.local_vlm import locate_point, save_debug
from core.troop_dataset import capture_sample
from core.troop_recognition import recognize_bar, save_debug as save_troop_debug
from core.troop_yolo import detect_bar as detect_yolo_bar
from device_manager import manager, load_settings

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.post("/locate")
def locate(body: dict = Body(...)):
    target = str(body.get("target") or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="target is required")
    settings = load_settings()
    frame = manager.capture_bgr()
    if frame is None:
        raise HTTPException(status_code=409, detail="device not connected / no frame")

    point = locate_point(
        frame,
        target,
        settings,
        region=body.get("region"),
        timeout=float(body.get("timeout", 45)),
    )
    min_conf = float(body.get("min_confidence", 0.75))
    tapped = False
    if bool(body.get("tap", False)) and point.found and point.x is not None and point.y is not None and point.confidence >= min_conf:
        if manager.ui_manager is None:
            raise HTTPException(status_code=409, detail="ui manager not initialized")
        manager.ui_manager.click(
            int(point.x), int(point.y),
            label=f"api-vlm:{target}",
            meta={"confidence": point.confidence, "reason": point.reason},
        )
        tapped = True
    debug_path = save_debug(frame, target, point, settings, tapped=tapped)
    return {
        "found": bool(point.found and point.confidence >= min_conf),
        "x": point.x,
        "y": point.y,
        "confidence": point.confidence,
        "reason": point.reason,
        "tapped": tapped,
        "debug": debug_path,
    }


@router.post("/troop-bar")
def troop_bar(body: dict = Body(default={})):
    settings = load_settings()
    frame = manager.capture_bgr()
    if frame is None:
        raise HTTPException(status_code=409, detail="device not connected / no frame")
    result = recognize_bar(
        frame,
        settings,
        region=body.get("region"),
        threshold=body.get("threshold"),
        max_results=body.get("max_results"),
    )
    debug_path = save_troop_debug(frame, result, settings)
    return {**result, "debug": debug_path}


@router.post("/troop-bar/capture")
def troop_bar_capture(body: dict = Body(default={})):
    settings = load_settings()
    frame = manager.capture_bgr()
    if frame is None:
        raise HTTPException(status_code=409, detail="device not connected / no frame")
    try:
        meta = capture_sample(
            frame,
            settings,
            note=str(body.get("note") or ""),
            expected=body.get("expected") or [],
            region=body.get("region"),
            threshold=body.get("threshold"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return meta


@router.post("/troop-bar/yolo")
def troop_bar_yolo(body: dict = Body(default={})):
    settings = load_settings()
    frame = manager.capture_bgr()
    if frame is None:
        raise HTTPException(status_code=409, detail="device not connected / no frame")
    try:
        result = detect_yolo_bar(
            frame,
            settings,
            model_path=body.get("model_path"),
            region=body.get("region"),
            conf=body.get("conf"),
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    debug_path = save_troop_debug(frame, result, settings, label="troop_yolo") if result.get("ok") else None
    return {**result, "debug": debug_path}
