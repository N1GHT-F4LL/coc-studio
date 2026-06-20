"""Train/export a troop-bar YOLO model from exported samples.

Requires optional dependency:
  pip install ultralytics

Typical flow from repo root:
  .\\.venv\\Scripts\\python.exe backend\\scripts\\export_troop_yolo.py
  .\\.venv\\Scripts\\python.exe backend\\scripts\\train_troop_yolo.py --epochs 80 --imgsz 640
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA = BACKEND_DIR / "data" / "troop_yolo" / "dataset.yaml"
DEFAULT_PROJECT = BACKEND_DIR / "data" / "troop_yolo" / "runs"


def train(args):
    try:
        from ultralytics import YOLO
    except ImportError as e:
        raise SystemExit("missing optional dependency: pip install ultralytics") from e

    data = Path(args.data)
    if not data.is_file():
        raise SystemExit(f"dataset.yaml not found: {data}")

    model = YOLO(args.model)
    result = model.train(
        data=str(data),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=str(args.project),
        name=args.name,
        exist_ok=args.exist_ok,
    )

    save_dir = Path(getattr(result, "save_dir", Path(args.project) / args.name))
    best = save_dir / "weights" / "best.pt"
    exported = None
    if args.export_onnx:
        export_model = YOLO(str(best if best.is_file() else args.model))
        exported = export_model.export(format="onnx", imgsz=args.imgsz, simplify=args.simplify)

    summary = {
        "run_dir": str(save_dir),
        "best_pt": str(best),
        "onnx": str(exported) if exported else None,
    }
    print(json.dumps(summary, indent=2))
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--model", default="yolov8n.pt")
    ap.add_argument("--epochs", type=int, default=80)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--device", default=None)
    ap.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    ap.add_argument("--name", default="troop_bar")
    ap.add_argument("--exist-ok", action="store_true")
    ap.add_argument("--export-onnx", action="store_true", default=True)
    ap.add_argument("--no-export-onnx", action="store_false", dest="export_onnx")
    ap.add_argument("--simplify", action="store_true")
    train(ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
