# POPUP HANDLING ANALYSIS — Bot xử lý pop-up hệ thống & in-game như thế nào?

Ngày: 2026-10-29. Căn cứ: `extracted/pyz/main.dis.txt` (connection_popup_visible @1826, one_cycle @2237, bot_loop @2487, wait_battle_end @1928, treasure_event @1757, clan_capital @816), `extracted/pyz/boot_recovery.dis.txt`, `extracted/pyz/clan_games.{pyc,dis.txt,summary.txt}`, listing `Templates/`.

## 1. Kiến trúc 3 tầng

| Tầng | Cơ chế | Áp dụng cho |
|---|---|---|
| 1. PHÁT HIỆN | `connection_popup_visible()` — template matching đa mẫu | Popup hệ thống/network chặn toàn màn hình |
| 2. CỨU CỘ | `boot_recovery()` — **relaunch game** | Mọi popup tầng 1 (không thoát được bằng nút) |
| 3. TAP CÓ CHỦ ĐÍCH | Template của nút cụ thể → tap | Popup in-game có nút (CC Go, Treasure Continue, Clan Games OPEN/START) |
| (3b) ABORT | Log ℹ️ + bỏ qua tác vụ | Trạng thái bận/không khả dụng (Clan Games busy/finished) |

## 2. Tầng phát hiện — `connection_popup_visible()` (main.py:1826)

```python
TEMPLATE_FILES = ['Another_device.png', 'Connection_lost.png', 'Client_error!.png', 'rate_coc.png']
THRESHOLD = 0.88

def connection_popup_visible() -> bool:
    shot_path = take_screenshot('conn.png')           # adb exec-out screencap
    img = imread_unicode(shot_path, IMREAD_GRAYSCALE)
    for tmpl_name in TEMPLATE_FILES:
        tpl = imread_unicode(join(TEMPLATE_DIR, tmpl_name), GRAY)
        res = cv2.matchTemplate(img, tpl, TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(res)
        if max_val >= THRESHOLD:
            print(f'[OK] Detected “{tmpl_name}” (score={max_val:.2f})')
            return True
    return False
```

4 popup hệ thống được nhận diện: **Another device** (tài khoản bị đăng nhập chỗ khác), **Connection lost** (mất kết nối), **Client error!** (lỗi client), **rate_coc** (hộp thoại đánh giá game). Ngưỡng khắt khe 0.88 để tránh dương tính giả.

## 3. Tầng cứu hộ — `boot_recovery()` (boot_recovery.py) — RELAUNCH

```python
def boot_recovery():
    host = main.host                    # nếu rỗng → RuntimeError
    print('🔁 Restarting Clash of Clans...')
    adb shell am force-stop com.supercell.clashofclans
    adb shell monkey -p com.supercell.clashofclans -c android.intent.category.LAUNCHER 1   # relaunch
    print('⏳ Waiting 10 seconds for game to load...')
    time.sleep(10)
    print('👆 Dismissing pop-ups…')
    adb shell input tap 146 487          # đè nút dismiss của popup màn hình load
```

Chiến lược: popup hệ thống không thoát được trong game → **giết hẳn process và mở lại**; tap (146,487) sau khi load để đè nút dismiss các popup khởi động.

## 4. Điểm gọi — guard pattern (đan xen mọi bước của vòng lặp)

- **`bot_loop`** (đầu mỗi vòng, main.py:2492): `sleep(2)` → `pause_event()` → `if connection_popup_visible():` → log `Connection lost detected—recovering…` → `boot_recovery()` → `ensure_home_base()` → `tap(140, 606)` → `sleep(2)` → vòng mới.
- **`one_cycle`** (trước MỖI sub-task: prep, collect, train, request troops, CC pass...): `_check_stop()` → `pause_event().wait()` → `if connection_popup_visible():` → log `[WARN] Connection lost → recovering` → `boot_recovery()` → **return** (abort toàn bộ cycle, reset `_saved_wall_offset`/`wall_save`). Ví dụ main.py:2355-2359 trước `auto_request()`; tương tự trước 'ZOOMING OUT', trước collect, trong CC loop (`[CC] Connection lost → recovering`).
- **`wait_battle_end`** (main.py:1938, 1955): trong lúc đợi trận kết thúc, định kỳ check popup → recover giữa trận.

Ý nghĩa phân tầng: trong vòng lớn chỉ recover + tiếp tục; giữa cycle thì recover + bỏ nửa việc đang dở để vòng sau làm lại sạch sẽ.

## 5. Tầng 3 — popup in-game có nút: xử lý riêng từng loại

### 5a. Clan Capital — popup "Go" vào raid (main.py:997-1031, trong clan_capital)
Match `Clan Capital/capital_popup.png` → **tap nút Go của popup** → chụp lại `cc_after_popup.png` → `_match_color` verify (`[CC] go score=.. thr=..`). Popup chỉ là một bước trong chuỗi điều hướng, không relaunch.

### 5b. Treasure event — `treasure_event()` (main.py:1757)
```python
hammer_tmpl    = Path(TEMPLATE_DIR) / 'hammer.png'
continue_tmpl  = Path(TEMPLATE_DIR) / 'continue.png'   # dead local — không bao giờ được dùng

print('Checking if treasure event is active. . .')
shot_path = take_screenshot('treasure_event')           # lưu BASE_DIR/treasure_event (không .png)
time.sleep(0.2)
img = imread_unicode(shot_path)
ok, score, loc = _match_template(img, hammer_tmpl, region=(622, 710, 964, 809), thresh=0.8)
if ok >= 0.8:                                           # hammer có trong banner event
    print('Treasure event detected.'); print('tapping. . . ')
    for _ in range(4):
        time.sleep(0.2)
        tap(273, 643)                                   # chạm vào banner/rương event
    time.sleep(4)
    print('Treasure open successfully.')
    print('Going home. . .')
    tap(788, 751)                                       # nút Return Home
# không match → return ngay, không làm gì
```
Lưu ý: `continue.png` chỉ được định nghĩa, **không có lệnh load/tap nào dùng nó** — dead asset. Kết thúc flow là tap Return Home (788,751).

### 5c. Clan Games — module riêng `clan_games.py` (main import `run_events_open`)
Chuỗi điều hướng bằng template: `events.png` (mở Events) → `clan_games.png` (tab Clan Games) → `open_button.png`/`open_button_2.png` (nút OPEN) → `choose_game()`: chụp games.png, **scan mọi PNG trong `Templates/Clan Games/` ≥90%** để chọn task card (có **swipe/scroll** nếu không thấy — `'❌ screenshot load failed after scroll'`) → `start_CG.png`/`start_button.png`/`start_button_2.png` (nút START).
Các **trạng thái popup không có nút bấm được** → abort nhẹ nhàng, KHÔNG relaunch:
- `'ℹ️ Clan Games busy.'` (không lấy được slot)
- `'ℹ️ Clan Games inactive'`
- `'ℹ️ User already finished Clan Games.'` (match `clan_games_finished.png`)
- `'⚠️ OPEN not found – closing'`, `'⚠️ START button not found (best=)'`, `'⚠️ Events window missing'`

## 6. Tài sản không dùng (legacy) trong Templates/

`close_button_profile/setting/shield/shop.png`, `surrender_window.png`, `surrender_button.png`, `Loading_screen.png`, `clan_games_busy_1..5.png`, `continue.png` (chỉ là dead local trong `treasure_event`) — **không module nào tham chiếu** trong dis (grep toàn bộ 18 module = 0 hit) → di chỉ các phiên bản trước. `is_account_loaded.png` chỉ dùng trong `ready_villages` (đợi tài khoản Supercell ID load xong khi switch).

## 7. Đánh giá

- Triết lý thiết kế: **popup hệ thống = chết đoàn → relaunch** (đơn giản, luôn thoát được, mất ~15s); **popup game = UI thường → tap theo template**; **trạng thái bất lợi = bỏ qua + thử lại vòng sau**.
- Guard được đặt TRƯỚC MỌI sub-task (không chỉ đầu cycle) — popups nổi giữa chừng cũng bị bắt ngay bước kế tiếp.
- Điểm yếu: tap (146,487) và (140,606) là toạ độ cứng theo màn hình 1600×900; ngưỡng 0.88 cao nên popup mới về mặt hình ảnh (update game) có thể không match → bot chỉ kẹt đến guard kế tiếp rồi vẫn relaunch.
