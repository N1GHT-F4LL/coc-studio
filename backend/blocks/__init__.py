"""Importing this package registers every block into engine.registry.REGISTRY.

The submodules are imported for their @register side effects. Import this
package (``import blocks``) once at startup before serving /api/blocks or
running a graph.

DESCRIPTIONS holds the human "how to use" text for each block (shown in the GUI
palette tooltip + parameter panel). Kept here so all copy lives in one place.
"""
from engine.registry import REGISTRY

from . import coc_blocks      # noqa: F401
from . import vision_blocks   # noqa: F401
from . import input_blocks    # noqa: F401
from . import ocr_blocks      # noqa: F401
from . import control_blocks  # noqa: F401
from . import logic_blocks    # noqa: F401
from . import util_blocks     # noqa: F401

DESCRIPTIONS = {
    # CoC
    "ensure_home": "Mở/đưa Clash of Clans ra trước, chờ về màn làng, đóng popup khởi động và zoom-out; lạc màn thì tự restart game. ĐẶT Ở ĐẦU mỗi graph farm.",
    "ensure_troops": "Train quân THỦ CÔNG khớp scenario đã chọn (vd Thrower → Thrower×16, Healer×6, Archer×12). Mở Train Troops, tap từng icon lính đủ số, rồi về home. ĐẶT Ở ĐẦU cycle (quân vừa bị tiêu). Cần chụp asset màn Army trước. Readiness: khai capacity_region+target_capacity để OCR chờ army đầy, hoặc wait_seconds để chờ cứng.",
    "collect_resources": "Thu mọi mỏ vàng/dầu/dầu đen đang đầy trên màn làng. Phải đang ở home (đặt sau ensure_home).",
    "find_match": "Bấm Attack → Find a Match → đọc loot, bỏ qua base dưới ngưỡng (settings.farm) cho tới khi gặp base đạt. Đặt biến match_found. Phải đang ở home.",
    "deploy": "Vào trận rồi thả quân. Để trống 'scenario' = dùng đội hình trong settings; điền tên scenario đã migrate (vd 'Thrower') để thả theo scenario đó. Chỉ chạy khi match_found=true.",
    "return_home": "Chờ trận kết thúc → bấm Return Home → đóng popup. Chỉ chạy khi match_found=true.",
    "request_clan_troops": "Xin quân từ Clan Castle ở màn chuẩn bị tấn công (nếu nút có hiện).",
    # Control
    "delay": "Dừng 'seconds' giây. Dừng được ngay khi bấm Stop.",
    "if": "Rẽ nhánh: nối một Bool (vd từ 'compare') vào 'cond'. cond=true chạy nhánh 'then', false chạy 'else'. Nối block tiếp theo vào cổng then/else.",
    "loop_n": "Chạy lại MỘT graph đã lưu ('graph_ref') 'times' lần. Farm liên tục: loop_n(graph_ref=farm_cycle, times=50). Bấm Stop để dừng.",
    "loop_until": "Chạy graph đã lưu cho tới khi biến 'until_var' = true (dùng block set_flag để bật) hoặc đủ 'max_iters'.",
    # Vision
    "wait_template": "Chờ một template (asset) xuất hiện trong 'timeout' giây. Trả coord + found. Dùng để đợi nút/màn hiện ra trước khi bấm.",
    "is_screen": "Kiểm tra nhiều anchor (nhiều template, cách nhau dấu phẩy) có cùng xuất hiện không → matched. Dùng nhận diện màn.",
    "find_template": "Tìm 1 template trên màn hiện tại → coord (toạ độ) + found. Nối 'coord' sang block Tap để bấm đúng chỗ tìm được.",
    "is_home": "Trả true nếu đang ở màn làng (home). Nối vào if để rẽ nhánh.",
    "is_attack": "Trả true nếu đang ở màn tấn công/tìm trận.",
    "is_battle": "Trả true nếu đang trong trận (battle).",
    # Input
    "tap": "Bấm 1 phát tại toạ độ 'coord'. Nối coord từ find_template, hoặc bấm nút Pick để chọn điểm trên Device view.",
    "tap_template": "Tìm template rồi bấm thẳng vào nó (gộp find_template + tap). Tiện khi chỉ cần bấm một nút.",
    "swipe_line": "Vuốt từ 'start' đến 'end' (hai toạ độ).",
    "pinch": "Pinch zoom in/out. Vd direction='out' để zoom xa xem toàn làng.",
    # OCR
    "read_number": "Đọc 1 số nguyên trong vùng 'region' [x1,y1,x2,y2] bằng OCR. Bấm Pick (Region) để khoanh vùng trên Device view.",
    "read_loot": "Đọc loot của địch (gold/elixir/dark) ở màn xem base. Nối các số sang compare/if để quyết định đánh hay bỏ qua.",
    "loot_ge": "Đọc số trong 'region' và so ≥ 'threshold' → Bool (ok).",
    # Logic
    "const_number": "Hằng số (number) làm nguồn cho data edge — vd ngưỡng loot để so sánh.",
    "const_bool": "Hằng số true/false làm nguồn cho data edge.",
    "compare": "So sánh: a (op) b → Bool. Vd nối loot.gold vào a, op='>=', b=500000. Nối 'result' vào if.cond.",
    "logic_and": "AND hai Bool → true khi cả hai true.",
    "logic_or": "OR hai Bool → true khi có ít nhất một true.",
    "logic_not": "NOT một Bool (đảo true/false).",
    # Util
    "log": "Ghi một dòng 'message' vào Run console — để debug graph.",
    "close_popups": "Quét và đóng các popup đang hiện (nút Close/OK).",
    "restart_game": "Khởi động lại Clash of Clans (dùng để recovery khi bot bị kẹt).",
    "set_flag": "Đặt biến ctx 'name' = 'value'. Dùng làm điều kiện dừng cho loop_until.",
}

# Attach descriptions to the registered block classes (single source of copy).
for _type, _desc in DESCRIPTIONS.items():
    if _type in REGISTRY:
        REGISTRY[_type].description = _desc
