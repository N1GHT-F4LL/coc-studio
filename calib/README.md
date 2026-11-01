# calib/ — tool hiệu chỉnh toạ độ thả quân cho plan `dragon_balloon`

>Toàn bộ tool hiệu chỉnh nằm gọn trong thư mục này — muốn xoá thì xoá cả thư mục, không ảnh hưởng gì tới coc-studio (trừ file plan mà nó ghi vào).

## Cách dùng

### 1. Bắt toạ độ trên device (cần Memu đang mở CoC)

```
cd C:\Users\antoinenguyen_09\Downloads\coc-studio
.venv\Scripts\python.exe calib\run_calib.py
```

Script sẽ: tự tắt backend coc-studio nếu đang chạy (để độc quyền device) → connect Memu → vào 1 trận attack (ngưỡng loot 0, nhận base đầu tiên, **không thả quân**, kết thúc bằng surrender) → zoom out hết cỡ → **chờ bạn tap 8 điểm** trên cửa sổ Memu → lưu `lines.json` → ra về màn hình nhà.

**Thứ tự 8 cú tap** (mỗi tap = 1 click đơn lên map, tránh thanh quân phía dưới; tap nào trúng thanh bar sẽ bị từ chối và bắt lại):

| Cú tap | Variant | Điểm đầu (→ royal_champion) | Điểm cuối (→ archer_queen) |
|---|---|---|---|
| 1, 2 | 1 | cạnh 9h | cạnh 12h |
| 3, 4 | 2 | cạnh 12h | cạnh 3h |
| 5, 6 | 3 | cạnh 3h | cạnh 6h |
| 7, 8 | 4 | cạnh 6h | cạnh 9h |

Hãy tap ở vị trí **ngoài viền đỏ** — đúng chỗ bạn muốn kẻ đường thả quân của variant đó.

### 2. Ghi vào plan (không cần device)

```
.venv\Scripts\python.exe calib\run_calib.py --apply
```

Đọc `lines.json` và ghi toạ độ vào `backend/data/scenarios/dragon_balloon.json`:
- Điểm đầu/cuối đường kẻ = **royal_champion / archer_queen**.
- **dragon** trải rộng 10%–90%, **balloon** dồn 25%–75% dọc đường.
- **stone_slammer** 50%, **prince** 40%, **grand_warden** 60%, **minion** 88% dọc đường.
- Điểm **spell** chung = giữa đường, dồn 45% về phía tâm làng (tâm ước lượng từ trung bình 4 đường).
- Node pan bị loại bỏ; backup plan cũ lưu tại `calib/dragon_balloon.pre_apply.bak.json`.

Xong: khởi động lại backend rồi Run graph `dragon_balloon_loop`.

## File trong thư mục

- `run_calib.py` — tool chính (2 chế độ như trên).
- `lines.json` — kết quả 8 cú tap (sinh ra sau bước 1).
- `dragon_balloon.pre_apply.bak.json` — backup plan trước khi ghi (sinh ra sau bước 2).
- Ảnh chụp chẩn đoán các lần thử trước nằm ở `backend/_calib/` (đã có sẵn trong .gitignore).
