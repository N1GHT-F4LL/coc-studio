"""Optional YOLO troop-bar detector runtime.

Uses Ultralytics only when called. This keeps normal startup light and lets the
experiment run without installing extra packages until a trained model exists.
"""
import os
from functools import lru_cache


def cfg(settings: dict | None) -> dict:
    return ((settings or {}).get("troop_yolo") or {})


def _bar_region(settings: dict | None, region=None):
    if region and len(region) == 4:
        return [int(v) for v in region]
    deploy = ((settings or {}).get("attack") or {}).get("deploy") or {}
    return [int(v) for v in deploy.get("troop_bar_region", [0, 730, 1600, 910])]


@lru_cache(maxsize=2)
def _load_model(path: str):
    try:
        from ultralytics import YOLO
    except ImportError as e:
        raise RuntimeError("missing optional dependency: pip install ultralytics") from e
    return YOLO(path)


def detect_bar(screen, settings: dict | None, model_path=None, region=None, conf=None):
    if screen is None:
        return {"ok": False, "error": "no screen", "detections": [], "region": None}
    path = str(model_path or cfg(settings).get("model_path") or "").strip()
    if not path:
        return {"ok": False, "error": "troop_yolo.model_path is empty", "detections": [], "region": None}
    if not os.path.isfile(path):
        return {"ok": False, "error": f"model not found: {path}", "detections": [], "region": None}

    h, w = screen.shape[:2]
    x1, y1, x2, y2 = _bar_region(settings, region)
    x1 = max(0, min(w - 1, x1)); x2 = max(1, min(w, x2))
    y1 = max(0, min(h - 1, y1)); y2 = max(1, min(h, y2))
    if x2 <= x1 or y2 <= y1:
        return {"ok": False, "error": "invalid region", "detections": [], "region": [x1, y1, x2, y2]}

    crop = screen[y1:y2, x1:x2]
    conf = float(conf if conf is not None else cfg(settings).get("conf", 0.35))
    model = _load_model(path)
    result = model.predict(crop, conf=conf, verbose=False)[0]
    names = result.names or {}
    detections = []
    for box in result.boxes:
        xyxy = box.xyxy[0].tolist()
        cls_id = int(box.cls[0])
        score = float(box.conf[0])
        bx1, by1, bx2, by2 = [int(v) for v in xyxy]
        key = str(names.get(cls_id, cls_id))
        detections.append({
            "key": key,
            "name": key.rsplit("/", 1)[-1],
            "kind": "unit",
            "score": score,
            "x": int((bx1 + bx2) / 2 + x1),
            "y": int((by1 + by2) / 2 + y1),
            "box": [bx1 + x1, by1 + y1, bx2 + x1, by2 + y1],
            "class_id": cls_id,
        })
    detections.sort(key=lambda d: d["x"])
    return {"ok": True, "detections": detections, "region": [x1, y1, x2, y2], "conf": conf, "model": path}
