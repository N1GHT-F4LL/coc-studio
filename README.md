# coc-studio

Web-based low-code automation builder for Clash of Clans, built on the
battle-tested vision/device/OCR core from `coc-tools`.

- **Backend** (Python / FastAPI) executes everything: ADB, screen capture,
  template matching, OCR, and the block-graph engine. It owns all state.
- **Frontend** (React + React Flow) is the configuration & debug console in
  the browser. It never touches ADB — it only talks to the backend over
  HTTP + WebSocket.

The reused `backend/core/` and `backend/screens/` are copied verbatim from
`coc-tools` (BlueStacks failover, strict app-state checks, vision cache, OCR).
Do not "simplify" them — see the upstream `REQUIREMENT.md`.

## Run (Milestone 1)

```bash
# Backend
cd backend
pip install -r requirements.txt
python main.py            # serves http://127.0.0.1:8000
```

Endpoints live now:
- `GET  /api/health`
- `GET  /api/settings`  / `PUT /api/settings`
- `GET  /api/device/status`
- `POST /api/device/connect`
- `WS   /ws/device?fps=4`  — binary JPEG frames of the live screen

Frontend (React Flow canvas) lands in Milestone 3.

## Layout

```
backend/
  core/      reused: device, vision, ocr, humanize, bootstrap, ui_manager
  screens/   reused: home / attack / battle / base screens
  assets/    reused: 172 recognition templates
  engine/    NEW: block registry, runtime context, graph executor
  blocks/    NEW: CoC block definitions (wrap core + screens)
  api/       NEW: FastAPI routers (settings, device + WS)
  data/      settings.json + graphs/
frontend/    NEW: Vite + React + TS (React Flow editor)
```

## Cơ chế runtime hiện tại (2026-11-01)

| Cơ chế | Module | Vận hành |
|---|---|---|
| Zoom-out làng | `backend/zoom_out.py` | pinch 2 ngón qua uiautomator2 (ATX agent) — chạy mỗi Run khi về làng |
| Popup hệ thống | `backend/popup_guard.py` | dò template nghiêm ngặt → relaunch app (rate 5 lần/15 phút); guard trước mọi sub-task |
| Star Bonus / Treasure | `backend/popup_guard.py` | tap Okay / rương sự kiện tự động |
| Deploy pattern | `backend/screens/battle_screen.py` + `data/scenarios/*.json` | điểm tĩnh dọc biên ngoài map (hiệu chuẩn sẵn) + jitter vị trí + burst tap (interval 0) |
| Chẩn đoán viền glow | `backend/glow_zone.py` | 7s sau khi vào trận — log drift + ảnh debug, không điều khiển deploy |
| Kẹt 3 tầng | popup restart / dump+surrender / dừng có kiểm soát | phân tầng theo `HANDOFF.md` §4 |

Tools hiệu chuẩn trong `calib/` + `backend/scripts/` — xem `HANDOFF.md` phần
"CẬP NHẬT SAU BÀN GIAO" cho quy trình và điều kiện nghiệm thu.
