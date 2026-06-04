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

## Đã xong: Milestone 6 (branch `m2-engine-registry-executor`) — MILESTONE CUỐI
Asset studio + scenario migrator. Verify END-TO-END trong browser với device thật.
- `api/assets_api.py`: `GET /api/assets/categories` (18, port `_CAT_TO_FOLDER`),
  `GET /api/assets?cat=` (list rel keys), `GET /api/assets/thumb/{rel}` (FileResponse),
  `POST /api/assets/crop` (capture `manager.capture_bgr` → crop region → ghi
  `assets/<folder>/<name>.png` → hot-load `vision.cache[name]` + `[key]`). Sanitize tên.
- `scenario_store.py` (data/scenarios/): load/list/save + `chosen_variant_nodes`
  (weighted pick, backward-compat slots). `app_paths.SCENARIOS_DIR`.
- `blocks/coc_blocks.py` Deploy: thêm param `scenario` (Text). Rỗng → settings path
  (AttackScreen.deploy cũ); có tên → load data/scenarios, pick variant, gọi
  `BattleScreen.deploy_troops` (= `_slot_deploy` không sửa → parity).
- `scripts/migrate_scenario.py`: scenario coc-tools cũ → `data/scenarios/<name>.json`
  + graph `data/graphs/<name>_farm.json` (collect→find_match→deploy(scenario)→return).
  Đã chạy cho `Thrower` (1 variant, 22 deploy nodes).
- Frontend: ParamPanel Template→**combobox 172 asset + thumbnail** (`/api/assets/thumb`),
  Coord/Region→nút **Pick** (click/drag trên DeviceView → toạ độ gốc). DeviceView thêm
  **Capture asset** (drag rect → form tên+category → `POST /crop`) + picker mode.
- **Verify browser:** migrate Thrower → load `Thrower_farm` render đúng (deploy
  scenario=Thrower) · Template combo 173 opt → thumbnail load 180×175 · coord pick
  click giữa canvas → `798,448`(≈1600/2,900/2) · asset studio drag→save
  `units/troops/...` ghi PNG ra đĩa + vào list + thumb 200.

**TẤT CẢ M1–M6 ĐÃ XONG.** Plan `resilient-herding-scott.md` hoàn tất.

## Setup môi trường (QUAN TRỌNG)
- Python **3.14.5**, venv riêng tại `d:\coc-studio\.venv`
- Node **v20.10**, npm **10.2.3**. Frontend deps trong `frontend/node_modules` (gitignored).
- **Chạy 1 phát cả 2 (khuyên dùng):** `.\start.ps1` ở gốc repo → build frontend +
  start backend serve SPA tại http://127.0.0.1:8000 (tự mở browser). Hot-reload:
  `.\start.ps1 -Dev` → backend :8000 + Vite :5173 song song (Ctrl+C dừng, backend tự tắt).
  (start.ps1 KHÔNG đặt ErrorActionPreference=Stop — uvicorn log ra stderr, sẽ bị PS coi
  là lỗi terminating và giết server.)
- Thủ công: `cd frontend && npm run build`, rồi `cd backend && ..\.venv\Scripts\python.exe main.py`.
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

## Fix sau M6 (commit `651d3d5`) — farm chạy được END-TO-END
Triệu chứng user: "bot chạy nhưng không farm". Gốc rễ: farm graph thiếu khung
startup/recovery của `run_bot` → bot thao tác trên màn sai (BlueStacks store), tap
nhầm "Attack!" rồi bail "Find a Match not found". `device_manager.connect()` chỉ
bootstrap ADB+assets, KHÔNG đưa CoC ra trước.
- Thêm block **`ensure_home`** (wrap `device.ensure_coc_ready` + detect home + đóng
  popup + pinch zoom-out + restart-game recovery như `coc_bot/main.py`).
- `farm_cycle.json`: prepend `ensure_home`; deploy `scenario="Thrower"` (scenario rỗng
  → settings path hỏng → "No troop slots matched"). `farm_loop.json` = `loop_n(farm_cycle,50)`
  farm liên tục (stop từ run console). Migrator cũng sinh graph có `ensure_home`.
- `main.py`: ép stdout/stderr UTF-8 (deploy log có `→`,`×` lỗi cp1252 trên console Win).
- **Verify device thật:** full cycle chạy hết — ensure_home về home, collect 3 mỏ, tap
  Attack→Find a Match, OCR loot (conf 1.00), đạt threshold, **deploy 22 node Thrower qua
  `_slot_deploy` (deploy parity ✓)**, return home. → Cách dùng: build FE, `main.py`,
  `POST /api/device/connect`, rồi Run `farm_cycle` (1 vòng) hoặc `farm_loop` (liên tục).

## Army training — ensure_troops — XONG (verify e2e 3/3 trên device thật)
Block `ensure_troops` train army thủ công khớp scenario. Code: `screens/train_screen.py`
(TrainScreen: open_roster/close_roster/clear_section/train_unit/_locate_in_roster),
block + helper trong `blocks/coc_blocks.py`. Branch `m2-engine-registry-executor`.
- **Cơ chế match:** mỗi section (troops/spells/sieges) tap panel "Tap to edit" → roster
  SÁNG → match FACE-only template `units/roster/<name>.png` (KHÔNG dùng `units/troops/
  <name>` vì có badge/level → chỉ ~0.5; face crop từ roster sáng match ~1.0) → tap N lần.
  Không thấy thì scroll roster rồi thử lại. Roster face: archer/healer/rage/thrower/totem/
  **log_launcher** (đủ cho scenario Thrower).
- **Switch section IN-PLACE (không re-enter):** mở army **1 lần** rồi mỗi section
  `clear_section → open_roster → train → close_roster`. 2 điều then chốt (đã đo trên
  device, từng làm flaky):
  1. `clear_section` xong màn về **My Army overview, roster ĐÓNG** (KHÔNG để roster mở như
     giả định cũ) → phải **LUÔN** `open_roster` sau clear.
  2. Trước khi sang section sau phải **`close_roster`** = tap chỗ trống `(800,130)` để thu
     roster đang mở (KHÔNG dùng X menu — X bị đẩy khuất khi roster mở). Để roster cũ mở →
     section sau không switch được → "not found".
  Đo xác nhận: với army fresh, open_roster mỗi section → archer 0.96 / rage 1.0 /
  log_launcher 1.0, đều còn ở army screen.
- **Reconnect-popup recovery (mới):** helper `dismiss_reconnect_popup(ui, logger)` trong
  `coc_blocks.py` bắt 2 popup CoC làm hỏng run: `icons/status/reload_game` ("Anyone there?/
  inactivity" → RELOAD GAME) và `icons/status/reload_connection` ("Connection lost/Another
  device is connecting" → RELOAD). Popup thứ 2 nổ GIỮA run khi **>1 client đọc màn cùng lúc**
  (browser DeviceView stream trong lúc chạy). ensure_home gọi nó trong poll_home; ensure_troops
  gọi qua `ensure_army()` trước mỗi section (dismiss + reopen army nếu bị đá về làng).
- **siege panel coord (1420,478); spell panel (1072,470)** (tap giữa content-frame, không
  phải mép "Tap to edit"). `back_home(max_taps=4)` tap X tới khi rời army.
- **Verify e2e device thật (graph `data/graphs/train_only.json` = ensure_home→ensure_troops
  Thrower, không deploy nên không tiêu army):** chạy nhiều lần cả 2 path (army rỗng→panel,
  army đầy→clear) đều **3/3 sạch**: troops 352/352 (archer×12,healer×6,thrower×16), spells
  11/11 (rage×2,totem×7), siege log_launcher×1 @(1265,660). Có run popup "Connection lost"
  nổ → `[reconnect] reload_connection popup — tapping reload` → tự phục hồi → vẫn 3/3.
- **Lưu ý:** `backend/_calib/` (ảnh dò toạ độ) đã vào `.gitignore`. Scripts diag tạm
  (`diag_*.py`, `make_log_launcher_face.py`) đã xóa.

## Post-v1 (plan §Open, chưa làm)
- Subroutine block (graph-as-block) đầy đủ — hiện loop dùng `graph_ref`.
- minitouch/scrcpy HID cho swipe mượt; đóng gói desktop app.

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
