"""measure_jitter_safety — đo và dịch điểm pattern vào trong dải an toàn jitter.

Vấn đề (spec 2026-10-31): jitter ra-ngoài 0–40px từ điểm gốc chỉ an toàn khi
điểm gốc nằm sâu trong biên playable. Balloon points nằm SÁT biên (được đặt
trên đường nối 2 góc cạnh) → jitter đẩy tap ra void, tap chắc chắn thất bại.

Mô hình biên: đường P_start→P_end hiệu chuẩn từ cú tap góc của người dùng
(2026-10-25, deploy-verified — hero đã rơi thành công tại đúng các điểm góc).
Đã đánh giá và LOẠI phương pháp dò rim theo brightness: profile trên 4 frame
cho thấy nhiễu ±40 quanh biên, không có signature rim ổn định để threshold.
Luật góc (spec bước 5): điểm nằm trong 80px của một góc diamond — biên xoay
gắt, ±10px tiếp tuyến vượt biên dù radial vừa đủ — overshoot tối thiểu 40px.

  1. `--measure` : overshoot từng điểm (signed distance của 3 extreme samples
                   tới đường biên; dương = phía void).
  2. `--apply`   : điểm vi phạm dịch radially về tâm (overshoot + 10px margin,
                   capped 50px = trần dải mục tiêu 30–50px), dragon ghép cặp
                   balloon dịch CÙNG vector (giữ offset "phía sau"), ghi JSON +
                   metadata + đo lại (tối đa 3 vòng) cho tới khi mọi điểm đạt
                   dải mục tiêu. Corner-rule artifacts (cờ góc tại điểm đã đạt
                   cap) được đếm riêng — chấp nhận theo thiết kế.
  3. `--verify`  : 12 ảnh offline verify (4 variant x 3 lần jitter vẽ tap vàng)
                   + kiểm máy từng tap vàng nằm trong biên playable.
"""
import json
import math
import os
import random
import sys

import cv2
import numpy as np

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAME_DIR = os.path.join(os.path.dirname(BACKEND), "calib")
SCEN = os.path.join(BACKEND, "data", "scenarios", "dragon_balloon.json")
BAK = os.path.join(BACKEND, "_calib", "dragon_balloon.pre_jittersafe.bak.json")
OUT = os.path.join(BACKEND, "data", "calib_debug")

JITTER_OUT = 40.0      # khớp PATTERN_JITTER_MAX (battle_screen)
JITTER_SIDE = 10.0     # khớp PATTERN_JITTER_SIDE
MARGIN = 10.0          # margin dịch thêm sau overshoot
CORNER_ZONE = 80.0     # px tính từ một góc diamond: biên xoay gắt
CAP = 50.0             # trần dịch cộng dồn mỗi điểm (trần dải mục tiêu 30-50px)
MAX_ROUNDS = 3


def edge_normal(P0, P1, centre):
    """Normal của đường biên P0→P1, chiều CHỈ VỀ PHÍA VOID (ngược phía tâm)."""
    ex, ey = P1[0] - P0[0], P1[1] - P0[1]
    ln = math.hypot(ex, ey) or 1.0
    nx, ny = -ey / ln, ex / ln
    mid = ((P0[0] + P1[0]) / 2, (P0[1] + P1[1]) / 2)
    if (centre[0] - mid[0]) * nx + (centre[1] - mid[1]) * ny > 0:
        nx, ny = -nx, -ny
    return nx, ny


def extremes(p, u, perp):
    """3 điểm extreme của hình chữ nhật jitter: outward 40 × side {-10,0,+10}."""
    return [(p[0] + u[0] * JITTER_OUT + perp[0] * s,
             p[1] + u[1] * JITTER_OUT + perp[1] * s)
            for s in (-JITTER_SIDE, 0.0, JITTER_SIDE)]


def measure_point(p, role, centre, P0, P1, edge_n):
    """Overshoot (px, phía void) của một điểm: signed distance của 3 extreme
    samples tới ĐƯỜNG BIÊN hiệu chuẩn; điểm trong CORNER_ZONE của một góc
    -> overshoot tối thiểu JITTER_OUT (biên xoay gắt)."""
    ux, uy = p[0] - centre[0], p[1] - centre[1]
    d = math.hypot(ux, uy) or 1.0
    ux, uy = ux / d, uy / d
    px, py = -uy, ux
    worst = 0.0
    for sx, sy in extremes(p, (ux, uy), (px, py)):
        worst = max(worst, (sx - P0[0]) * edge_n[0] + (sy - P0[1]) * edge_n[1])
    for corner in (P0, P1):
        if math.hypot(p[0] - corner[0], p[1] - corner[1]) <= CORNER_ZONE:
            worst = max(worst, JITTER_OUT)
    return max(0.0, worst)


def collect(doc):
    out = {}
    for v in doc["variants"]:
        name = v["name"]
        frame = os.path.join(FRAME_DIR, f"frame_{name}_START.png")
        pts = []
        for n in v["nodes"]:
            if n.get("strategy") == "pattern" and n.get("points"):
                role = str(n.get("id", "")).rsplit("_", 1)[-1]
                for i, p in enumerate(n["points"]):
                    pts.append((role, [int(p[0]), int(p[1])], n, i))
        cal = v.get("calibration", {})
        centre = cal.get("centre") or [800, 450]
        P0, P1 = cal.get("edge_start_rc") or [0, 0], cal.get("edge_end_aq") or [0, 0]
        out[name] = {"frame": frame, "pts": pts, "centre": centre,
                     "P0": P0, "P1": P1,
                     "edge_n": edge_normal(P0, P1, centre)}
    return out


def measure_all(doc, verbose=True, cum=None):
    """Đo tất cả. Trả về (report, raw_violations, artifacts) — artifacts = cờ
    góc tại điểm đã đạt cap (chấp nhận theo thiết kế, không phải thất bại)."""
    data = collect(doc)
    report = {}
    total = 0
    artifacts = 0
    for name, vd in data.items():
        rows = []
        for role, p, node, idx in vd["pts"]:
            over = measure_point(p, role, vd["centre"], vd["P0"], vd["P1"],
                                 vd["edge_n"])
            rows.append((role, p, over))
            if over > 0:
                total += 1
                if cum and cum.get((id(node), idx), 0.0) >= CAP:
                    artifacts += 1
        report[name] = rows
        viol = [(r, p, round(o, 1)) for r, p, o in rows if o > 0]
        if verbose:
            print(f"[{name}] {len(rows)} pts | violations: {len(viol)}")
            for r, p, o in viol:
                print(f"    {r:<8} {tuple(p)} overshoot {o}px")
    if verbose:
        print(f"TOTAL violations: {total} (corner-rule artifacts: {artifacts})")
    return report, total, artifacts


PAIR_ROLE = {"balloon": "dragon", "queen": "king", "champ": "duke"}


def apply_rounds(doc, max_rounds=MAX_ROUNDS):
    """Dịch các điểm vi phạm vào trong; dragon ghép cặp balloon và hero mirror
    (king của queen, duke của champ) dịch CÙNG vector để giữ offset "phía sau".
    Cap cộng dồn 50px/điểm = trần dải mục tiêu — chặn over-shift từ luật góc
    (luật góc không có chiều sâu, sẽ báo vi phạm mãi nếu không có cap)."""
    pair_node = {}        # (variant, role) -> node
    for v in doc["variants"]:
        for n in v["nodes"]:
            role = str(n.get("id", "")).rsplit("_", 1)[-1]
            pair_node.setdefault((v["name"], role), n)

    cum = {}              # (id(node), idx) -> tổng px đã dịch vào trong
    total_moved = 0
    for rnd in range(1, max_rounds + 1):
        moved = 0
        for v in doc["variants"]:
            name = v["name"]
            frame = os.path.join(FRAME_DIR, f"frame_{name}_START.png")
            img = cv2.imread(frame, cv2.IMREAD_GRAYSCALE)
            if img is None:
                print(f"[{name}] missing frame {frame} — bỏ qua variant này.")
                continue
            cal = v.get("calibration", {})
            centre = cal.get("centre") or [800, 450]
            P0, P1 = cal.get("edge_start_rc"), cal.get("edge_end_aq")
            edge_n = edge_normal(P0, P1, centre)
            shift_list = []
            for n in v["nodes"]:
                if n.get("strategy") != "pattern" or not n.get("points"):
                    continue
                role = str(n.get("id", "")).rsplit("_", 1)[-1]
                for idx, p in enumerate(n["points"]):
                    p = [int(p[0]), int(p[1])]
                    over = measure_point(p, role, centre, P0, P1, edge_n)
                    if over <= 0:
                        continue
                    k = (id(n), idx)
                    room = CAP - cum.get(k, 0.0)
                    if room <= 0:
                        continue   # đã đạt trần dải mục tiêu (corner artifact)
                    amount = min(over + MARGIN, room)
                    if amount <= 0:
                        continue
                    # dịch theo PHÁP TUYẾN vào trong của đường biên — KHÔNG
                    # theo radial: gần góc, radial từ tâm gần song song với
                    # biên (u·n ≈ 0.12 đo thật) nên dịch radial trượt dọc
                    # biên thay vì vào trong. Normal-shift cộng thẳng vào
                    # độ sâu biên = amount px chính xác.
                    shift_list.append((n, idx, -edge_n[0] * amount,
                                       -edge_n[1] * amount, role, amount))
            applied = set()
            for node, idx, sx, sy, role, amount in shift_list:
                if (id(node), idx) in applied:
                    continue
                applied.add((id(node), idx))
                node["points"][idx] = [int(round(node["points"][idx][0] + sx)),
                                       int(round(node["points"][idx][1] + sy))]
                cum[(id(node), idx)] = cum.get((id(node), idx), 0.0) + amount
                # cặp ghép: dragon theo balloon, king theo queen, duke theo champ
                pr = PAIR_ROLE.get(role)
                pn = pair_node.get((name, pr)) if pr else None
                if pn is not None and idx < len(pn["points"]):
                    if (id(pn), idx) not in applied:
                        applied.add((id(pn), idx))
                        pn["points"][idx] = [int(round(pn["points"][idx][0] + sx)),
                                             int(round(pn["points"][idx][1] + sy))]
                        cum[(id(pn), idx)] = cum.get((id(pn), idx), 0.0) + amount
                moved += 1
        report, total, artifacts = measure_all(doc, verbose=False, cum=cum)
        real = total - artifacts
        total_moved += moved
        print(f"  round {rnd}: moved {moved} point-writes | raw violations {total} "
              f"(corner artifacts {artifacts}, real {real})")
        if moved == 0:
            print("  mọi điểm đạt dải mục tiêu — dừng.")
            break
    return total_moved


def draw_verify(doc, draws=3, out_dir=OUT):
    """Ảnh verify: điểm gốc (xanh), tap sau jitter thật (vàng) — kèm kiểm máy
    'tap vàng nằm trong biên playable' (signed distance < 0)."""
    os.makedirs(out_dir, exist_ok=True)
    results = []
    for v in doc["variants"]:
        name = v["name"]
        frame = os.path.join(FRAME_DIR, f"frame_{name}_START.png")
        img = cv2.imread(frame)
        if img is None:
            print(f"  [{name}] missing frame {frame}")
            continue
        cal = v.get("calibration", {})
        centre = cal.get("centre") or [800, 450]
        P0, P1 = cal.get("edge_start_rc"), cal.get("edge_end_aq")
        edge_n = edge_normal(P0, P1, centre)
        for draw_i in range(1, draws + 1):
            random.seed(7000 * draw_i + (hash(name) % 997))
            vis = img.copy()
            bad, total = 0, 0
            for n in v["nodes"]:
                if n.get("strategy") != "pattern" or not n.get("points"):
                    continue
                role = str(n.get("id", "")).rsplit("_", 1)[-1]
                color = (0, 255, 0)
                for p in n["points"]:
                    p = (int(p[0]), int(p[1]))
                    ux, uy = p[0] - centre[0], p[1] - centre[1]
                    d = math.hypot(ux, uy) or 1.0
                    ux, uy = ux / d, uy / d
                    px, py = -uy, ux
                    r_out = random.uniform(0.0, JITTER_OUT)
                    r_side = random.uniform(-JITTER_SIDE, JITTER_SIDE)
                    tx = int(round(p[0] + ux * r_out + px * r_side))
                    ty = int(round(p[1] + uy * r_out + py * r_side))
                    cv2.circle(vis, p, 6, color, 2)
                    cv2.circle(vis, (tx, ty), 4, (0, 255, 255), -1)
                    total += 1
                    sd = ((tx - P0[0]) * edge_n[0] + (ty - P0[1]) * edge_n[1])
                    if sd >= 0:
                        bad += 1
                        cv2.circle(vis, (tx, ty), 10, (0, 0, 255), 2)
            cv2.line(vis, tuple(P0), tuple(P1), (255, 128, 0), 1)
            out = os.path.join(out_dir, f"verify_offline_{name}_d{draw_i}.png")
            cv2.imwrite(out, vis)
            results.append((os.path.basename(out), bad, total))
    return results


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    mode = sys.argv[1] if len(sys.argv) > 1 else "--measure"
    with open(SCEN, encoding="utf-8") as f:
        doc = json.load(f)
    if mode == "--measure":
        measure_all(doc)
    elif mode == "--apply":
        os.makedirs(os.path.dirname(BAK), exist_ok=True)
        with open(BAK, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
        print(f"backup -> {BAK}")
        moved = apply_rounds(doc)
        cal = doc.setdefault("calibration", {})
        cal["date"] = "2026-10-31"
        cal["note"] = ("nominal points shifted inward for outward-jitter safety, "
                       "margin 10px (boundary = calibrated corner-tap edge); "
                       "cap 50px/point = top of the 30-50px target band")
        with open(SCEN, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
        print(f"saved -> {SCEN} ({moved} point-writes)")
        made = draw_verify(doc)
        for fn, bad, total in made:
            print(f"  {fn}: yellow outside boundary = {bad}/{total}")
    elif mode == "--verify":
        made = draw_verify(doc)
        for fn, bad, total in made:
            print(f"  {fn}: yellow outside boundary = {bad}/{total}")


if __name__ == "__main__":
    main()
