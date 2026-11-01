# -*- coding: utf-8 -*-
"""calib/run_calib.py — dragon_balloon deploy-line calibration, v3 (interactive).

Run it YOURSELF in a terminal:

    cd C:\\Users\\antoinenguyen_09\\Downloads\\coc-studio
    .venv\\Scripts\\python.exe calib\\run_calib.py

It talks you through every step in Vietnamese: kills the coc-studio backend if
it is running, connects to Memu, enters an attack (no troops are used — it
surrenders at the end), zooms out, then for each of the 4 variants asks you to
PAN the map yourself (drags are ignored) and TAP the two ends of that variant's
deploy line (taps are captured). At the end it prints a RESULT block — copy the
whole block back into the chat.

    .venv\\Scripts\\python.exe calib\\run_calib.py --apply

turns calib/lines.json into backend/data/scenarios/dragon_balloon.json (with a
measured pan node per variant so the runtime view matches your taps).
"""
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.normpath(os.path.join(HERE, "..", "backend"))
SCEN = os.path.join(BACKEND, "data", "scenarios", "dragon_balloon.json")
LINES = os.path.join(HERE, "lines.json")

VARIANTS = [("9-12", "9h -> 12h", "trai-tren (goc 9h -> goc 12h)"),
            ("12-3", "12h -> 3h", "phai-tren (goc 12h -> goc 3h)"),
            ("3-6", "3h -> 6h", "phai-duoi (goc 3h -> goc 6h)"),
            ("6-9", "6h -> 9h", "trai-duoi (goc 6h -> goc 9h)")]

FRACTIONS = {
    "champ": (0.00, 0.00), "queen": (1.00, 1.00),
    "dragon": (0.10, 0.90),
    "balloon": (0.25, 0.75),
    "slammer": (0.50, 0.50), "prince": (0.40, 0.40),
    "warden": (0.60, 0.60), "minion": (0.88, 0.88),
}
# spells drop in a tight cluster hugging the VERTICAL AXIS through the screen
# centre x=800 (user spec 2026-10-26, supersedes the r=150 circle): rage on and
# right next to the axis, freeze tight on the core. Screen coords, identical
# for every variant (a variant's pan moves the map, not these points).
SPELL_RAGE_PTS = [[800, 390], [800, 510], [765, 450], [835, 450]]    # taps=4
SPELL_FREEZE_PTS = [[800, 450], [775, 415], [825, 485]]              # taps=3
BAR_Y = 715
TAP_TIMEOUT = 10 * 60


def banner(msg):
    print("\n" + "=" * 70, flush=True)
    print(msg, flush=True)
    print("=" * 70, flush=True)


def kill_backend_if_running():
    try:
        urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=2)
    except Exception:
        print("[1/4] Backend coc-studio khong chay - OK, tiep tuc.", flush=True)
        return
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                         stdin=subprocess.DEVNULL).stdout
    pids = {l.split()[-1] for l in out.splitlines() if ":8000" in l and "LISTENING" in l.upper()}
    for pid in pids:
        subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True,
                       stdin=subprocess.DEVNULL)
        print(f"[1/4] Da tat backend (pid {pid}) de doc quyen thiet bi.", flush=True)


def lerp(p, q, t):
    return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)


def clamp(pt):
    return (max(10, min(1590, round(pt[0]))), max(40, min(BAR_Y - 5, round(pt[1]))))


# ---------------------------------------------------------------- live capture
def capture():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    try:
        os.system("chcp 65001 >nul 2>&1")
    except Exception:
        pass

    banner("HUONG DAN CHUNG (doc ky 1 lan)")
    print("""Công cụ sẽ: vào 1 cuộc attack (KHÔNG tốn quân, cuối trận tự đầu hàng),
zoom out hết cỡ, rồi với MỖI cạnh (9h-12h, 12h-3h, 3h-6h, 6h-9h) bạn sẽ:
  1. TỰ KÉO map (giữ chuột + kéo) tới khi THẤY TRỌN cạnh đó + 2 góc của nó.
  2. CLICK NHANH điểm ĐẦU cạnh (click ngắn, không kéo).
  3. CLICK NHANH điểm CUỐI cạnh (không kéo map giữa 2 cú click).
Quy tắc: KÉO = di chuyển camera (bỏ qua), CLICK = ghi toạ độ (tính).
Không click vào thanh quân dưới đáy màn hình (sẽ bị từ chối, phải click lại).""", flush=True)
    input("\nNhấn ENTER để bắt đầu (tôi sẽ connect Memu và vào attack)...")

    sys.path.insert(0, BACKEND)
    os.chdir(BACKEND)
    import logging
    logging.basicConfig(level=logging.WARNING)
    log = logging.getLogger("calib")

    print("\n[2/4] Đang connect Memu...", flush=True)
    import blocks  # noqa: F401
    import cv2  # noqa: F401
    from device_manager import manager, load_settings
    from engine.context import RuntimeContext
    from blocks.coc_blocks import EnsureHome
    import popup_guard
    from screens.attack_screen import AttackScreen
    from screens.battle_screen import BattleScreen
    from screens.home_screen import HomeScreen

    kill_backend_if_running()
    ok, reason = manager.connect()
    if not ok:
        sys.exit(f"KHÔNG connect được thiết bị ({reason}). Kểm tra Memu rồi chạy lại.")
    dev, ui = manager.device, manager.ui_manager
    settings = load_settings()
    print(f"[2/4] Đã connect: {dev.serial}", flush=True)

    print("\n[3/4] Đang đưa game về màn hình nhà rồi vào attack (khoảng 30-90 giây,\n"
          "co the phai doi game khoi dong lai neu ban vua thoat tran - CỨ ĐỢI, đừng click Memu)...",
          flush=True)
    ctx = RuntimeContext(device=dev, ui_manager=ui, vision=None,
                         ocr_read=lambda *a, **k: (None, 0.0), settings=settings,
                         logger=log, stop_event=threading.Event(), vars={}, emit=lambda ev: None)
    if not EnsureHome().run(ctx, {"zoom_out": True, "timeout": 10})["home"]:
        sys.exit("Không về được màn hình nhà. Chạy lại tool.")
    popup_guard.guard_and_recover(log)   # only acts if a system popup is up
    attack = AttackScreen(ui, {**settings,
                               "farm": {"min_gold": 0, "min_elixir": 0, "min_dark_elixir": 0},
                               "attack": {**settings.get("attack", {}), "scout_settle": 1.0}})
    if not attack.find_match():
        sys.exit("Không tìm được đối thủ. Chạy lại tool.")
    battle = BattleScreen(ui)
    if not battle.wait_until_entered(timeout=15):
        sys.exit("Không vào được màn hình chiến đấu. Chạy lại tool.")
    dev.pinch("out", span_pixels=600, repeats=3)
    ui._poll_sleep(1.5)

    event_dev, max_x, max_y = dev._find_touch_input_device()
    sw, sh = dev.get_screen_size()
    if not event_dev:
        sys.exit("Không tìm thấy touch device.")
    print(f"\n[3/4] ĐÃ VÀO ATTACK, đã zoom out. Màn hình {sw}x{sh}.", flush=True)

    def save_frame(name):
        f = ui.get_screen()
        path = os.path.join(HERE, f"frame_{name}.png")
        cv2.imwrite(path, f)
        return path

    save_frame("center")

    taps = []
    tap_event = threading.Event()

    def reader():
        # Memu host clicks on event6: Protocol B WITHOUT BTN_TOUCH (verified
        # against a real capture). Contact = TRACKING_ID(0x39) != -1 ... frames
        # of ABS_MT_POSITION_X/Y + SYN ... release = TRACKING_ID=-1.
        # A tap = short hold with little movement; anything else is a drag.
        proc = subprocess.Popen(
            [dev.adb_path, "-s", dev.serial, "shell", "getevent", "-t", event_dev],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            errors="replace")
        st = {"active": False, "rx": None, "ry": None, "pts": [], "t0": None, "tn": None}

        def start_contact(ts):
            st.update(active=True, rx=None, ry=None, pts=[], t0=ts, tn=ts)

        def flush_contact():
            pts = st["pts"]
            if pts:
                disp = math.hypot(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1])
                dur = (st["tn"] - st["t0"]) if st["t0"] is not None and st["tn"] is not None else 0.0
                if disp < 50 and (dur < 0.7 or disp < 20):
                    taps.append(pts[0])          # aim point = where the press landed
                    tap_event.set()
            st.update(active=False, rx=None, ry=None, pts=[], t0=None, tn=None)

        for raw in proc.stdout:
            s = raw.strip()
            ts = None
            if s.startswith("["):
                close = s.find("]")
                if close > 0:
                    try:
                        ts = float(s[1:close])
                    except ValueError:
                        ts = None
                    s = s[close + 1:].strip()
            parts = s.split()
            if parts and parts[0].endswith(":"):
                parts = parts[1:]
            if len(parts) < 3:
                continue
            try:
                t, c, v = int(parts[0], 16), int(parts[1], 16), int(parts[2], 16)
            except ValueError:
                continue
            if t == 0x0003 and c == 0x0039:                  # ABS_MT_TRACKING_ID
                if v == 0xFFFFFFFF:
                    flush_contact()
                else:
                    if st["active"]:                          # leaked contact (missed -1)
                        flush_contact()
                    start_contact(ts)
            elif t == 0x0003 and c == 0x0035:
                st["rx"] = v
            elif t == 0x0003 and c == 0x0036:
                st["ry"] = v
            elif t == 0x0001 and c == 0x014a:                # BTN_TOUCH (if ever)
                if v:
                    if not st["active"]:
                        start_contact(ts)
                else:
                    flush_contact()
            elif t == 0x0000 and c == 0x0000:                # SYN_REPORT
                if st["active"] and st["rx"] is not None and st["ry"] is not None:
                    st["pts"].append((round(st["rx"] * sw / max_x),
                                      round(st["ry"] * sh / max_y)))
                    if ts is not None:
                        st["tn"] = ts
                st["rx"], st["ry"] = None, None

    threading.Thread(target=reader, daemon=True).start()

    def wait_tap(label):
        while True:
            tap_event.clear()
            if not tap_event.wait(timeout=30):
                print(f"   ... vẫn chờ click {label} (không có click nào trong 30s)", flush=True)
                continue
            x, y = taps[-1]
            if y >= BAR_Y:
                print(f"   Bị từ chối ({x},{y}): click trúng thanh quân. CLICK LẠI trên bản đồ!",
                      flush=True)
                taps.clear()
                continue
            taps.clear()             # drop queued extra clicks (double-click 2nd hit)
            return (x, y)

    def settle():
        """Swallow clicks for a moment after an accepted point, so the second
        hit of an accidental double-click can never leak into the next step."""
        time.sleep(0.5)
        taps.clear()
        tap_event.clear()

    lines = {}
    banner("[4/4] BẮT TOẠ ĐỘ - 4 CẠNH, MỖI CẠNH 2 CLICK")
    try:
        for idx, (name, _desc, vn) in enumerate(VARIANTS, 1):
            print(f"\n----- CẠNH {idx}/4 : variant {name} — {vn} -----", flush=True)
            print("BƯỚC A: KÉO map (giữ chuột kéo) tới khi thấy TRỌN cạnh này + 2 góc.", flush=True)
            input(f"        Xong thì nhấn ENTER ở đây để sang bước B...")
            print("BƯỚC B: CLICK NHANH điểm ĐẦU cạnh (góc "
                  f"{VARIANTS[idx-1][1].split(' -> ')[0]}) — nơi thả royal_champion. Đang chờ click...",
                  flush=True)
            S = wait_tap("điểm ĐẦU")
            print(f"        Đã nhận điểm đầu = {S}. Chụp ảnh lưu vết...OK", flush=True)
            lines.setdefault(name, {})["START"] = list(S)
            lines[name]["START_frame"] = save_frame(f"{name}_START")
            settle()
            print("BƯỚC C: CLICK NHANH điểm CUỐI cạnh (góc "
                  f"{VARIANTS[idx-1][1].split(' -> ')[1]}) — nơi thả archer_queen.\n"
                  "        (KHÔNG kéo map giữa 2 cú click!) Đang chờ click...", flush=True)
            E = wait_tap("điểm CUỐI")
            print(f"        Đã nhận điểm cuối = {E}. Chụp ảnh lưu vệt...OK", flush=True)
            lines[name]["END"] = list(E)
            lines[name]["END_frame"] = save_frame(f"{name}_END")
            settle()
    except KeyboardInterrupt:
        print("\nĐã hủy. Không lưu kết quả.", flush=True)
        _surrender(battle, attack, ui, HomeScreen)
        sys.exit(130)

    with open(LINES, "w", encoding="utf-8") as f:
        json.dump({"screen": [sw, sh], "lines": lines}, f, indent=2, ensure_ascii=False)

    print("\nĐủ 8 điểm. Đang đầu hàng ra về màn hình nhà (không tốn quân)...", flush=True)
    _surrender(battle, attack, ui, HomeScreen)
    print("Đã xong! Đã lưu calib/lines.json", flush=True)

    banner("KẾT QUẢ — COPY TOÀN BỘ KHỐI GIỮA 2 ĐƯỜNG KẺ GỬI VÀO CHAT")
    print(f"SCREEN: {sw}x{sh}")
    for name, _, _ in VARIANTS:
        v = lines[name]
        print(f"{name}: START=({v['START'][0]},{v['START'][1]}) "
              f"END=({v['END'][0]},{v['END'][1]})")
    print("JSON:")
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if not kk.endswith('_frame')}
                      for k, v in lines.items()}, ensure_ascii=False))
    print("=" * 70, flush=True)


def _surrender(battle, attack, ui, HomeScreen):
    for _ in range(3):
        try:
            battle.surrender(return_home=True)
            HomeScreen(ui).close_popups()
            if HomeScreen(ui).is_current_screen():
                return
        except Exception:
            pass
        ui._poll_sleep(1.0)
    attack._bail()


# --------------------------------------------------------------------- apply
def content_shift(f_from, f_to):
    """Map-content displacement between two frames. Patches are sampled on
    pure MAP areas only: the top-left enemy panel (x<380, y<340) and the troop
    bar / surrender area are FIXED screen UI — matching those would always
    report (0,0) and poison the measurement."""
    import cv2
    g1 = cv2.cvtColor(cv2.imread(f_from), cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(cv2.imread(f_to), cv2.COLOR_BGR2GRAY)
    half = 90
    # central, map-only spots: content here stays on-screen in BOTH frames
    # even for the largest pans (~300px), unlike margin spots which fall off
    # the edge of the other frame
    spots = ((800, 380), (650, 300), (950, 300), (650, 480), (950, 480), (800, 550))
    results = []
    for sx, sy in spots:
        patch = g1[sy - half:sy + half, sx - half:sx + half]
        if patch.shape != (2 * half, 2 * half):
            continue
        res = cv2.matchTemplate(g2, patch, cv2.TM_CCOEFF_NORMED)
        _, mv, _, ml = cv2.minMaxLoc(res)
        d = (ml[0] + half - sx, ml[1] + half - sy)
        results.append((round(float(mv), 2), d))
    print(f"    patches {f_from.split(os.sep)[-1]} -> "
          f"{f_to.split(os.sep)[-1]}: {results}", flush=True)
    # group patches by displacement: >=4 agreeing on the same shift is trusted
    # even at low confidence (a frame captured while the map was still gliding
    # matches weakly but consistently); otherwise demand >=3 strong matches.
    groups = {}
    for c, d in results:
        key = (round(d[0] / 8) * 8, round(d[1] / 8) * 8)
        groups.setdefault(key, []).append((c, d))
    best = max(groups.values(), key=len)
    strong = [d for c, d in results if c > 0.75]
    if len(best) >= 4:
        good = [d for c, d in best]
    elif len(strong) >= 3:
        good = strong
    else:
        return None
    dx = sorted(p[0] for p in good)[len(good) // 2]
    dy = sorted(p[1] for p in good)[len(good) // 2]
    return (int(dx), int(dy))


def apply():
    if not os.path.isfile(LINES):
        sys.exit("calib/lines.json not found — run the live capture first")
    data = json.load(open(LINES, encoding="utf-8"))
    lines = data["lines"]
    center_frame = os.path.join(HERE, "frame_center.png")

    pans, spell_centers, failed = {}, [], []
    for name, _x, _y in VARIANTS:
        d_cv = content_shift(center_frame, lines[name]["END_frame"])
        d = (-d_cv[0], -d_cv[1]) if d_cv else None
        if d is None:
            failed.append(name)
            continue
        pans[name] = d
        d_ab = content_shift(lines[name]["START_frame"], lines[name]["END_frame"])
        if d_ab and (abs(d_ab[0]) > 25 or abs(d_ab[1]) > 25):
            sys.exit(f"[apply] variant {name}: panned between the two taps "
                     f"(shift {d_ab}) — rerun, pan only before the first tap")
        S, E = lines[name]["START"], lines[name]["END"]
        mid = lerp(S, E, 0.5)
        spell_centers.append((mid[0] - d[0], mid[1] - d[1]))
        print(f"[apply] {name}: d={d} (pan swipe = ({800 - d[0]},{450 - d[1]}))")
    if failed:
        sys.exit(f"[apply] cannot measure pan for variant(s) {failed} — rerun the capture")

    # cross-check via the shared corners: consecutive variants tapped the SAME
    # corner in two different views, so END[i] + d[i] must ~= START[i+1] + d[i+1]
    worst = 0
    for i in range(4):
        n1, n2 = VARIANTS[i][0], VARIANTS[(i + 1) % 4][0]
        a, b = lines[n1]["END"], lines[n2]["START"]
        err = (a[0] + pans[n1][0] - b[0] - pans[n2][0],
               a[1] + pans[n1][1] - b[1] - pans[n2][1])
        worst = max(worst, abs(err[0]), abs(err[1]))
        print(f"[apply] corner check {n1}->{n2}: err=({err[0]},{err[1]})")
    if worst > 60:
        print(f"[apply] NOTE: corner cross-check worst err {worst}px (>60) — usually "
              f"just tap-placement variance on the shared corners; frame-based pan "
              f"measurements above are internally consistent, continuing.", flush=True)
    else:
        print(f"[apply] corner cross-check OK (worst {worst}px)")

    center_common = (sum(c[0] for c in spell_centers) / 4, sum(c[1] for c in spell_centers) / 4)
    print(f"[apply] village centre (centre frame): ({center_common[0]:.0f},{center_common[1]:.0f})")

    geos, warnings = {}, []
    for name, _x, _y in VARIANTS:
        S, E = lines[name]["START"], lines[name]["END"]
        d = pans[name]
        center_in_view = (center_common[0] + d[0], center_common[1] + d[1])
        geo = {}
        for key, (t1, t2) in FRACTIONS.items():
            pts = [clamp(lerp(S, E, t1)), clamp(lerp(S, E, t2))]
            for i, pt in enumerate(pts):
                raw = lerp(S, E, (t1, t2)[i])
                if pt != (round(raw[0]), round(raw[1])):
                    warnings.append(f"{name}/{key}: clamped {raw} -> {pt}")
            geo[key] = pts if key in ("dragon", "balloon") else pts[0]
        geo["rage_pts"] = [list(p) for p in SPELL_RAGE_PTS]
        geo["freeze_pts"] = [list(p) for p in SPELL_FREEZE_PTS]
        geos[name] = geo
        print(f"[apply] {name}: {json.dumps(geo)}")

    shutil.copyfile(SCEN, os.path.join(HERE, "dragon_balloon.pre_apply.bak.json"))
    doc = json.load(open(SCEN, encoding="utf-8"))
    for v in doc["variants"]:
        name, geo = v["name"], geos[v["name"]]
        d = pans[name]
        pan = {"id": f"{name}_pan", "label": f"Pan camera to {name} edge", "type": "pan",
               "after": [], "template": "", "taps": 1,
               "x1": 800, "y1": 450, "x2": 800 - d[0], "y2": 450 - d[1]}
        v["nodes"] = [n for n in v["nodes"] if n["type"] != "pan"]
        v["nodes"].insert(0, pan)
        for n in v["nodes"]:
            key = n["id"].rsplit("_", 1)[-1]
            if key in ("balloon", "dragon"):
                a, b = geo[key]
                n["x1"], n["y1"], n["x2"], n["y2"] = a[0], a[1], b[0], b[1]
                if key == "balloon":
                    n["after"] = [pan["id"]]
            elif key in ("slammer", "minion", "champ", "queen", "prince", "warden",
                         "queen_ab", "champ_ab", "prince_ab", "warden_ab"):
                n["points"] = [list(geo[key.replace("_ab", "")])]
            elif key == "rage":
                n["points"] = geo["rage_pts"]; n["taps"] = 4
            elif key == "freeze":
                n["points"] = geo["freeze_pts"]; n["taps"] = 3

    with open(SCEN, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    print(f"[apply] plan rewritten: {SCEN}")
    for w in warnings:
        print(f"[apply] WARNING: {w}")
    print("[apply] done — restart the backend, then run graph dragon_balloon_loop")


if __name__ == "__main__":
    if "--apply" in sys.argv:
        apply()
    else:
        capture()
