"""Experimental local AI endpoints.

These endpoints are for calibrating local VLM pointing without building a graph.
They are disabled by default through settings.local_ai.enabled=false.
"""
from fastapi import APIRouter, Body, HTTPException
import logging

from core.local_vlm import locate_point, save_debug
from core.troop_dataset import capture_sample
from core.perception import detect_troop_bar
from core.troop_recognition import recognize_bar, save_debug as save_troop_debug
from core.troop_yolo import detect_bar as detect_yolo_bar
from device_manager import manager, load_settings

router = APIRouter(prefix="/api/ai", tags=["ai"])
logger = logging.getLogger(__name__)


@router.post("/locate")
def locate(body: dict = Body(...)):
    target = str(body.get("target") or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="target is required")
    settings = load_settings()
    logger.info("[AI] locate target=%r tap=%s", target, bool(body.get("tap", False)))
    frame = manager.capture_bgr()
    if frame is None:
        logger.warning("[AI] locate failed: no frame")
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
    logger.info("[AI] locate result target=%r found=%s conf=%.2f tapped=%s debug=%s reason=%s",
                target, bool(point.found and point.confidence >= min_conf), point.confidence,
                tapped, debug_path, point.reason)
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
    logger.info("[AI] troop-bar scan threshold=%s", body.get("threshold"))
    frame = manager.capture_bgr()
    if frame is None:
        logger.warning("[AI] troop-bar scan failed: no frame")
        raise HTTPException(status_code=409, detail="device not connected / no frame")
    result = recognize_bar(
        frame,
        settings,
        region=body.get("region"),
        threshold=body.get("threshold"),
        max_results=body.get("max_results"),
    )
    debug_path = save_troop_debug(frame, result, settings)
    logger.info("[AI] troop-bar result count=%d debug=%s region=%s",
                len(result.get("detections") or []), debug_path, result.get("region"))
    return {**result, "debug": debug_path}


@router.post("/troop-bar/capture")
def troop_bar_capture(body: dict = Body(default={})):
    settings = load_settings()
    logger.info("[AI] troop-bar capture note=%r expected=%s", body.get("note"), body.get("expected"))
    frame = manager.capture_bgr()
    if frame is None:
        logger.warning("[AI] troop-bar capture failed: no frame")
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
        logger.warning("[AI] troop-bar capture failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    logger.info("[AI] troop-bar capture saved sample=%s detections=%d overlay=%s",
                meta.get("sample_id"), len(meta.get("detections") or []),
                (meta.get("files") or {}).get("overlay"))
    return meta


@router.post("/troop-bar/yolo")
def troop_bar_yolo(body: dict = Body(default={})):
    settings = load_settings()
    logger.info("[AI] troop-bar YOLO conf=%s model=%r", body.get("conf"), body.get("model_path"))
    frame = manager.capture_bgr()
    if frame is None:
        logger.warning("[AI] troop-bar YOLO failed: no frame")
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
        logger.warning("[AI] troop-bar YOLO failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    debug_path = save_troop_debug(frame, result, settings, label="troop_yolo") if result.get("ok") else None
    if result.get("ok"):
        logger.info("[AI] troop-bar YOLO result count=%d debug=%s model=%s",
                    len(result.get("detections") or []), debug_path, result.get("model"))
    else:
        logger.warning("[AI] troop-bar YOLO result error=%s", result.get("error"))
    return {**result, "debug": debug_path}

@router.post("/troop-bar/perception")
def troop_bar_perception(body: dict = Body(default={})):
    settings = load_settings()
    mode = body.get("mode") or ((settings.get("perception") or {}).get("troop_bar") or {}).get("mode") or "auto"
    logger.info("[AI] troop-bar perception mode=%s", mode)
    frame = manager.capture_bgr()
    if frame is None:
        logger.warning("[AI] troop-bar perception failed: no frame")
        raise HTTPException(status_code=409, detail="device not connected / no frame")
    result = detect_troop_bar(
        frame,
        settings,
        mode=mode,
        region=body.get("region"),
        conf=body.get("conf"),
        threshold=body.get("threshold"),
        model_path=body.get("model_path"),
    )
    debug_path = save_troop_debug(frame, result, settings, label=f"troop_perception_{result.get('source')}") if result.get("ok") else None
    logger.info("[AI] troop-bar perception source=%s count=%d debug=%s",
                result.get("source"), len(result.get("detections") or []), debug_path)
    return {**result, "debug": debug_path}
