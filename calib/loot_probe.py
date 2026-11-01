"""loot_probe — đọc-THÔI (không tap) chứng cứ pipeline loot trong lúc user bấm Next tay.

Mục đích: sửa tận gốc lỗi "base giàu bị skip" (dark/elixir OCR đọc rác, vùng OCR lệch).
Mỗi khi thấy màn scout (nút Next xuất hiện), công cụ:
  1. Chạy ĐÚNG hàm _read_loot của bot (giá trị + conf từng tài nguyên).
  2. OCR THÔ toàn panel loot (không allowlist) để thấy game hiển thị số gì.
  3. Chép frame PNG + crop panel vào calib/loot_probe/ để agent đọc ảnh sau.
  4. In kết luận skip/pass theo threshold settings.json.

Cách chạy (backend coc-studio phải TẮT — script tự tắt nếu đang chạy):
  cd coc-studio
  .venv\\Scripts\\python.exe calib\\loot_probe.py
Rồi trong game: Attack -> Find a Match -> Next vài base (để nó quét 6-10 màn).
Ctrl+C bất cứ lúc nào để dừng; kết quả đã in từng dòng nên không mất gì.
"""
import os
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.abspath(os.path.join(HERE, "..", "backend"))
OUT_DIR = os.path.join(HERE, "loot_probe")
MAX_FRAMES = 10
POLL = 1.5          # seconds between screen grabs
NEXT_TEMPLATE = "buttons/attack/btn_next_enemy"
NEXT_THRESHOLD = 0.60
# Loot panel top-left: same area the icon search uses, slightly wider/taller.
PANEL_REGION = (0, 60, 440, 400)


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
        print("[1/3] Backend coc-studio khong chay - OK.", flush=True)
        return
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                         stdin=subprocess.DEVNULL).stdout
    pids = {l.split()[-1] for l in out.splitlines()
            if ":8000" in l and "LISTENING" in l.upper()}
    for pid in pids:
        subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True,
                       stdin=subprocess.DEVNULL)
        print(f"[1/3] Da tat backend (pid {pid}) de doc quyen thiet bi.", flush=True)


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

    banner("LOOT PROBE - chi DOC man hinh, KHONG tap gi ca")
    print("""Công cụ sẽ ngồi im và quan sát. VIỆC CỦA BẠN:
  1. Trong game: Attack -> Find a Match -> (nút Attack! xanh) -> tới màn scout.
  2. Bấm Next để đi qua KHOẢNG 6-10 base (càng nhiều base 'giàu bị skip' càng tốt).
  3. Mỗi màn scout công cụ tự ghi 1 dòng kết quả + lưu 1 frame PNG.
Dừng: Ctrl+C, hoặc để nó tự dừng sau %d frame.""".replace("%d", str(MAX_FRAMES)), flush=True)
    input("\nNhấn ENTER để connect Memu và bắt đầu quan sát...")

    kill_backend_if_running()

    sys.path.insert(0, BACKEND)
    os.chdir(BACKEND)
    import logging
    logging.basicConfig(level=logging.WARNING)

    print("\n[2/3] Đang connect Memu + nạp assets...", flush=True)
    import blocks  # noqa: F401  -- populate REGISTRY (side effect)
    import cv2
    from device_manager import manager, load_settings
    from core.ocr import read_number_with_confidence, _get_reader
    from core.vision import vision
    from screens.attack_screen import AttackScreen, LOOT_BOUNDS, LOOT_ICON_CANDIDATE_TEMPLATES
    import popup_guard

    ok, reason = manager.connect()
    if not ok:
        sys.exit(f"KHÔNG connect được thiết bị ({reason}). Kiểm tra Memu rồi chạy lại.")
    ui = manager.ui_manager
    settings = load_settings()
    attack_cfg = settings.get("attack", {})
    farm = settings.get("farm", {})
    attack = AttackScreen(ui, settings)
    print(f"[2/3] OK. Threshold hiện tại: gold>={farm.get('min_gold', 0):,} "
          f"elixir>={farm.get('min_elixir', 0):,} dark>={farm.get('min_dark_elixir', 0):,}", flush=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    reader = _get_reader()
    print("[3/3] Bắt đầu quan sát — hãy bấm Next trong game (Ctrl+C để dừng).\n", flush=True)

    frames = 0
    result_lines = []
    last_capture = 0.0
    try:
        while frames < MAX_FRAMES:
            time.sleep(POLL)
            screen = ui.get_screen()
            if screen is None:
                continue
            popup_guard.guard_and_recover(None)   # only acts if a system popup is up
            if not vision.find_template(screen, NEXT_TEMPLATE, threshold=NEXT_THRESHOLD,
                                        use_orb_fallback=False):
                print(".", end="", flush=True)  # heartbeat: not a scout screen
                continue
            now = time.time()
            if now - last_capture < 2.0:
                continue                         # same base as last frame
            last_capture = now
            frames += 1
            ts = datetime.now().strftime("%H%M%S")
            tag = f"frame_{frames:02d}_{ts}"

            # 1) the bot's own loot read (identical to a live run)
            loot, conf = attack._read_loot(screen, attack_cfg)

            # 2) raw panel OCR — no allowlist, see what the game actually shows
            px1, py1, px2, py2 = PANEL_REGION
            panel = screen[py1:py2, px1:px2]
            raw_items = reader.readtext(panel, detail=1, paragraph=False)
            raw_text = " | ".join(f"'{t}'({c:.2f})" for _b, t, c in raw_items if c > 0.15)

            # 3) icon anchors + per-candidate region OCR (the internals _read_loot hides)
            icon_info = {}
            regions = attack._regions_from_resource_icons(
                screen,
                search_roi=attack_cfg.get("loot_by_icon", {}).get("search_roi", [0, 70, 420, 360]),
                loot_regions=attack_cfg.get("loot_regions", {}),
                x_start_offset=int(attack_cfg.get("loot_by_icon", {}).get("x_start_offset", -8)),
                x_end_offset=int(attack_cfg.get("loot_by_icon", {}).get("x_end_offset", 236)),
                y_half_height=int(attack_cfg.get("loot_by_icon", {}).get("y_half_height", 19)),
                per_resource_cfg=attack_cfg.get("loot_by_icon", {}).get("per_resource", {}),
            )
            for key in ("gold", "elixir", "dark_elixir"):
                reg = regions.get(key)
                if reg is None:
                    icon_info[key] = "NO-ICON"
                    continue
                val, c = read_number_with_confidence(
                    screen, tuple(reg),
                    min_value=LOOT_BOUNDS.get(key, (0, None))[0],
                    max_value=LOOT_BOUNDS.get(key, (0, None))[1],
                    prefer_longest=(key != "dark_elixir"),
                    prefer_consensus=(key == "dark_elixir"),
                )
                icon_info[key] = f"@{tuple(reg)} -> {val} (c={c:.2f})"

            # 4) threshold verdict — which gate failed
            meets = (loot["gold"] >= farm.get("min_gold", 0)
                     and loot["elixir"] >= farm.get("min_elixir", 0)
                     and loot["dark_elixir"] >= farm.get("min_dark_elixir", 0))
            failed = []
            if loot["gold"] < farm.get("min_gold", 0):
                failed.append(f"gold {loot['gold']} < {farm.get('min_gold', 0)}")
            if loot["elixir"] < farm.get("min_elixir", 0):
                failed.append(f"elixir {loot['elixir']} < {farm.get('min_elixir', 0)}")
            if loot["dark_elixir"] < farm.get("min_dark_elixir", 0):
                failed.append(f"dark {loot['dark_elixir']} < {farm.get('min_dark_elixir', 0)}")
            verdict = "KEEP (attacked)" if meets else "SKIP vi: " + "; ".join(failed)

            # 5) save evidence frames
            cv2.imwrite(os.path.join(OUT_DIR, f"{tag}_full.png"), screen)
            up = cv2.resize(panel, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            cv2.imwrite(os.path.join(OUT_DIR, f"{tag}_panel.png"), up)

            line = (f"{tag}: gold={loot['gold']:,}(c={conf['gold']:.2f}) "
                    f"elixir={loot['elixir']:,}(c={conf['elixir']:.2f}) "
                    f"dark={loot['dark_elixir']:,}(c={conf['dark_elixir']:.2f}) -> {verdict}")
            print(line, flush=True)
            print(f"   raw panel OCR: {raw_text}", flush=True)
            print(f"   icon regions : {icon_info}", flush=True)
            print(f"   saved: calib/loot_probe/{tag}_full.png + _panel.png", flush=True)
            result_lines.append(line)
    except KeyboardInterrupt:
        print("\n(Dừng theo Ctrl+C)", flush=True)

    banner(f"RESULT — COPY TOÀN BỘ KHỐI NÀY ({frames} frame)")
    print("settings farm:", {k: farm.get(k) for k in ("min_gold", "min_elixir", "min_dark_elixir")})
    for l in result_lines:
        print(l, flush=True)
    print(f"(Frame PNG nằm trong calib/loot_probe/ — agent sẽ tự đọc các file này.)", flush=True)
    banner("HẾT — dán RESULT vào chat là xong")


if __name__ == "__main__":
    main()
