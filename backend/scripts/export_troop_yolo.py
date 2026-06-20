"""Export captured troop-bar samples to a YOLO-style dataset.

The samples come from /api/ai/troop-bar/capture or the Device tab capture UI.
Labels are weak labels from the current recognizer detections, so review them
before training a production detector.

Run from repo root:
  .\\.venv\\Scripts\\python.exe backend\\scripts\\export_troop_yolo.py

Output:
  backend/data/troop_yolo/
    dataset.yaml
    images/train/*.jpg
    labels/train/*.txt
    review/*.jpg
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sys
from pathlib import Path

import cv2

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

DEFAULT_IN = BACKEND_DIR / "data" / "troop_samples"
DEFAULT_OUT = BACKEND_DIR / "data" / "troop_yolo"


def _load_samples(src: Path):
    for meta_path in sorted(src.glob("*/meta.json")):
        try:
            with meta_path.open("r", encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            continue
        crop = meta.get("files", {}).get("bar_crop")
        if not crop:
            continue
        crop_path = Path(crop)
        if not crop_path.is_absolute():
            crop_path = (BACKEND_DIR / crop_path).resolve()
        if crop_path.is_file():
            yield meta_path, meta, crop_path


def _class_names(samples):
    names = set()
    for _meta_path, meta, _crop in samples:
        for key in meta.get("expected") or []:
            names.add(str(key))
        for det in meta.get("detections") or []:
            if det.get("key"):
                names.add(str(det["key"]))
    return sorted(names)


def _rel_yolo_box(box, region, crop_w, crop_h):
    rx1, ry1, _rx2, _ry2 = [float(v) for v in region]
    x1, y1, x2, y2 = [float(v) for v in box]
    x1 -= rx1; x2 -= rx1
    y1 -= ry1; y2 -= ry1
    x1 = max(0.0, min(float(crop_w), x1)); x2 = max(0.0, min(float(crop_w), x2))
    y1 = max(0.0, min(float(crop_h), y1)); y2 = max(0.0, min(float(crop_h), y2))
    if x2 <= x1 or y2 <= y1:
        return None
    cx = ((x1 + x2) / 2.0) / crop_w
    cy = ((y1 + y2) / 2.0) / crop_h
    bw = (x2 - x1) / crop_w
    bh = (y2 - y1) / crop_h
    return cx, cy, bw, bh


def _draw_review(img, detections, region, class_to_id, min_score):
    out = img.copy()
    rx1, ry1, _rx2, _ry2 = [int(v) for v in region]
    for det in detections:
        key = det.get("key")
        if key not in class_to_id or float(det.get("score", 0.0)) < min_score:
            continue
        x1, y1, x2, y2 = [int(v) for v in det.get("box", [0, 0, 0, 0])]
        x1 -= rx1; x2 -= rx1; y1 -= ry1; y2 -= ry1
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(out, f"{key.rsplit('/', 1)[-1]} {float(det.get('score', 0.0)):.2f}",
                    (x1, max(16, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.48,
                    (0, 255, 0), 1, cv2.LINE_AA)
    return out


def export(src: Path, out: Path, min_score: float, val_ratio: float, seed: int):
    samples = list(_load_samples(src))
    if not samples:
        raise SystemExit(f"no samples found under {src}")
    names = _class_names(samples)
    if not names:
        raise SystemExit("samples contain no expected labels or detections")
    class_to_id = {name: i for i, name in enumerate(names)}

    random.Random(seed).shuffle(samples)
    val_n = int(round(len(samples) * val_ratio)) if len(samples) > 1 else 0

    for split in ("train", "val"):
        (out / "images" / split).mkdir(parents=True, exist_ok=True)
        (out / "labels" / split).mkdir(parents=True, exist_ok=True)
    (out / "review").mkdir(parents=True, exist_ok=True)

    exported = 0
    for idx, (meta_path, meta, crop_path) in enumerate(samples):
        split = "val" if idx < val_n else "train"
        img = cv2.imread(str(crop_path), cv2.IMREAD_COLOR)
        if img is None:
            continue
        crop_h, crop_w = img.shape[:2]
        region = meta.get("region")
        if not (region and len(region) == 4):
            continue

        stem = meta.get("sample_id") or meta_path.parent.name
        dst_img = out / "images" / split / f"{stem}.jpg"
        dst_lbl = out / "labels" / split / f"{stem}.txt"
        shutil.copyfile(crop_path, dst_img)

        lines = []
        for det in meta.get("detections") or []:
            key = det.get("key")
            if key not in class_to_id:
                continue
            if float(det.get("score", 0.0)) < min_score:
                continue
            box = _rel_yolo_box(det.get("box"), region, crop_w, crop_h)
            if box is None:
                continue
            lines.append("{} {:.6f} {:.6f} {:.6f} {:.6f}".format(class_to_id[key], *box))
        with dst_lbl.open("w", encoding="utf-8") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))

        review = _draw_review(img, meta.get("detections") or [], region, class_to_id, min_score)
        cv2.imwrite(str(out / "review" / f"{stem}.jpg"), review)
        exported += 1

    yaml_path = out / "dataset.yaml"
    with yaml_path.open("w", encoding="utf-8") as f:
        f.write(f"path: {out.as_posix()}\n")
        f.write("train: images/train\n")
        f.write("val: images/val\n")
        f.write("names:\n")
        for i, name in enumerate(names):
            f.write(f"  {i}: {name}\n")

    manifest = {
        "source": str(src),
        "output": str(out),
        "samples": exported,
        "classes": names,
        "min_score": min_score,
        "val_ratio": val_ratio,
        "note": "Weak labels from recognizer detections. Review/correct before real training.",
    }
    with (out / "manifest.json").open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=DEFAULT_IN)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--min-score", type=float, default=0.48)
    ap.add_argument("--val-ratio", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=13)
    args = ap.parse_args()
    manifest = export(args.src, args.out, args.min_score, args.val_ratio, args.seed)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
