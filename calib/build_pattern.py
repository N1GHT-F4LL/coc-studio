"""build_pattern — hiệu chuẩn pattern biên ngoài cho dragon_balloon (4 variant).

Dữ liệu vào (đã đo trên thiết bị 2026-10-25, run_calib v3):
  - Góc đầu/cuối mỗi cạnh map: tap START = royal_champion (P_start), tap END =
    archer_queen (P_end) — chụp trên VIEW SAU PAN của từng variant.
  - Pan node của variant (swipe 800,450 -> x2,y2) => độ dịch chuyển nội dung
    map trên màn hình = (x2-800, y2-450); tâm làng ở view variant =
    tâm_làng_frame_trung tâm (815,367) + dịch chuyển đó.

Sinh ra:
  - `data/scenarios/dragon_balloon.json` mới: balloon 14 điểm DỌC BIÊN NGOÀI
    (0%..100% cạnh), dragon 14 điểm cùng biên dịch vào trong 45px về hướng tâm,
    slammer = điểm giữa biên, minion = điểm giữa dải dragon, heroes theo pattern
    (queen/king = đầu aq, champ/duke = đầu rc, prince 40% / warden 60% trên
    dải dragon), spells GIỮ NGUYÊN. Tương thích ngược: chỉ thêm strategy
    "pattern", node line/points cũ của scenario khác không bị đụng.
  - 12 ảnh debug vào `backend/data/calib_debug/` (START + END + detail-zoom
    cho từng variant) để người dùng duyệt từng variant.

Chạy:  cd backend && ..\\.venv\\Scripts\\python.exe ..\\calib\\build_pattern.py
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.abspath(os.path.join(HERE, "..", "backend"))
sys.path.insert(0, BACKEND)

import cv2  # noqa: E402

SCEN_PATH = os.path.join(BACKEND, "data", "scenarios", "dragon_balloon.json")
BAK_PATH = os.path.join(BACKEND, "_calib", "dragon_balloon.pre_pattern.bak.json")
DEBUG_DIR = os.path.join(BACKEND, "data", "calib_debug")
FRAME_DIR = os.path.join(HERE)          # calib/frame_<variant>_{START,END}.png

DRAGON_INSET = 45        # px vào trong từ biên (đặc tả: 30-60)
CENTRE_FRAME_CENTRE = (815, 367)   # tâm làng đo trên frame_center (2026-10-25)

# Góc cạnh map đã TAP chuẩn trên view sau-pan của từng variant (2026-10-25):
# START = royal_champion corner, END = archer_queen corner.
EDGES = {
    "9-12": {"start": (189, 542), "end": (777, 103)},
    "12-3": {"start": (802, 105), "end": (1401, 543)},
    "3-6":  {"start": (1410, 266), "end": (879, 695)},
    "6-9":  {"start": (757, 695), "end": (218, 268)},
}
N_POINTS = 14


def lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def round_pt(p):
    return [int(round(p[0])), int(round(p[1]))]


def build_variant(name, edge, pan_shift):
    rc, aq = edge["start"], edge["end"]
    centre = (CENTRE_FRAME_CENTRE[0] + pan_shift[0],
              CENTRE_FRAME_CENTRE[1] + pan_shift[1])

    # pháp tuyến của cạnh, chiều DẤNG VÀO map (về phía tâm làng)
    ux, uy = aq[0] - rc[0], aq[1] - rc[1]
    ln = math.hypot(ux, uy) or 1.0
    ux, uy = ux / ln, uy / ln
    nx, ny = -uy, ux
    mid = ((rc[0] + aq[0]) / 2, (rc[1] + aq[1]) / 2)
    if (centre[0] - mid[0]) * nx + (centre[1] - mid[1]) * ny < 0:
        nx, ny = -nx, -ny

    balloon = [round_pt(lerp(rc, aq, i / (N_POINTS - 1))) for i in range(N_POINTS)]
    dragon = [round_pt((p[0] + nx * DRAGON_INSET, p[1] + ny * DRAGON_INSET))
              for p in (lerp(rc, aq, i / (N_POINTS - 1)) for i in range(N_POINTS))]
    mid_edge = round_pt(lerp(rc, aq, 0.5))
    slammer = mid_edge
    minion = round_pt((mid_edge[0] + nx * DRAGON_INSET, mid_edge[1] + ny * DRAGON_INSET))
    queen = list(aq)
    champ = list(rc)
    prince = round_pt((lerp(rc, aq, 0.40)[0] + nx * DRAGON_INSET,
                       lerp(rc, aq, 0.40)[1] + ny * DRAGON_INSET))
    warden = round_pt((lerp(rc, aq, 0.60)[0] + nx * DRAGON_INSET,
                       lerp(rc, aq, 0.60)[1] + ny * DRAGON_INSET))

    # tâm hiệu chuẩn = trọng tâm dải dragon (proxy "hướng tâm base" cho jitter)
    cal_centre = round_pt((sum(p[0] for p in dragon) / N_POINTS,
                           sum(p[1] for p in dragon) / N_POINTS))
    return {
        "balloon": balloon, "dragon": dragon, "slammer": slammer,
        "minion": minion, "queen": queen, "champ": champ,
        "prince": prince, "warden": warden,
        "centre": cal_centre, "inset_normal": [round(nx, 3), round(ny, 3)],
        "centre_est": [int(centre[0]), int(centre[1])],
    }


def apply_to_doc(doc, patterns):
    for v in doc["variants"]:
        p = patterns[v["name"]]
        by_role = {}
        for n in v["nodes"]:
            role = str(n.get("id", "")).rsplit("_", 1)[-1]
            by_role[role] = n
        by_role["balloon"].update({"strategy": "pattern", "points": p["balloon"], "taps": 14})
        by_role["dragon"].update({"strategy": "pattern", "points": p["dragon"], "taps": 14})
        by_role["slammer"].update({"strategy": "pattern", "points": [p["slammer"]], "taps": 3})
        by_role["minion"].update({"strategy": "pattern", "points": [p["minion"]], "taps": 1})
        for role, pt in (("queen", p["queen"]), ("champ", p["champ"]),
                         ("prince", p["prince"]), ("warden", p["warden"])):
            by_role[role].update({"strategy": "pattern", "points": [pt], "taps": 1})
            ab = by_role.get(role + "_ab")
            if ab is not None:
                ab["points"] = [list(pt)]     # mirror (taps=0 -> không tap toạ độ)
        # king/duke là fallback của queen/champ — mirror toạ độ tương ứng
        for fallback_role, src in (("king", "queen"), ("duke", "champ")):
            n = by_role.get(fallback_role)
            if n is not None:
                n.update({"strategy": "pattern",
                          "points": [list(by_role[src]["points"][0])], "taps": 1})
                ab = by_role.get(fallback_role + "_ab")
                if ab is not None:
                    ab["points"] = [list(n["points"][0])]
        # nhịp spell theo đặc tả (interval dữ liệu, không hardcode trong code)
        for n in v["nodes"]:
            if n.get("type") == "spell":
                stem = (n.get("template") or "").rsplit("/", 1)[-1]
                if stem == "rage":
                    n["interval"] = 1.0
                elif stem == "freeze":
                    n["interval"] = 2.0
        v["calibration"] = {
            "centre": p["centre"],
            "inset_normal": p["inset_normal"],
            "centre_est_from_pan": p["centre_est"],
            "edge_start_rc": EDGES[v["name"]]["start"],
            "edge_end_aq": EDGES[v["name"]]["end"],
            "dragon_inset_px": DRAGON_INSET,
        }
    doc["calibration"] = {
        "design": "outer-border static pattern (user spec 2026-10-29) — deploy "
                  "never analyses the enemy base at runtime",
        "resolution": "1600x900",
        "date": "2026-10-29",
        "bases_verified": 0,
        "source_frames": "calib/frame_<variant>_{START,END}.png (2026-10-25 run_calib)",
        "dragon_inset_px": DRAGON_INSET,
    }


def draw_debug(doc, patterns):
    os.makedirs(DEBUG_DIR, exist_ok=True)
    made = []
    for v in doc["variants"]:
        name = v["name"]
        p = patterns[name]
        for suffix in ("START", "END"):
            frame_path = os.path.join(FRAME_DIR, f"frame_{name}_{suffix}.png")
            img = cv2.imread(frame_path)
            if img is None:
                print(f"  (skip — missing frame {frame_path})")
                continue
            cv2.line(img, tuple(EDGES[name]["start"]), tuple(EDGES[name]["end"]),
                     (255, 0, 0), 1)                       # biên ngoài (xanh)
            for i, pt in enumerate(p["balloon"]):
                cv2.circle(img, tuple(pt), 6, (0, 0, 255), -1)     # balloon = đỏ
                cv2.putText(img, str(i), (pt[0] + 8, pt[1] - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1, cv2.LINE_AA)
            for i, pt in enumerate(p["dragon"]):
                cv2.circle(img, tuple(pt), 5, (0, 255, 255), -1)   # dragon = vàng
            for role, color in (("slammer", (255, 0, 255)), ("minion", (0, 255, 0)),
                                ("queen", (255, 255, 0)), ("champ", (255, 255, 0)),
                                ("prince", (255, 128, 0)), ("warden", (255, 128, 0))):
                pt = p[role]
                cv2.drawMarker(img, tuple(pt), color, cv2.MARKER_TILTED_CROSS, 18, 2)
                cv2.putText(img, role, (pt[0] + 10, pt[1] + 4),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
            c = p["centre"]
            cv2.drawMarker(img, tuple(c), (0, 0, 255), cv2.MARKER_CROSS, 26, 2)
            out = os.path.join(DEBUG_DIR, f"pattern_{name}_{suffix}.png")
            cv2.imwrite(out, img)
            made.append(out)
        # detail zoom 2x quanh dải pattern của variant
        frame_path = os.path.join(FRAME_DIR, f"frame_{name}_START.png")
        img = cv2.imread(frame_path)
        if img is not None:
            xs = [pt[0] for pt in p["balloon"] + p["dragon"]]
            ys = [pt[1] for pt in p["balloon"] + p["dragon"]]
            x1, x2 = max(0, min(xs) - 40), min(1600, max(xs) + 40)
            y1, y2 = max(0, min(ys) - 40), min(900, max(ys) + 40)
            crop = img[y1:y2, x1:x2]
            crop = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
            out = os.path.join(DEBUG_DIR, f"pattern_{name}_detail.png")
            cv2.imwrite(out, crop)
            made.append(out)
    return made


def main():
    with open(SCEN_PATH, encoding="utf-8") as f:
        doc = json.load(f)
    os.makedirs(os.path.dirname(BAK_PATH), exist_ok=True)
    with open(BAK_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    print(f"backup -> {BAK_PATH}")

    pans = {}
    for v in doc["variants"]:
        pan = next((n for n in v["nodes"] if n.get("type") == "pan"), None)
        pans[v["name"]] = (pan["x2"] - pan["x1"], pan["y2"] - pan["y1"])

    patterns = {name: build_variant(name, EDGES[name], pans[name]) for name in EDGES}
    apply_to_doc(doc, patterns)
    with open(SCEN_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    print(f"written -> {SCEN_PATH}")

    made = draw_debug(doc, patterns)
    print(f"debug images ({len(made)}):")
    for m in made:
        print("  ", os.path.relpath(m, BACKEND))

    print("\n=== pattern summary (per variant) ===")
    for name, p in patterns.items():
        xs_b = [pt[0] for pt in p["balloon"]]
        ys_b = [pt[1] for pt in p["balloon"]]
        xs_d = [pt[0] for pt in p["dragon"]]
        ys_d = [pt[1] for pt in p["dragon"]]
        print(f"{name}: balloon 14 pts x[{min(xs_b)}..{max(xs_b)}] y[{min(ys_b)}..{max(ys_b)}]"
              f" | dragon 14 pts x[{min(xs_d)}..{max(xs_d)}] y[{min(ys_d)}..{max(ys_d)}]"
              f" | centre={p['centre']} | minion={p['minion']} slammer={p['slammer']}")


if __name__ == "__main__":
    main()
