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
- `GET  /api/blocks`  ·  `POST /api/run`  / `POST /api/run/stop`  ·  `WS /ws/run`
- `GET|PUT|DELETE /api/graphs[/{name}]`  ·  `GET|POST|DELETE /api/assets…`  ·  `GET|POST|DELETE /api/scenarios…`
- `GET  /api/multi_village`  ·  `PUT /api/multi_village/config`  ·  `POST /api/multi_village/{load,save,apply,delete_all}/{idx}`  ·  `GET /api/multi_village/icon/{idx}`

Frontend: React Flow canvas (Bot Builder / Attack Plan / Assets / Device /
Multi-Village / About tabs) — built into `backend/static` by `start.ps1`.

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

## Cơ chế runtime hiện tại (2026-11-19)

| Cơ chế | Module | Vận hành |
|---|---|---|
| Zoom-out làng | `backend/zoom_out.py` | pinch 2 ngón qua uiautomator2 (ATX agent) — chạy mỗi Run khi về làng |
| Zoom-out battle | `backend/screens/battle_screen.py` | `_slot_deploy` luôn zoom-out tối đa bằng u2 pinch trước hero lineup |
| Popup hệ thống | `backend/popup_guard.py` | dò template nghiêm ngặt → relaunch app (rate 5 lần/15 phút); guard trước mọi sub-task |
| Star Bonus / Treasure | `backend/popup_guard.py` | tap Okay / rương sự kiện tự động |
| Banner Treasure 2 biến thể | `backend/popup_guard.py` | `_treasure_tool` match cả `hammer.png` lẫn `rolling_pin.png` trên banner |
| Chest overlay sau attack | `backend/popup_guard.py` + `blocks/coc_blocks.py` | overlay rương pop sau battle → smash tại chỗ trong `return_home`, không restart game đè lên rương |
| Deploy pattern | `backend/screens/battle_screen.py` + `data/scenarios/*.json` | zoom-out battle → hero lineup pre-scan → **pan ×3 (verify độ trôi mỗi pass)** → thả theo pattern/line + jitter; nút **1x_to_4x detect + tap đúng 1 lần** sau dump |
| Battle-end 2 biến thể | `backend/screens/battle_screen.py` | `_battle_end_buttons` match `btn_return_home` + `claim_reward` trên cùng 1 frame → tap + log theo variant |
| Kẹt 3 tầng | popup restart / dump+surrender / **NOPROGRESS self-recovery** | 3 chu kỳ abnormal liên tiếp → boot_recovery + reset counter + **tiếp tục farm (không dừng run)**; unknown-state frame được dump vào `data/calib_debug/` |
| Train army thủ công | `backend/screens/train_screen.py` + block `ensure_troops` | train đúng variant sẽ deploy; verify = **composition card check bằng `assets/units/verify/`** (face crop từ đúng hàng card camp); army đúng → keep, không train lại |
| Multi-Village rotation | `backend/multi_village.py` + `api/multi_village_api.py` + tab **Multi-Village** | rotation Supercell ID qua desktop self-capture (thấy xuyên FLAG_SECURE), locate account **by name qua OCR**, identity check sau switch; per-village config (scenario + loot thresholds); `mv_rotation` là node đầu farm cycle |
| Chẩn đoán viền glow | `backend/glow_zone.py` | 7s sau khi vào trận — log drift + ảnh debug, không điều khiển deploy |

Tools hiệu chuẩn trong `calib/` + `backend/scripts/` — xem `HANDOFF.md` phần
"CẬP NHẬT SAU BÀN GIAO" cho quy trình và điều kiện nghiệm thu.
