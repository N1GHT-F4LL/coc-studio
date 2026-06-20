# Local VLM Guard Experiment

Branch: `experiment/local-vlm-guard`

Purpose: test local vision-language pointing for missclick-prone UI targets
without replacing the existing template/OCR pipeline.

## Runtime

Default config in `backend/data/settings.json` is fail-closed:

```json
"local_ai": {
  "enabled": false,
  "provider": "ollama",
  "url": "http://127.0.0.1:11434/api/generate",
  "model": "moondream",
  "debug_dir": "logs/vlm_taps"
}
```

To test locally:

```powershell
ollama pull moondream
```

Then set `local_ai.enabled=true`, restart backend, add the `VLM Tap
(experimental)` block, and use a concrete target such as `green Attack button`
or `Return Home button`.

You can test against the current connected device without editing a graph:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/ai/locate `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"target":"green Attack button","min_confidence":0.75,"tap":false}'
```

Set `tap:true` only after checking the debug overlay.

## Tap Recorder

For missclick diagnosis, enable this opt-in recorder:

```json
"tap_debug": {
  "enabled": true,
  "debug_dir": "logs/tap_debug",
  "capture_after": false,
  "after_delay": 0.25,
  "max_per_run": 300
}
```

When enabled during a graph run, every `ui_manager.click()` writes an overlay
showing requested coordinates, jittered coordinates, and an optional after-tap
frame. Keep it off for normal farming because it adds screenshots around taps.

## Troop Bar Recognition

The important diagnostic for troop missclicks is `recognize_troop_bar`. It scans
the visible battle troop bar once using the existing unit/spell/siege/hero asset
cache and writes an overlay to `logs/troop_recognition/`.

API test:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/ai/troop-bar `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"threshold":0.48}'
```

Graph test: add `Recognize Troop Bar` while on the battle screen. It returns:

- `detected`: any slot matched,
- `count`: number of visible slots matched,
- `json`: `[ { key, name, kind, score, x, y, box }, ... ]`.

Use these overlays to identify whether the current deploy misses because the
asset is wrong, the bar region is wrong, or two troop icons score too closely.
If template diagnostics remain ambiguous, train a custom YOLO/classifier on the
saved bar crops/overlays and replace this recognizer behind the same API shape.

To capture a reusable training sample:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/ai/troop-bar/capture `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"note":"thrower attack bar","expected":["units/troops/thrower","units/spells/rage"]}'
```

This saves a full screenshot, bar crop, overlay, and `meta.json` under
`backend/data/troop_samples/` (gitignored). The graph block `Capture Troop
Sample` does the same from a running graph.

After collecting samples, export a weak-label YOLO dataset for review/training:

```powershell
.\.venv\Scripts\python.exe backend\scripts\export_troop_yolo.py --min-score 0.48
```

Output goes to `backend/data/troop_yolo/` (gitignored): `dataset.yaml`,
`images/`, `labels/`, `review/`, and `manifest.json`. Labels are generated from
the current recognizer detections, so inspect/correct them before training.

Train a prototype detector after review/correction:

```powershell
pip install ultralytics
.\.venv\Scripts\python.exe backend\scripts\train_troop_yolo.py --epochs 80 --imgsz 640
```

Then point `troop_yolo.model_path` at `best.pt` or exported `.onnx` and test:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/ai/troop-bar/yolo `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"conf":0.35}'
```

The YOLO endpoint is optional. If `ultralytics` is missing or the model path is
empty, it returns a clear error instead of affecting existing automation.

## Safety

`vlm_tap` only taps when:

- local AI is enabled,
- the model returns valid JSON,
- the point is inside the screenshot,
- confidence is at least `min_confidence`.

Every call writes an overlay image to `logs/vlm_taps/` showing the selected
point, confidence, target text, and whether a tap happened.

## Expected Limits

This is a probe, not a production replacement. Local VLMs may produce imprecise
coordinates. Use it first for diagnostics and compare saved overlays against
actual missclicks. If it helps, the next step is to promote common targets to a
detector model such as YOLO, with VLM kept as fallback/explainer.
