# RED ZONE ANALYSIS — Bot xác định vùng đỏ (cấm deploy) như thế nào?

Ngày: 2026-10-29. Căn cứ: `extracted/pyz/main.dis.txt` (các code object dòng 289–646 của main.py), `attacks/attacks.py` (nguồn thật).

## 1. Insight then chốt: bot KHÔNG dò màu đỏ

Bot **không hề phân loại pixel đỏ**. Thay vào đó nó khai thác đặc trưng ổn định hơn của giao diện CoC: red zone luôn được viền bởi một **đường sáng trắng phát quang (glowing white border)** — ranh giới giữa vùng đỏ và bãi cỏ xanh. Bot dò các đoạn thẳng trắng sáng đó, rải điểm rơi dọc theo chúng, rồi **dời từng điểm về phía pixel "xanh cỏ" nhất** để đảm bảo điểm tap nằm ngoài red zone.

Có 2 pipeline độc lập + 1 bản biến thể, toàn bộ trong `main.py`:

## 2. Pipeline A — `get_glow_drop_points(img_bgr, tl=GLOW_TL, br=GLOW_BR, spacing=DROP_SPACING)` (main.py:370)

```python
H, W = img_bgr.shape[:2]
x1, y1, x2, y2 = _sorted_box(tl, br)          # GLOW_TL=(1549,722), GLOW_BR=(235,210) → hộp sân 235..1549 × 210..722
x1,y1,x2,y2 = clip theo biên ảnh
if hộp rỗng: return [tâm hộp]

roi = img_bgr[y1:y2, x1:x2]
hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
Hc, Sc, Vc = cv2.split(hsv)
mask = ((Sc < 80) & (Vc > 220)).astype(np.uint8) * 255     # pixel TRẮNG SÁNG = viền glow
mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3,3),np.uint8), iterations=2)
mask = cv2.dilate(mask, np.ones((3,3),np.uint8), iterations=1)
edges = cv2.Canny(mask, 50, 150)
lines = cv2.HoughLinesP(edges, 1, np.pi/180, 60, minLineLength=12)
if lines is None: return [tâm ROI]

lines = [tuple(map(int, l[0])) for l in lines]
lines.sort(key=lambda L: math.hypot(L[2]-L[0], L[3]-L[1]), reverse=True)   # đoạn dài trước
segs = lines[:6]                                                          # 6 cạnh của viền

pts = []
for xa,ya,xb,yb in segs:                       # đổi về toạ độ toàn ảnh
    pts += _points_along(x1+xa, y1+ya, x1+xb, y1+yb, spacing)   # rải điểm mỗi ~180px

out = []
for px,py in pts:                              # dedup: giữ điểm cách mọi điểm cũ >18px
    if all(abs(px-qx) > 18 or abs(py-qy) > 18 for qx,qy in out):
        out.append((px,py))
return out[:12]
```

## 3. Pipeline B — `detect_bright_field_drop_points(img_bgr, roi_spec, debug=None)` (main.py:523) — bản nâng cấp có confidence

```python
box = _norm_roi_any(img.shape, roi_spec, margin=BRIGHT_EDGE_MARGIN)  # margin=10
if not box: return (_last_good_points, 0.0) nếu có cache else ([], 0.0)
x1,y1,x2,y2 = box; roi = img[y1:y2, x1:x2]; gray = cvtColor(roi, GRAY)

hat  = _white_tophat(gray, k=21)             # top-hat ellipse 21px: chỉ giữ cấu trúc SÁNG MẢNH
mask = _auto_binary(hat)                     # Otsu ∪ adaptive(31,-3) → CLOSE 5×5 → OPEN 3×3

lines = _find_lines_hough(mask, x1, y1)
if len(lines) < 2:
    lines = sorted(lines + _find_lines_lsd(hat, x1, y1),
                   key=lambda L: hypot(L[2]-L[0], L[3]-L[1]), reverse=True)
if debug: vẽ rectangle xanh + 8 đoạn đỏ, imwrite _dbg/_hat/_mask.png

if not lines: return (_last_good_points, 0.15) nếu có cache else ([tâm ROI], 0.15)

lines = lines[:6]
pts = [điểm rải mỗi DROP_SPACING dọc từng đoạn]
uniq = []
for px,py in pts:
    if all(abs(px-ux) > 18 or abs(py-uy) > 18 for ux,uy in uniq):
        uniq.append(_nudge_inside((px,py), img_bgr, step=12))    # ← dời về phía xanh

diag = hypot(x2-x1, y2-y1)
conf = min(1.0, sum(độ dài đoạn) / diag)
_last_good_points = uniq
return uniq[:12], conf
```

Helper then chốt:

```python
def _find_lines_hough(mask, xa, ya):                      # (và _find_lines_lsd tương tự trên top-hat)
    med = np.median(mask); low = int(max(0, .66*med)); high = int(min(255, 1.33*med))
    edges = cv2.Canny(mask, low, high)
    min_len = max(80, int(0.12 * hypot(W,H)))
    lines = cv2.HoughLinesP(edges, 1, np.pi/180, 60, minLineLength=min_len, maxLineGap=16)
    for x1,y1,x2,y2 in lines[:,0]:
        ang = abs(math.degrees(math.atan2(y2-y1, x2-x1)))
        if (12 <= ang <= 85) or (95 <= ang <= 168):       # CHỈ NHẬN ĐOẠN XIÊN
            out.append((xa+x1, ya+y1, xa+x2, ya+y2))      # loại line ngang/dọc của UI

def _nudge_inside(pt, img_bgr, step):
    x, y = pt; H, W = img.shape[:2]
    dirs = [(1,0),(0,1),(-1,0),(0,-1),(1,1),(-1,1),(1,-1),(-1,-1)]
    best = (0, None)
    for dx,dy in dirs:
        b,g,r = img[clip(y+dy*8), clip(x+dx*8)]
        score = int(g) - (int(r) + int(b)) // 2           # độ "XANH CỎ"
        if score > best[0]: best = (score, (dx,dy))
    if best[1] is None: return (x, y)
    return (clip(x+dx*step), clip(y+dy*step))             # dời 12px về hướng xanh nhất
```

`_points_along(x1,y1,x2,y2,spacing)`: chia đoạn thành `n = int(L//spacing)+1` phần, trả `n` điểm tại **giữa mỗi nút chia** (`(i+0.5)/n`).

## 4. Pipeline C — `get_glow_drop_points_poly` (main.py:309) — bản giới hạn trong đa giác

Giống pipeline A nhưng: vẽ `cv2.fillPoly(zeros, [np.array(poly_abs, int32)], 255)` rồi **AND** mask trắng-sáng với mask đa giác trước khi Hough — chỉ nhận glow nằm trong đa giác đích. Đa giác tới từ `CP_GLOW_POLY_REL` (4 đỉnh theo tỉ lệ màn hình) qua `_abs_poly_from_rel(img.shape, poly_rel)`.

## 5. Hằng số hoạt động (module-level, main.py ~136–167)

| Hằng | Giá trị | Ý nghĩa |
|---|---|---|
| `GLOW_TL` / `GLOW_BR` | (1549,722) / (235,210) | Hộp dò glow mặc định (sau `_sorted_box`: x 235–1549, y 210–722 — vùng sân trung tâm 1600×900) |
| `BRIGHT_EDGE_ROI_RAW` | (1549,722,235,210) | ROI góc dưới-phải cho pipeline B (qua `_norm_roi_any`, tự nhận dạng w/h ≤ W/3,H/3) |
| `BRIGHT_EDGE_MARGIN` | 10 | Nới ROI 10px mỗi cạnh |
| `DROP_SPACING` | 160 → override 180 | Khoảng cách rải điểm dọc viền |
| `CP_GLOW_POLY_REL` | (0.631,0.096),(0.752,0.266),(0.339,0.810),(0.191,0.642) | Đa giác dò quanh Capital Peak (tỉ lệ W×H) |
| `CP_FIRST_DROPPOINTS` | (795,444),(805,432) | Điểm rơi đầu tiên cố định |
| `_last_good_points` | [] | Cache điểm tốt lần trước làm fallback (conf 0.15) |

**Dead constants** (chỉ STORE, không LOAD — di chỉ bản detector cũ theo gradient): `EDGE_S_MAX_DEF=50`, `EDGE_V_MIN_DEF=210`, `EDGE_LOCAL_DELTA_DEF=16`, `EDGE_GRAD_FLOOR=60`, `EDGE_MIN_LINE_LEN_FR=0.12`, `EDGE_MAX_GAP=18`, `ANGLE_MIN=15`, `ANGLE_MAX=75`.

## 6. Điểm gọi

- `clan_capital_phase4._regular_points_round()` (main.py:1560):
  `poly_abs = _abs_poly_from_rel(...)` → `get_glow_drop_points_poly(img, poly_abs, spacing=DROP_SPACING)` → nếu rỗng → `get_glow_drop_points(img)` → lọc qua `_safe_playfield_points` → dùng làm điểm deploy quân/spell quanh village trong raid Clan Capital.
- `save_glow_debug(img, path)`: gọi pipeline A, vẽ chấm đỏ r=10, lưu ảnh debug.
- **Attack thường (Dragon/E-Dragon) KHÔNG dùng red-zone detection**: `attacks.py` rải theo toạ độ cứng ven bản đồ (`DRAGON_L/R`...) + `jitterCoord` ngẫu nhiên — rìa màn hình luôn ngoài red zone nên không cần dò.

## 7. Đánh giá kỹ thuật

- Điểm yếu thiết kế: dò **trắng sáng** có thể bắt nhầm các element sáng khác trong ROI (hào nước, hiệu ứng spell); bộ lọc góc 12–85°/95–168° và dedup 18px + nudge-green là 3 lớp chống nhiễu bù lại.
- `_nudge_inside` chỉ dịch tối đa 12px/1 lần — đủ để nhấc điểm khỏi viền glow nhưng không cứu điểm rơi rơi giữa red zone lớn.
- Confidence = tỉ lệ độ dài glow tìm thấy trên đường chéo ROI — proxy thô cho "đã thấy đủ viền chưa".
