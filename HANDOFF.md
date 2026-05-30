# HANDOFF — coc-studio (đọc cái này trước khi tiếp tục)

Trạng thái bàn giao để một session Claude mới tiếp tục các milestone.

## Dự án là gì
Web-based low-code automation builder cho Clash of Clans. Viết lại UI + engine
block-graph dạng web, **giữ nguyên `core/` + `screens/`** đã tôi luyện từ repo cũ
`d:\coc-tools` (frozen reference). Browser KHÔNG đụng ADB — backend Python (FastAPI)
làm hết; browser chỉ là bảng điều khiển/cấu hình.

Quyết định đã chốt: node-graph dataflow · CoC block-kit (không phải RPA tổng quát) ·
local web app · repo riêng `d:\coc-studio` · frontend React + React Flow + TypeScript.

**Plan đầy đủ (6 milestone):** `C:\Users\n1ghtf4ll\.claude\plans\resilient-herding-scott.md`

## Đã xong: Milestone 1 (commit `890088b`)
Backend skeleton + chứng minh tái dùng core, đã verify END-TO-END với device thật:
- `GET /api/settings` trả đúng `settings.json` thật
- `POST /api/device/connect` → bootstrap launch BlueStacks, ADB connect `127.0.0.1:5555`,
  `vision.load_assets` nạp 172 asset — core chạy KHÔNG sửa dòng nào
- `/ws/device?fps=4` → stream JPEG 1600×900 thật từ màn hình device

File đã tạo: `backend/{app_paths,device_manager,main}.py`,
`backend/api/{app,settings_api,device_api,__init__}.py`, `README.md`, `.gitignore`.

## Đã xong: Milestone 2 (commit `0a1d0ff`, branch `m2-engine-registry-executor`)
Engine block-graph tổng quát + registry + executor, đã verify END-TO-END với device thật:
- `engine/`: `registry.py` (Kind/Param/Port/BlockSpec + `@register` + REGISTRY),
  `context.py` (RuntimeContext), `graph.py` (Node/Graph + validate: dangling refs +
  Kahn cycle), `executor.py` (`run_graph` — vòng ready/completed/pending, **fail-stop**
  on_error→abort). Tổng quát hóa từ `_slot_deploy`.
- `blocks/`: 15 block. CoC: collect_resources/find_match/deploy/return_home/
  request_clan_troops (wrap `screens/`; var `match_found` gate deploy/return — cầu nối
  M5 if-edges). Primitive: wait_template/is_screen/find_template, tap/tap_template/
  swipe_line/pinch, read_number/loot_ge, delay.
- `screens/attack_screen.py`: tách `run_attack_cycle` → `find_match`/`deploy`/
  `return_home` (giữ nguyên từng câu lệnh, orchestrator mỏng). **Đây là sửa DUY NHẤT
  trong screens/.**
- API: `run_api.py` (`POST /api/run` sync worker+stop_event, `/api/run/stop`,
  `GET /api/blocks`), `graphs_api.py` (CRUD `data/graphs/`). `device_manager.ensure_ocr()`.
- `data/graphs/farm_cycle.json` mirror 1 cycle của run_bot.
- `tests/test_engine.py`: 23 check no-device PASS (topo-order/cycle/fail-stop/on_error/stop).
- **Parity device thật:** `POST /api/run farm_cycle` → status ok, 4 node topo-order đúng;
  log khớp run_attack_cycle (tap Attack → bail khi Find-a-Match vắng → var-gate no-op).

## Đã xong: Milestone 3 (branch `m2-engine-registry-executor`)
Frontend React Flow — canvas low-code editor, đã verify END-TO-END trong browser thật:
- `frontend/` Vite + React 18 + TS + `reactflow@11`. Build → `backend/static/`
  (main.py serve SPA tại `/`). Dev: `npm run dev` :5173 (proxy `/api`+`/ws`→:8000).
- `src/api/client.ts` (fetch `/api/blocks`, `/api/graphs` CRUD), `src/blocks/types.ts`
  (mirror backend spec), `src/canvas/` (BlockNode typed-handle, kindColors, handleId
  encode Kind, validation = kind-match + Kahn cycle như `engine/graph.py`), `src/graph/
  serialize.ts` (RF↔GraphDoc: control edge↔`after`, data edge↔`data_in`), `src/panels/`
  (Palette group-by-category, ParamPanel auto-form từ spec.inputs theo Kind).
- **Verify browser (Playwright):** palette load 15 block/5 category · add (cascade) ·
  **connect** control-edge drag → `after` serialize đúng · ParamPanel sửa literal
  (`coord:[300,400]`) persist · Save→`PUT /api/graphs` ghi JSON · Load `farm_cycle`
  round-trip 4 node+3 edge · backend `validate()` sạch. favicon 404 là noise vô hại.
- **Build:** `cd frontend && npm install && npm run build` (tsc --noEmit + vite, pass).

## Setup môi trường (QUAN TRỌNG)
- Python **3.14.5**, venv riêng tại `d:\coc-studio\.venv`
- Node **v20.10**, npm **10.2.3**. Frontend deps trong `frontend/node_modules` (gitignored).
- Deps đã cài trong venv: fastapi, uvicorn[standard], websockets, opencv-python,
  numpy, pure-python-adb, **easyocr 1.7.2** (M2 đã cài). `httpx` CHƯA cài (nên test
  qua urllib/curl, không dùng starlette TestClient).
- Chạy backend (từ thư mục `backend`):
  `..\.venv\Scripts\python.exe main.py` → http://127.0.0.1:8000
- Endpoints sống: `/api/health`, `/api/settings` (GET/PUT), `/api/device/status`,
  `/api/device/connect` (POST), `/ws/device?fps=4`, **`/api/blocks` (GET), `/api/run`
  (POST), `/api/run/stop` (POST), `/api/graphs[/{name}]` (CRUD)** (M2)
- Verify engine no-device: `cd backend && ..\.venv\Scripts\python.exe tests\test_engine.py`
- Chạy graph qua REST: start `main.py`, `POST /api/device/connect`, rồi `POST /api/run`
  body `{"graph": <farm_cycle.json>}` (test bằng urllib/curl, KHÔNG có httpx).

## Tiếp theo: Milestone 4 — run + debug (WebSocket realtime)
- Thêm WS `/ws/run` trong backend: client gửi `{cmd:"start", graph}` / `{cmd:"stop"}`;
  chạy `run_graph` trong worker thread, `emit` = WS sink (thay vì gom list như
  `/api/run`). **Tái dùng nguyên `run_graph` + RuntimeContext + RunController** đã có ở
  M2 (`api/run_api.py`) — chỉ đổi sink + đẩy realtime.
- Frontend: RunConsole panel (Start/Stop), nghe `/ws/run`, highlight node đang chạy
  trên canvas (set class theo event `{type:"node",id,state}`), hiển thị `vars` live +
  log stream. Executor đã emit sẵn các event này (running/done/error + done status).
- DeviceView panel: vẽ frame JPEG từ `/ws/device` (đã có ở M1) lên `<canvas>`.

Milestone sau: M5 typed data edges + if/loop/on_error branching (resolver `data_in` đã
wired sẵn trong executor; frontend đã render+validate+serialize data-edge) · M6 asset
studio + migrator scenario cũ (`Thrower.json`).

## Ràng buộc PHẢI giữ (từ coc-tools REQUIREMENT.md/CLAUDE.md)
- `core/` + `screens/` copy verbatim — KHÔNG "đơn giản hóa": BlueStacks failover trong
  `device.py`, `is_app_running` nghiêm ngặt, `is_package_installed` tri-state,
  strict multi-anchor screen detection, không `cv2.imread` trong loop.
- Engine theo triết lý **fail-stop**: block lỗi → đi theo cạnh `on_error` nếu có,
  không thì abort. Không nuốt lỗi rồi chạy tiếp với state hỏng.
- Giữ settings.json contract (device/farm/delays/jitter...).

## Lưu ý môi trường
- Subagent (Explore/Plan/general-purpose) BÁO LỖI không truy cập được model trong môi
  trường này → tự khảo sát code trực tiếp, đừng spawn agent.
- Bash tool đôi khi reset CWD giữa các call — dùng đường dẫn tuyệt đối.
- Memory của Claude keyed theo folder: mở `d:\coc-studio` sẽ KHÔNG tự nạp memory đã ghi
  cho `d:\coc-tools`. Cần thì tạo memory mới cho repo này.
