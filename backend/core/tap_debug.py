"""Tap debug recorder.

Opt-in only. Capturing screenshots around every tap is expensive, but it gives
the evidence needed to diagnose missclicks: requested point, jittered point,
label, and optional post-tap frame.
"""
import json
import os
from datetime import datetime

import cv2


def cfg(settings: dict | None) -> dict:
    return ((settings or {}).get("tap_debug") or {})


def enabled(settings: dict | None) -> bool:
    return bool(cfg(settings).get("enabled", False))


def after_delay(settings: dict | None) -> float:
    return float(cfg(settings).get("after_delay", 0.0) or 0.0)


def capture_after(settings: dict | None) -> bool:
    return bool(cfg(settings).get("capture_after", False))


def out_dir(settings: dict | None) -> str:
    path = str(cfg(settings).get("debug_dir") or os.path.join("logs", "tap_debug"))
    os.makedirs(path, exist_ok=True)
    return path


def max_per_run(settings: dict | None) -> int:
    return int(cfg(settings).get("max_per_run", 300) or 300)


def save(frame, requested, actual, label, settings, after_frame=None, meta=None) -> str | None:
    if frame is None:
        return None
    canvas = frame.copy()
    rx, ry = int(requested[0]), int(requested[1])
    ax, ay = int(actual[0]), int(actual[1])
    cv2.drawMarker(canvas, (rx, ry), (0, 200, 255), markerType=cv2.MARKER_CROSS,
                   markerSize=30, thickness=2)
    cv2.circle(canvas, (ax, ay), 22, (0, 255, 0), 2)
    cv2.line(canvas, (rx, ry), (ax, ay), (0, 180, 255), 2)
    text = f"tap {label or ''} requested=({rx},{ry}) actual=({ax},{ay})"
    cv2.putText(canvas, text[:150], (18, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.75,
                (0, 255, 0), 2, cv2.LINE_AA)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    base = os.path.join(out_dir(settings), f"tap_{ts}")
    img_path = base + ".jpg"
    cv2.imwrite(img_path, canvas)
    if after_frame is not None:
        cv2.imwrite(base + "_after.jpg", after_frame)
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump({
            "label": label,
            "requested": [rx, ry],
            "actual": [ax, ay],
            "meta": meta or {},
            "image": os.path.basename(img_path),
            "after_image": os.path.basename(base + "_after.jpg") if after_frame is not None else None,
        }, f, indent=2)
    return img_path
