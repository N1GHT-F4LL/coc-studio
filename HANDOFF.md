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

## Đã xong: Milestone 4 (branch `m2-engine-registry-executor`)
Run + debug realtime qua WebSocket, đã verify END-TO-END trong browser với device thật:
- Backend `api/run_api.py`: tách `setup_and_run(graph, emit, stop_event, stream_logs)`
  (connect+OCR+ctx+`run_graph`) dùng chung; `_EmitLogHandler` gắn root logger → forward
  log của screens/core thành event `{type:"log"}` (KHÔNG sửa code screens). POST /api/run
  giờ gọi `setup_and_run` với `emit=list.append`.
- Backend `api/run_ws.py`: WS `/ws/run` — client `{cmd:"start",graph}`/`{cmd:"stop"}`.
  Chạy `run_graph` trong worker thread; event qua `asyncio.Queue` +
  `loop.call_soon_threadsafe` (thread→event-loop an toàn). Stop hợp tác + tự stop khi
  client disconnect. Dùng chung `RunController` (REST/WS không chạy chồng).
- Frontend: `run/useRunner.ts` (hook quản WS, fold event→state), `run/RunStateContext.ts`
  (nodeId→state cho highlight), `panels/RunConsole.tsx` (Run/Stop/Clear + log stream +
  vars live + status), `panels/DeviceView.tsx` (WS `/ws/device` JPEG→`<canvas>`, toggle).
  `BlockNode` đọc context → class `run-running/done/error`. App: layout center(canvas+
  RunConsole dock) | right(ParamPanel+DeviceView), bọc canvas trong RunStateContext.
- **Verify browser:** load `farm_cycle` → Run → 4 node sáng running→done (DOM
  `run-done`) · log backend thật stream live ("Tapped Attack!", bail, var-gate skip) ·
  vars `match_found:false` · done `status:ok` · DeviceView stream 1600×900 frame thật.

## Đã xong: Milestone 5 (branch `m2-engine-registry-executor`)
Typed data edges + control-flow blocks (if/loop) + validation hai đầu. Verify
END-TO-END trong browser với device thật + 38 engine unit tests.
- `engine/graph.py`: control edge `after` giờ là `str` (ordering) HOẶC
  `{from,branch}` (branch edge cho `if`). `Node.control_edges/data_sources/dep_ids`.
  `validate()` bắt cycle qua **cả control + data** (Kahn).
- `engine/executor.py`: `ready` = mọi dep (control+data) đã terminal → **data edge
  cũng ép thứ tự**. `_is_active`: node chạy nếu ≥1 control-edge active (branch khớp
  `_branch` của source) VÀ mọi data-producer completed; ngược lại **skipped** (lan
  truyền). `resolve_inputs` đổ `data_in` đè `params`. Fail-stop/on_error giữ nguyên.
- `blocks/control_blocks.py`: `if` (out then/else Trigger → trả `_branch`),
  `loop_n`/`loop_until` (chạy 1 graph đã lưu N lần / tới khi var truthy — subroutine,
  nuốt `done` lồng). `delay` cũ giữ nguyên.
- Frontend: BlockNode render Trigger-output thành **branch control-out handle**
  (then/else, có nhãn); `handleId` thêm `ctl|out|<branch>`; `serialize` branch↔`after`
  object + data↔`data_in`; ParamPanel **disable field khi input có data-edge**
  ("← from data edge"). Node thêm class `run-skipped` (mờ, viền đứt).
- **Verify browser:** `if_demo` (find_template.found → data-edge → if.cond) → Run →
  `[if] cond=False -> else`, **else(delay) run-done, then(collect) run-skipped**,
  status ok · `find_tap` (coord data-edge → tap) → coord None → tap **run-error**
  (fail-stop) · round-trip save/load giữ nguyên branch+data edges, validate sạch.
- Graph demo: `data/graphs/{farm_cycle,find_tap,if_demo}.json`.

## Setup môi trường (QUAN TRỌNG)
- Python **3.14.5**, venv riêng tại `d:\coc-studio\.venv`
- Node **v20.10**, npm **10.2.3**. Frontend deps trong `frontend/node_modules` (gitignored).
- **Chạy full app:** `cd frontend && npm run build` (ra `backend/static/`), rồi
  `cd backend && ..\.venv\Scripts\python.exe main.py` → mở http://127.0.0.1:8000/.
  Dev nóng: `npm run dev` (:5173, proxy `/api`+`/ws`→:8000) song song backend.
- **Engine tests (no device):** `cd backend && ..\.venv\Scripts\python.exe tests\test_engine.py` (38 pass).
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

## Tiếp theo: Milestone 6 — asset studio + scenario migrator (milestone cuối)
- Backend: REST `GET /api/assets?cat=` (list theo `_CAT_TO_FOLDER` cũ),
  `GET /api/assets/thumb/{rel}` (serve thumbnail từ `assets/`), `POST /api/assets/crop`
  (lưu asset từ vùng crop màn hình — port logic studio cũ ở `d:\coc-tools`).
- Migrator: convert `d:\coc-tools\coc_bot\scenarios\Thrower.json` (variants→graph,
  deploy slots→params block `deploy`) → graph JSON ở `data/graphs/`. Chạy lại, so deploy
  parity với PyQt cũ (đối chiếu `coc_bot/logs/debug/bar_deploy_*.png`).
- Frontend: Asset Studio panel (chụp từ `/ws/device`, vẽ rect crop → save asset),
  Template-param combobox dùng thumbnail + danh mục; Coord/Region picker click/draw trên
  DeviceView (port toán `dialogs.DeviceView._orig_coords` — map click→toạ độ gốc 1600×900).

Đã xong M1–M5. M6 là milestone cuối của plan (`resilient-herding-scott.md`).

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
