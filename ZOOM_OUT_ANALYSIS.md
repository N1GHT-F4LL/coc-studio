# ZOOM-OUT ANALYSIS — Bot zoom out màn hình home base như thế nào?

Ngày: 2026-10-28. Căn cứ: `extracted/pyz/zoom_out.{pyc,dis.txt,summary.txt}`, `extracted/pyz/main.dis.txt`, `AutoHotkey/v2/zoom_out.ahk` (trên đĩa).

## 1. Cơ chế chính trong code: `zoom_out.py` (tên gốc `multi_pinch_out.py`) — uiautomator2 pinch gesture

Docstring gốc: *"Runs several pinch-in (zoom-out) gestures via UIAutomator2. If the user touches the screen at the same time (causing a SecurityException about INJECT_EVENTS), we wait briefly and retry instead of crashing."*

Tái dựng từ disassembly:

```python
import sys, time
import uiautomator2 as u2
from uiautomator2.exceptions import RPCUnknownError
import main

def _safe_pinch_in(uiobj, percent=100, steps=20, retries=5, backoff=0.35, device=None):
    delay = backoff
    for attempt in range(1, retries + 1):
        try:
            uiobj.pinch_in(percent=percent, steps=steps)   # 2 ngón gập vào giữa = zoom OUT
            return True
        except RPCUnknownError as e:
            msg = str(e)
            if ('INJECT_EVENTS' in msg or 'SecurityException' in msg
                    or 'performMultiPointerGesture' in msg):
                try:
                    if device is not None:
                        device.shell('input tap 5 5')      # chạm góc để "giải phóng" touch
                except Exception:
                    pass
            time.sleep(delay)
            delay = min(delay * 1.5, 2.0)                  # backoff luỹ thừa, trần 2s
        except Exception:
            time.sleep(delay)
            delay = min(delay * 1.5, 2.0)
    return False

def multi_zoom_out(addr=None, percent=100, steps=20, count=3, interval=0.5, retries=5, backoff=0.35):
    if addr is None:
        addr = main.host
        if not addr:
            print('No emulator host set before calling multi_zoom_out()')
            return False
    d = u2.connect(addr)          # nối ADB serial, vd 127.0.0.1:21503 (MEmu)
    root = d()                    # UiObject gốc = toàn màn hình
    any_success = False
    for i in range(count):
        ok = _safe_pinch_in(root, percent=percent, steps=steps,
                            retries=retries, backoff=backoff, device=d)
        if ok:
            any_success = True
        else:
            print('⚠️ zoom-out attempt skipped after retries (likely due to user touch).')
        if i < count - 1:
            time.sleep(interval)
    return any_success

if __name__ == '__main__':        # CLI: zoom_out.py [addr] [percent] [steps] [count] [interval]
    args = sys.argv[1:]
    addr = args[0] if len(args) > 0 else main.host
    ...
    multi_zoom_out(addr, percent, steps, count, interval)
```

Nguyên lý: trong Clash of Clans, camera zoom-out = **hai ngón gập về giữa màn hình (pinch-in gesture)**. `uiautomator2.pinch_in(percent=100, steps=20)` bơm gesture đa điểm chạm vào Android qua ATX agent (`performMultiPointerGesture`) — chạy trong hệ điều hành của giả lập qua ADB, **không mô phỏng chuột/scroll trên cửa sổ Windows**. `percent=100` = biên độ kéo tối đa, `steps=20` = 20 bước nội suy (mượt), lặp `count=3` lần cách nhau `0.5s` → zoom hết cỡ về xa nhất.

## 2. Điểm gọi trong luồng bot (`main.py` — `one_cycle`)

- `main.py:2265` — in `ZOOMING OUT . . .`, rồi `multi_zoom_out(host)` (chỉ truyền `addr=host`, mọi tham số khác dùng default) **trước khi** chạy `clan_capital(cfg)`.
- `main.py:2295` — `[CC] Zooming out for next CC run…` → `multi_zoom_out(host)` sau khi reboot Clash giữa các pass Clan Capital.
- Ý nghĩa: đưa camera về mức zoom xa nhất để mọi toạ độ tap và template matching (thiết kế cho màn hình 1600×900 ở zoom mặc định/xa nhất) khớp nhau giữa các vòng.

## 3. Cơ chế thứ hai — `AutoHotkey/v2/zoom_out.ahk` (legacy/manual, KHÔNG có caller trong code)

Tìm thấy trên đĩa nhưng **không module đóng gói nào tham chiếu tên nó** (grep `zoom_out.ahk` trên toàn bộ dis = 0 hit; `ahk_utils` chỉ nêu nó làm ví dụ docstring). Nội dung: tìm cửa sổ `MEmu.exe`, `AttachThreadInput` rồi `PostMessage WM_KEYDOWN/WM_KEYUP` phím **F3 ×4 lần** (cách nhau 1s), không lấy focus. Tức là dựa vào keymap của MEmu (F3 được map thành thao tác zoom trong game) — tàn dư của giai đoạn bot điều khiển bằng AHK, giờ chỉ còn là công cụ chạy tay. Bot đóng gói dùng hoàn toàn đường uiautomator2.

## 4. Chi tiết an toàn đáng ghi nhận

- `INJECT_EVENTS`/`SecurityException` xảy ra khi Android từ chối bơm touch vì **có ngón tay người thật đang chạm** vào màn hình giả lập cùng lúc. Bot xử lý bằng cách: chạm góc `(5,5)` (vô hại) → sleep backoff 0.35s → ×1.5 mỗi lần, trần 2.0s → tối đa 5 lần → bỏ qua lượt đó và báo `⚠️ ... (likely due to user touch)`. Toàn bộ `multi_zoom_out` bọc try/except — không bao giờ làm sập vòng lặp farm.
- Điểm gọi luôn sau `pause_event()` check — tôn trọng nút Pause của GUI.

## 5. Chuỗi file của đường pinch uiautomator2 (AutoHotkey64.exe KHÔNG liên quan)

```
zoom_out.pyc  (trong PYZ của Simplicity.exe)
   │  u2.connect('127.0.0.1:21503' = main.host)  →  root.pinch_in(percent=100, steps=20)
   ▼
uiautomator2*.pyc ×19  (client HTTP/JSON; u2.core có AdbHTTPConnection đi qua adb forward;
   │                    docstring: "runs without atx-agent")
adbutils*.pyc ×15      (client giao thức ADB qua socket tới adb server :5037 —
   │                    push/install APK, forward port, shell vào giả lập)
   ▼
adb\adb.exe + AdbWinApi.dll + AdbWinUsbApi.dll   (ADB server Windows; bản Apr 2020 4.57MB.
   │                                              adbutils còn kèm bản riêng 6.64MB Dec 2025 tại
   │                                              _internal\adbutils\binaries\)
   ▼ (adb forward tcp)
┌── BÊN TRONG GIẢLẬP ANDROID ─────────────────────────────────────────────┐
│ app-uiautomator.apk (1.87MB, agent com.github.uiautomator v2.4.0 theo   │
│   version.json) + u2.jar (3.7MB) — nguồn: _internal\uiautomator2\assets\│
│ chạy instrumentation UiAutomator → performMultiPointerGesture           │
│ → pinch 2 ngón thật sự → CoC zoom out                                    │
└──────────────────────────────────────────────────────────────────────────┘
```

- `AutoHotkey64.exe`: chỉ phục vụ `bypass_screen.ahk` (chụp màn hình MEmu) và `zoom_out.ahk` legacy — **không nằm trên đường pinch**.
- Bot tự dùng `adb\adb.exe` qua `ADB_BIN` cho các lệnh riêng (screencap, input tap, force-stop); uiautomator2/adbutils nói chuyện với adb **server** qua socket nên không cần gọi adb.exe từng lệnh.
- Hai bản adb.exe khác version trong folder: bản gốc trong `adb\` và bản do adbutils 2.12 kèm theo trong `_internal\adbutils\binaries\`.
