"""Troop-recognition sample capture.

Stores full screenshots, bar crops, recognizer overlays and metadata so we can
build a real detector/classifier dataset from the user's emulator instead of
guessing thresholds.
"""
import json
import os
import re
from datetime import datetime

import cv2

from core.troop_recognition import recognize_bar, save_debug as save_recognition_debug


def cfg(settings: dict | None) -> dict:
    return ((settings or {}).get("troop_dataset") or {})


def root_dir(settings: dict | None) -> str:
    path = str(cfg(settings).get("root_dir") or os.path.join("data", "troop_samples"))
    os.makedirs(path, exist_ok=True)
    return path


def _slug(raw: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "_", (raw or "").strip())
    return value.strip("_")[:80] or "sample"


def capture_sample(screen, settings: dict | None, note="", expected=None, region=None, threshold=None):
    if screen is None:
        raise ValueError("no screen")

    result = recognize_bar(screen, settings, region=region, threshold=threshold)
    reg = result.get("region")
    if not reg:
        raise ValueError("invalid troop bar region")
    x1, y1, x2, y2 = [int(v) for v in reg]
    crop = screen[y1:y2, x1:x2].copy()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    sample_id = f"{ts}_{_slug(note)}"
    out_dir = os.path.join(root_dir(settings), sample_id)
    os.makedirs(out_dir, exist_ok=True)

    full_path = os.path.join(out_dir, "screen.jpg")
    crop_path = os.path.join(out_dir, "bar_crop.jpg")
    cv2.imwrite(full_path, screen)
    cv2.imwrite(crop_path, crop)
    overlay_path = save_recognition_debug(screen, result, settings, label=f"sample_{sample_id}")

    meta = {
        "sample_id": sample_id,
        "note": note,
        "expected": expected or [],
        "region": reg,
        "threshold": result.get("threshold"),
        "detections": result.get("detections", []),
        "files": {
            "screen": full_path,
            "bar_crop": crop_path,
            "overlay": overlay_path,
        },
    }
    meta_path = os.path.join(out_dir, "meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    meta["files"]["meta"] = meta_path
    return meta
