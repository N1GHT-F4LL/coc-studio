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

## Setup môi trường (QUAN TRỌNG)
- Python **3.14.5**, venv riêng tại `d:\coc-studio\.venv`
- Deps đã cài trong venv: fastapi, uvicorn[standard], websockets, opencv-python,
  numpy, pure-python-adb. **CHƯA cài `easyocr`** (nặng, ~vài phút).
- Chạy backend (từ thư mục `backend`):
  `..\.venv\Scripts\python.exe main.py` → http://127.0.0.1:8000
- Endpoints sống: `/api/health`, `/api/settings` (GET/PUT), `/api/device/status`,
  `/api/device/connect` (POST), `/ws/device?fps=4`

## Tiếp theo: Milestone 2 — engine + registry + executor
- Tạo `backend/engine/{context,registry,graph,executor}.py` và `backend/blocks/*.py`
- **Executor tổng quát hóa vòng topo-order** trong `backend/screens/battle_screen.py`
  hàm `_slot_deploy` (~dòng 95–214): gom node "ready" theo `after`, guard cycle, dispatch.
- Port 5–6 block CoC lớn wrap `screens/` (collect_resources, find_match, deploy,
  request_clan_troops, return_home) + vài primitive (tap, wait_template).
- Chạy 1 graph tuyến tính hardcoded qua REST, so parity với `run_bot` cũ trong
  `d:\coc-tools\coc_bot\main.py`.
- **M2 CẦN cài easyocr trước:** `..\.venv\Scripts\python.exe -m pip install "easyocr>=1.6.0"`
  (block OCR/loot mới chạy được; connect ở M1 không cần vì `warmup_ocr` chưa gọi).

Milestone sau: M3 frontend React Flow · M4 run+debug WS · M5 typed data edges + if/loop ·
M6 asset studio + migrator scenario cũ (`Thrower.json`).

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
