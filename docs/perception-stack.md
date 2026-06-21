# Perception stack

Goal: keep bot actions deterministic while improving recognition quality.

## Runtime layers

1. `core.perception.detect_troop_bar(...)`
   - `mode=auto`: use YOLO when `settings.troop_yolo.model_path` points to an existing model, otherwise use template recognition.
   - `mode=yolo`: require YOLO and return `ok=false` when no model is configured.
   - `mode=template`: force existing template recognizer.
   - Normalizes every detection with `kind`, `status`, `role`, and `slot`.

2. Event troop dump
   - Still uses color occupancy to find unknown/event leftovers because new event troops may not exist in the model yet.
   - Uses `core.perception` to identify protected hero/siege slots and skip them.
   - Tunables are exposed on the `deploy` block: detector mode, taps per slot, max rounds, color threshold, skip hero/siege.

3. Future screen state
   - Add the same boundary for `detect_screen_state(frame)` before replacing action preconditions.

## Dataset flow

1. Device tab: capture troop-bar samples.
2. Export weak labels:
   ```powershell
   .\.venv\Scripts\python.exe backend\scripts\export_troop_yolo.py
   ```
3. Review `backend/data/troop_yolo/review/` before production training. If a sample is mislabeled, relabel it left-to-right over the detected boxes:
   ```powershell
   .\.venv\Scripts\python.exe backend\scripts\label_troop_sample.py --latest --classes thrower,healer,rage,totem,log_launcher
   ```
   The canonical class list and aliases live in `backend/data/troop_yolo_classes.json`.
4. Export again. Manual `meta.labels` now override weak detections.
5. Train:
   ```powershell
   .\.venv\Scripts\python.exe backend\scripts\train_troop_yolo.py --epochs 80 --imgsz 640
   ```
6. Set `backend/data/settings.json`:
   ```json
   "troop_yolo": { "model_path": "data/troop_yolo/runs/troop_bar/weights/best.pt", "conf": 0.35 }
   ```

## Diagnostics

- Template recognizer: `POST /api/ai/troop-bar`
- Raw YOLO: `POST /api/ai/troop-bar/yolo`
- Normalized perception: `POST /api/ai/troop-bar/perception` with body `{ "mode": "auto" }`

Use the normalized endpoint to verify `role=protected` for heroes/sieges before enabling event troop dumping on a real farm run.
