r"""Apply reviewed labels to captured troop-bar samples.

The capture metadata starts with weak template detections. This script lets you
replace their class keys with a reviewed left-to-right class list while keeping
the detected boxes. Export then prefers `meta.labels` over weak detections.

Examples:
  .\.venv\Scripts\python.exe backend\scripts\label_troop_sample.py --latest --classes thrower,healer,rage,totem,log_launcher
  .\.venv\Scripts\python.exe backend\scripts\label_troop_sample.py --sample 20260621_120000_event --classes event,empty,king
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = BACKEND_DIR / "data" / "troop_samples"
DEFAULT_CLASSES = BACKEND_DIR / "data" / "troop_yolo_classes.json"

def _load_class_config(path: Path):
    if not path.is_file():
        return {}, []
    with path.open("r", encoding="utf-8") as f:
        doc = json.load(f)
    aliases = {str(k): str(v) for k, v in (doc.get("aliases") or {}).items()}
    classes = [str(x) for x in doc.get("classes") or []]
    return aliases, classes

def _canonical(raw: str, aliases: dict[str, str], classes: list[str]) -> str:
    key = str(raw or "").strip()
    if not key:
        raise SystemExit("empty class label")
    canon = aliases.get(key, aliases.get(key.rsplit("/", 1)[-1], key))
    if classes and canon not in classes:
        raise SystemExit(f"unknown class {key!r} -> {canon!r}; add it to {DEFAULT_CLASSES}")
    return canon

def _sample_dirs(root: Path):
    return sorted([p for p in root.iterdir() if (p / "meta.json").is_file()], key=lambda p: p.name)

def _pick_sample(root: Path, sample: str | None, latest: bool):
    dirs = _sample_dirs(root)
    if not dirs:
        raise SystemExit(f"no samples under {root}")
    if latest:
        return dirs[-1]
    if not sample:
        raise SystemExit("pass --sample <id> or --latest")
    matches = [p for p in dirs if p.name == sample or p.name.startswith(sample)]
    if len(matches) != 1:
        raise SystemExit(f"sample match count={len(matches)} for {sample!r}")
    return matches[0]

def relabel(meta_path: Path, labels: list[str], aliases: dict[str, str], classes: list[str], min_score: float):
    with meta_path.open("r", encoding="utf-8") as f:
        meta = json.load(f)
    dets = [d for d in meta.get("detections") or [] if float(d.get("score", 1.0)) >= min_score]
    dets.sort(key=lambda d: int(d.get("x", 0)))
    if len(labels) != len(dets):
        raise SystemExit(f"label count {len(labels)} != detection count {len(dets)}; sample={meta.get('sample_id')}")
    reviewed = []
    for det, label in zip(dets, labels):
        row = dict(det)
        row["key"] = _canonical(label, aliases, classes)
        row["reviewed"] = True
        reviewed.append(row)
    meta["labels"] = reviewed
    meta["label_source"] = "manual"
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    return meta

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--sample", default="")
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--classes", required=True, help="Comma-separated class labels, left-to-right over current detections")
    ap.add_argument("--class-file", type=Path, default=DEFAULT_CLASSES)
    ap.add_argument("--min-score", type=float, default=0.0)
    args = ap.parse_args()

    aliases, known = _load_class_config(args.class_file)
    sample_dir = _pick_sample(args.root, args.sample or None, args.latest)
    labels = [x.strip() for x in args.classes.split(",") if x.strip()]
    meta = relabel(sample_dir / "meta.json", labels, aliases, known, args.min_score)
    print(json.dumps({
        "sample_id": meta.get("sample_id"),
        "labels": [x["key"] for x in meta.get("labels") or []],
        "meta": str(sample_dir / "meta.json"),
    }, indent=2))

if __name__ == "__main__":
    sys.exit(main())
