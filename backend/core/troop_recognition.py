"""Troop/spell/siege bar recognition diagnostics.

This is a deterministic recognizer built on the existing asset cache. It scans
the visible battle troop bar once and reports the best matching unit icons. It
is meant to produce evidence for missclicks and a bootstrap dataset for a later
custom YOLO/classifier model.
"""
import json
import os
from datetime import datetime

import cv2

from core.vision import vision

UNIT_PREFIXES = (
    "units/troops/",
    "units/super_troops/",
    "units/spells/",
    "units/siege/",
    "units/heroes/",
)
SLOT_ICON_SCALES = (0.50, 0.60, 0.70, 0.80, 0.90, 1.00, 1.10, 1.20)


def cfg(settings: dict | None) -> dict:
    return ((settings or {}).get("troop_recognition") or {})


def _bar_region(settings: dict | None, region=None):
    if region and len(region) == 4:
        return [int(v) for v in region]
    deploy = ((settings or {}).get("attack") or {}).get("deploy") or {}
    return [int(v) for v in deploy.get("troop_bar_region", [0, 730, 1600, 910])]


def _asset_keys(settings: dict | None):
    include = cfg(settings).get("asset_prefixes") or UNIT_PREFIXES
    out = []
    for key in vision.cache.keys():
        if any(str(key).startswith(p) for p in include):
            out.append(key)
    return sorted(set(out))


def _kind(key: str) -> str:
    if "/spells/" in key:
        return "spell"
    if "/siege/" in key:
        return "siege"
    if "/heroes/" in key:
        return "hero"
    return "troop"


def recognize_bar(screen, settings: dict | None, region=None, threshold=None, max_results=None):
    if screen is None:
        return {"detections": [], "region": None}
    h, w = screen.shape[:2]
    x1, y1, x2, y2 = _bar_region(settings, region)
    x1 = max(0, min(w - 1, x1)); x2 = max(1, min(w, x2))
    y1 = max(0, min(h - 1, y1)); y2 = max(1, min(h, y2))
    if x2 <= x1 or y2 <= y1:
        return {"detections": [], "region": [x1, y1, x2, y2]}

    threshold = float(threshold if threshold is not None else cfg(settings).get("threshold", 0.48))
    max_results = int(max_results if max_results is not None else cfg(settings).get("max_results", 18))
    min_distance = int(cfg(settings).get("min_distance", 46))

    crop = screen[y1:y2, x1:x2]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    candidates = []
    for key in _asset_keys(settings):
        tpl = vision.cache.get(key)
        if tpl is None:
            continue
        score, scaled, rmap = vision._find_best_scale(
            gray, tpl, threshold=threshold, scales=SLOT_ICON_SCALES
        )
        if rmap is None or scaled is None or score < threshold:
            continue
        _, _, _, max_loc = cv2.minMaxLoc(rmap)
        th, tw = scaled.shape[:2]
        cx = int(max_loc[0] + tw // 2 + x1)
        cy = int(max_loc[1] + th // 2 + y1)
        candidates.append({
            "key": key,
            "name": key.rsplit("/", 1)[-1],
            "kind": _kind(key),
            "score": float(score),
            "x": cx,
            "y": cy,
            "box": [int(max_loc[0] + x1), int(max_loc[1] + y1), int(max_loc[0] + tw + x1), int(max_loc[1] + th + y1)],
        })

    # NMS by slot center. Keep strongest class per physical slot.
    selected = []
    for det in sorted(candidates, key=lambda d: d["score"], reverse=True):
        if any((det["x"] - s["x"]) ** 2 + (det["y"] - s["y"]) ** 2 < min_distance ** 2 for s in selected):
            continue
        selected.append(det)
        if len(selected) >= max_results:
            break

    selected.sort(key=lambda d: d["x"])
    return {"detections": selected, "region": [x1, y1, x2, y2], "threshold": threshold}


def save_debug(screen, result: dict, settings: dict | None, label="troop_bar") -> str | None:
    if screen is None:
        return None
    path = str(cfg(settings).get("debug_dir") or os.path.join("logs", "troop_recognition"))
    os.makedirs(path, exist_ok=True)
    out = screen.copy()
    region = result.get("region")
    if region:
        x1, y1, x2, y2 = [int(v) for v in region]
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 180, 255), 2)
    for det in result.get("detections", []):
        bx1, by1, bx2, by2 = [int(v) for v in det["box"]]
        cv2.rectangle(out, (bx1, by1), (bx2, by2), (0, 255, 0), 2)
        txt = f"{det['name']} {det['score']:.2f}"
        cv2.putText(out, txt[:36], (bx1, max(18, by1 - 5)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, (0, 255, 0), 2, cv2.LINE_AA)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    base = os.path.join(path, f"{label}_{ts}")
    cv2.imwrite(base + ".jpg", out)
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    return base + ".jpg"
