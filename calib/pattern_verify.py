"""pattern_verify — kiểm chứng pattern biên ngoài trên base địch THẬT (user tự chạy).

Mục đích (bước 3 của quy trình hiệu chuẩn — đặc tả 2026-10-29): với TỪNG base
địch, chụp view sau pan của cả 4 variant và VẼ pattern lên ảnh để duyệt; 3 base
× 4 variant = 12 ảnh verify lưu vào backend/data/calib_debug/verify_*.png.

Cách dùng:
  1. TẮT backend coc-studio (tool tự tắt nếu đang chạy).
  2. cd coc-studio && .venv\\Scripts\\python.exe calib\\pattern_verify.py
  3. Tool tự: connect Memu -> về làng -> bấm Attack -> Find a Match (ngưỡng 0
     -> giữ base ĐẦU TIÊN). Với TỪNG variant: lăn pan đúng như node pan trong
     JSON -> chụp -> vẽ pattern -> lưu ảnh.
  4. Khi tool báo "XONG BASE n/3 — Next": bấm Next trong game để sang base mới,
     nhấn ENTER để lặp lại. Sau 3 base: tool tự surrender + về làng.

Lưu ý: đây là ảnh SCOUT (chưa chọn quân) — đủ để duyệt vị trí điểm so với biên
map/base; phán xét "điểm có rơi vào đỏ" thật sự diễn ra khi CHẠY THẬT với biến
môi trường COC_PATTERN_VERIFY=1 (battle_screen tự chụp ảnh verify tại lúc thả).
"""
import json
import os
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.abspath(os.path.join(HERE, "..", "backend"))
OUT_DIR = os.path.join(BACKEND, "data", "calib_debug")
SCEN = os.path.join(BACKEND, "data", "scenarios", "dragon_balloon.json")
N_BASES = 3


def banner(msg):
    print("\n" + "=" * 70, flush=True)
    print(msg, flush=True)
    print("=" * 70, flush=True)


def kill_backend_if_running():
    import urllib.request
    import subprocess
    try:
        urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=2)
    except Exception:
        print("[1/4] Backend coc-studio khong chay - OK.", flush=True)
        return
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                         stdin=subprocess.DEVNULL).stdout
    pids = {l.split()[-1] for l in out.splitlines()
            if ":8000" in l and "LISTENING" in l.upper()}
    for pid in pids:
        subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True,
                       stdin=subprocess.DEVNULL)
        print(f"[1/4] Da tat backend (pid {pid}) de doc quyen thiet bi.", flush=True)


def draw_pattern(img, variant_nodes):
    pts = {n["id"]: n for n in variant_nodes}
    for n in variant_nodes:
        if n.get("strategy") != "pattern" or not n.get("points"):
            continue
        role = n["id"].rsplit("_", 1)[-1]
        color = {"balloon": (0, 0, 255), "dragon": (0, 255, 255)}.get(role, (0, 255, 0))
        for i, p in enumerate(n["points"]):
            cv2.circle(img, tuple(p), 6 if role in ("balloon", "dragon") else 9,
                       color, -1)
            if role in ("balloon", "dragon") and i % 2 == 0:
                cv2.putText(img, str(i), (p[0] + 8, p[1] - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)
        label = n.get("label") or role
        p0 = n["points"][0]
        cv2.putText(img, label[:20], (p0[0] + 10, p0[1] + 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
    return img


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    try:
        os.system("chcp 65001 >nul 2>&1")
    except Exception:
        pass

    banner(f"PATTERN VERIFY — {N_BASES} base x 4 variant (chi chup + ve, KHONG tha quan)")
    print("""Tool sẽ: về làng -> Attack -> Find a Match (ngưỡng 0, giữ base đầu tiên)
-> với cả 4 variant: lăn pan đúng như JSON -> chụp + vẽ pattern -> lưu ảnh.
SAU MỖI BASE tool dừng — bạn bấm Next sang base khác rồi nhấn ENTER.
Ctrl+C bất cứ lúc nào; ảnh đã lưu không mất.""", flush=True)
    input("\nNhấn ENTER để connect Memu và bắt đầu...")

    kill_backend_if_running()
    sys.path.insert(0, BACKEND)
    os.chdir(BACKEND)
    import logging
    logging.basicConfig(level=logging.WARNING)

    print("\n[2/4] Connect Memu + nạp assets...", flush=True)
    import cv2
    import blocks  # noqa: F401
    from device_manager import manager, load_settings
    from engine.context import RuntimeContext
    from engine.graph import Graph
    from engine.executor import run_graph
    from blocks.coc_blocks import EnsureHome, FindMatch
    import threading

    kill_ok = True
    ok, reason = manager.connect()
    if not ok:
        sys.exit(f"KHÔNG connect được thiết bị ({reason}). Kiểm tra Memu rồi chạy lại.")
    settings = load_settings()
    with open(SCEN, encoding="utf-8") as f:
        doc = json.load(f)
    os.makedirs(OUT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%m%d_%H%M%S")

    ctx = RuntimeContext(device=manager.device, ui_manager=manager.ui_manager,
                         vision=None, ocr_read=lambda *a, **k: (None, 0.0),
                         settings=settings, logger=logging.getLogger("verify"),
                         stop_event=threading.Event(), vars={}, emit=lambda ev: None)

    print("[3/4] Về làng + giữ base đầu tiên (threshold 0)...", flush=True)
    if not EnsureHome().run(ctx, {"zoom_out": True, "timeout": 10})["home"]:
        sys.exit("Không về được màn hình nhà. Chạy lại tool.")
    fm = FindMatch()
    fm.run(ctx, {"min_gold": 0, "min_elixir": 0, "min_dark_elixir": 0})
    if not ctx.vars.get("match_found"):
        sys.exit("Không giữ được base nào (match_found=False). Chạy lại tool.")

    made = []
    for base in range(1, N_BASES + 1):
        banner(f"BASE {base}/{N_BASES}")
        for v in doc["variants"]:
            name = v["name"]
            pan = next((n for n in v["nodes"] if n.get("type") == "pan"), None)
            if pan is None:
                print(f"  [{name}] không có node pan — bỏ qua.", flush=True)
                continue
            # pan NHANH cho mục đích xem ảnh (không cần 900ms chuẩn như deploy)
            x1, y1, x2, y2 = pan["x1"], pan["y1"], pan["x2"], pan["y2"]
            manager.device._run_adb(["shell", "input", "swipe",
                                     str(x1), str(y1), str(x2), str(y2), "900"])
            time.sleep(1.0)
            frame = manager.ui_manager.get_screen()
            if frame is None:
                print(f"  [{name}] chụp màn hình thất bại — bỏ qua.", flush=True)
                continue
            img = draw_pattern(frame.copy(), v["nodes"])
            out = os.path.join(OUT_DIR, f"verify_b{base}_{name}_{ts}.png")
            cv2.imwrite(out, img)
            made.append(out)
            print(f"  [{name}] saved -> data/calib_debug/{os.path.basename(out)}",
                  flush=True)
        if base < N_BASES:
            input(f"\nXONG BASE {base}/{N_BASES} — bấm Next trong game sang base mới "
                  "rồi nhấn ENTER (hoặc Ctrl+C để dừng)... ")

    banner(f"RESULT — {len(made)} ảnh verify (COPY KHỐI NÀY)")
    for m in made:
        print("  ", os.path.relpath(m, BACKEND))
    print("Gửi danh sách này cho agent để đối chiếu; điểm nào thấy sai vị trí trên "
          "base thật sẽ được nudge trong lần hiệu chuẩn kế.")
    banner("Đang thoát khỏi trận (surrender + về làng)...")
    try:
        from screens.battle_screen import BattleScreen
        bs = BattleScreen(manager.ui_manager)
        if bs.wait_until_entered(timeout=5):
            bs.surrender(return_home=True)
            print("Đã về làng. Xong.", flush=True)
    except Exception as e:
        print(f"(thoát trận tự động lỗi: {e} — tự tay Return Home nhé)", flush=True)


if __name__ == "__main__":
    main()
