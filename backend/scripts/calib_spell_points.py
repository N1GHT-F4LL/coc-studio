"""Spell-deploy recalibration tool (offline, no device) — dragon_balloon.

Measures the ACTUAL content shift between the 2026-10-25 post-pan battle
frames (template matching on stable scenery patches), derives the missing
6-9 post-pan view from the measured shifts, draws the proposed spell points
over each variant's post-pan view, and saves review frames to
data/calib_debug/spell_<variant>_CALIB.png.

This is a TEMPORARY calibration aid — never imported by runtime code.

Run:  cd backend && ..\\.venv\\Scripts\\python.exe scripts\\calib_spell_points.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, BACKEND)

import cv2  # noqa: E402
import numpy as np  # noqa: E402

CALIB = os.path.abspath(os.path.join(BACKEND, "..", "calib"))
DEBUG_DIR = os.path.join(BACKEND, "data", "calib_debug")

FRAMES = {v: os.path.join(CALIB, f"frame_{v}_START.png")
          for v in ("9-12", "12-3", "3-6")}

# Intended pan shifts from the scenario JSON (screen dx,dy per variant).
INTENDED = {"9-12": (53, 112), "12-3": (-49, 113), "3-6": (-15, -183),
            "6-9": (53, -183)}

# Stable, UNIQUE patches (real 1600x900 coords, from the 9-12 frame) for shift
# measurement: skull rock + base building clusters (walls/TH). Low-texture
# sand/water patches false-lock on this map — buildings and the skull do not.
# Base-cluster patches survive the clamped y-shifts (see measured note below).
PATCHES = [(1180, 130, 1400, 280),   # skull rock (top-right scenery)
           (770, 460, 930, 580),     # TH block (base core)
           (450, 390, 610, 500),     # left-corner wall cluster
           (1150, 360, 1310, 480)]   # right-corner wall cluster

# Proposed spell points per variant (real coords) — EDIT and re-run to iterate.
# rage = 4 points (quadrant cores of the post-pan base), freeze = 3 (core).
#
# Measured frame relations (template-matched, skull/TH eye-verified, ±10px):
#   12-3 = 9-12 + (-103, 0)      3-6 = 9-12 + (-69, -295)      6-9 = 3-6 + (+68, 0)
# (intended pans are exact; NO clamping. 9-12/12-3 show the base's TOP ~2/3 —
# the bottom is cut by the screen edge; 3-6/6-9 show the bottom ~3/4 — the top
# is cut. Building extent (to the red border) in the 9-12 view: x[490,1245],
# y[144,880], centre ~(868,512), half ~(377,368).)
SPELL_POINTS = {
    "9-12": {
        "rage": [(725, 315), (1025, 315), (1025, 535), (725, 535)],
        "freeze": [(875, 360), (795, 470), (955, 470)],
    },
    "12-3": {
        "rage": [(622, 315), (922, 315), (922, 535), (622, 535)],
        "freeze": [(772, 360), (692, 470), (852, 470)],
    },
    "3-6": {
        "rage": [(592, 180), (1012, 180), (692, 400), (912, 400)],
        "freeze": [(799, 240), (702, 360), (897, 360)],
    },
    "6-9": {
        "rage": [(660, 180), (1080, 180), (760, 400), (980, 400)],
        "freeze": [(867, 240), (770, 360), (965, 360)],
    },
}


def load(name):
    img = cv2.imread(os.path.join(CALIB, f"frame_{name}_START.png"))
    if img is None:
        sys.exit(f"missing frame: {name}")
    return img


def measure_shift(img_a, img_b, patches):
    """Median content shift A->B over the given patches (real px)."""
    ga = cv2.cvtColor(img_a, cv2.COLOR_BGR2GRAY)
    gb = cv2.cvtColor(img_b, cv2.COLOR_BGR2GRAY)
    shifts = []
    for (x1, y1, x2, y2) in patches:
        tpl = ga[y1:y2, x1:x2]
        if tpl.size == 0:
            continue
        res = cv2.matchTemplate(gb, tpl, cv2.TM_CCOEFF_NORMED)
        _, mv, _, ml = cv2.minMaxLoc(res)
        if mv < 0.55:
            continue  # patch not confidently found in B
        shifts.append((ml[0] - x1, ml[1] - y1, mv))
    if not shifts:
        return None
    dx = int(np.median([s[0] for s in shifts]))
    dy = int(np.median([s[1] for s in shifts]))
    return (dx, dy), shifts


def draw_variant(base_img, shift, variant, out_path):
    """Draw the spell points (shifted into this variant's view) on the frame."""
    img = base_img.copy()
    sp = SPELL_POINTS[variant]
    for pt in sp["rage"]:
        cv2.circle(img, tuple(pt), 9, (0, 0, 255), -1)          # rage = red
        cv2.circle(img, tuple(pt), 16, (0, 0, 255), 2)
    for pt in sp["freeze"]:
        cv2.drawMarker(img, tuple(pt), (255, 0, 255), cv2.MARKER_TILTED_CROSS,
                       26, 3)                                    # freeze = magenta
    cv2.putText(img, f"{variant} rage x4 (red) / freeze x3 (magenta)",
                (30, 860), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(img, f"{variant} rage x4 (red) / freeze x3 (magenta)",
                (30, 860), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.imwrite(out_path, img)
    return out_path


def building_mask(img):
    """Objective base-footprint estimate: buildings/walls are anything that is
    NOT grass-green and NOT water-blue (HSV). Biggest blob in the play area
    (above the troop bar) = the enemy base."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0].astype(int), hsv[..., 1].astype(int), hsv[..., 2].astype(int)
    grass = (h >= 30) & (h <= 75) & (s >= 60) & (v >= 40)
    water = (h >= 85) & (h <= 125) & (s >= 60)
    bg = grass | water
    fg = (~bg).astype(np.uint8) * 255
    play = np.zeros_like(fg)
    play[95:730, 20:1580] = fg[95:730, 20:1580]
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31))
    m = cv2.morphologyEx(play, cv2.MORPH_CLOSE, k)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (15, 15)))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m)
    if n < 2:
        return None
    best = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, w, h2, area = stats[best]
    if area < 20000:
        return None
    return (int(x), int(y), int(x + w), int(y + h2)), (lab == best).astype(np.uint8)


def draw_grid(img):
    """100px reference grid (labels every 200px, yellow) so positions can be
    read directly in real 1600x900 coordinates from the review frame."""
    for x in range(0, img.shape[1], 100):
        cv2.line(img, (x, 0), (x, img.shape[0]), (255, 255, 255), 1)
        if x % 200 == 0:
            cv2.putText(img, str(x), (x + 3, 620), cv2.FONT_HERSHEY_SIMPLEX,
                        0.55, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(img, str(x), (x + 3, 620), cv2.FONT_HERSHEY_SIMPLEX,
                        0.55, (0, 255, 255), 1, cv2.LINE_AA)
    for y in range(0, img.shape[0], 100):
        cv2.line(img, (0, y), (img.shape[1], y), (255, 255, 255), 1)
        if y % 200 == 0 and y > 0:
            cv2.putText(img, str(y), (6, y + 18), cv2.FONT_HERSHEY_SIMPLEX,
                        0.55, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(img, str(y), (6, y + 18), cv2.FONT_HERSHEY_SIMPLEX,
                        0.55, (0, 255, 255), 1, cv2.LINE_AA)


def analyze_variant(img, variant, shift, out_path):
    """Draw the detected base footprint + spell points on the frame."""
    img = img.copy()
    draw_grid(img)
    r = building_mask(img)
    if r is not None:
        (x1, y1, x2, y2), mask = r
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(img, cnts, -1, (0, 255, 0), 3)
        m = cv2.moments(mask, binaryImage=True)
        cx, cy = int(m["m10"] / m["m00"]), int(m["m01"] / m["m00"])
        cv2.drawMarker(img, (cx, cy), (0, 255, 0), cv2.MARKER_CROSS, 30, 2)
        print(f"  {variant}: base bbox=({x1},{y1})-({x2},{y2}) centroid=({cx},{cy})")
    sp = SPELL_POINTS[variant]
    for pt in sp["rage"]:
        cv2.circle(img, tuple(pt), 9, (0, 0, 255), -1)
        cv2.circle(img, tuple(pt), 16, (0, 0, 255), 2)
    for pt in sp["freeze"]:
        cv2.drawMarker(img, tuple(pt), (255, 0, 255), cv2.MARKER_TILTED_CROSS, 26, 3)
    cv2.putText(img, f"{variant} rage x4 (red) / freeze x3 (magenta) / base detect (green)",
                (30, 865), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(img, f"{variant} rage x4 (red) / freeze x3 (magenta) / base detect (green)",
                (30, 865), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.imwrite(out_path, img)


def apply_to_scenario():
    """Write the measured spell points into data/scenarios/dragon_balloon.json
    (data-only: points/taps/interval per node + calibration metadata)."""
    import json

    scen = os.path.join(BACKEND, "data", "scenarios", "dragon_balloon.json")
    bak = os.path.join(BACKEND, "_calib", "dragon_balloon.pre_spell_recalib.bak.json")
    with open(scen, encoding="utf-8") as f:
        doc = json.load(f)
    os.makedirs(os.path.dirname(bak), exist_ok=True)
    with open(bak, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    print(f"backup -> {os.path.relpath(bak, BACKEND)}")

    for v in doc["variants"]:
        sp = SPELL_POINTS[v["name"]]
        for n in v["nodes"]:
            stem = (n.get("template") or "").rsplit("/", 1)[-1]
            if n.get("type") != "spell":
                continue
            if stem == "rage":
                new, want_taps, want_itv = sp["rage"], 4, 1.0
            elif stem == "freeze":
                new, want_taps, want_itv = sp["freeze"], 3, 2.0
            else:
                continue
            old = n.get("points")
            assert int(n.get("taps", 0)) == want_taps, f"{v['name']}/{stem}: taps changed?"
            assert abs(float(n.get("interval", 0)) - want_itv) < 1e-9, \
                f"{v['name']}/{stem}: interval changed?"
            n["points"] = [list(p) for p in new]
            print(f"{v['name']}/{stem}: {old} -> {n['points']} "
                  f"(taps={want_taps}, interval={want_itv})")

    cal = doc.setdefault("calibration", {})
    cal["date"] = "2026-11-01"
    cal["spell_points"] = "recalibrated per-variant over the post-pan base region " \
                          "(rage 4 / freeze 3, intervals unchanged 1.0s / 2.0s)"
    cal["spell_frame_relations"] = {
        "12-3": [-103, 0], "3-6": [-69, -295], "6-9_from_3-6": [68, 0],
        "method": "phase correlation + template match on 2026-10-25 battle frames",
    }
    with open(scen, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    print(f"written -> {os.path.relpath(scen, BACKEND)}")


def main():
    imgs = {v: load(v) for v in FRAMES}

    print("=== measured content shifts (actual, template-matched) ===")
    measured = {}
    pairs = [("9-12", "12-3"), ("9-12", "3-6"), ("12-3", "3-6")]
    for a, b in pairs:
        r = measure_shift(imgs[a], imgs[b], PATCHES)
        if r is None:
            print(f"{a} -> {b}: NOT MEASURABLE")
            continue
        (dx, dy), per = r
        intended = (INTENDED[b][0] - INTENDED[a][0], INTENDED[b][1] - INTENDED[a][1])
        measured[(a, b)] = (dx, dy)
        print(f"{a} -> {b}: measured ({dx:+d},{dy:+d})  intended {intended}  "
              f"[{len(per)} patches, conf {min(p[2] for p in per):.2f}-{max(p[2] for p in per):.2f}]")
        for s in per:
            print(f"    patch ({s[0]:+d},{s[1]:+d}) conf {s[2]:.2f}")

    # per-variant shift vs the 9-12 view (measured where possible, chained
    # otherwise) — this is what places the base in each variant's view.
    rel = {"9-12": (0, 0)}
    if ("9-12", "12-3") in measured:
        rel["12-3"] = measured[("9-12", "12-3")]
    else:
        rel["12-3"] = (INTENDED["12-3"][0] - INTENDED["9-12"][0],
                       INTENDED["12-3"][1] - INTENDED["9-12"][1])
    if ("9-12", "3-6") in measured:
        rel["3-6"] = measured[("9-12", "3-6")]
    else:
        rel["3-6"] = (INTENDED["3-6"][0] - INTENDED["9-12"][0],
                      INTENDED["3-6"][1] - INTENDED["9-12"][1])
    # 6-9: no live frame exists. Derive from the MEASURED 3-6 view: the x axis
    # is unclamped (skull check), so delta-x = intended x-diff (6-9 vs 3-6);
    # the y axis clamps at the map's top edge for BOTH up-pans -> same y.
    err = [abs(measured[p][i] - (INTENDED[p[1]][i] - INTENDED[p[0]][i]))
           for p in measured for i in (0, 1)] or [999]
    print(f"\nintended-model error on measurable pairs: max {max(err)}px, "
          f"mean {sum(err) / len(err):.0f}px")
    if ("9-12", "3-6") in measured:
        rel["6-9"] = (rel["3-6"][0] + INTENDED["6-9"][0] - INTENDED["3-6"][0],
                      rel["3-6"][1])
        print("6-9 derived from measured 3-6 view + unclamped x-diff "
              f"(+{INTENDED['6-9'][0] - INTENDED['3-6'][0]}, 0)")
    else:
        rel["6-9"] = (INTENDED["6-9"][0] - INTENDED["9-12"][0],
                      INTENDED["6-9"][1] - INTENDED["9-12"][1])
    print("\nper-variant base view offset vs 9-12 frame:", rel)

    os.makedirs(DEBUG_DIR, exist_ok=True)
    print("\n=== drawing spell points + detected base footprint ===")
    for v in ("9-12", "12-3", "3-6", "6-9"):
        dx, dy = rel[v]
        # 12-3/3-6 have their own frames; 6-9 is derived by shifting the
        # 9-12 frame content by the measured/modelled offset.
        if v in imgs:
            src = imgs[v]
        else:
            M = np.float32([[1, 0, dx], [0, 1, dy]])
            src = cv2.warpAffine(imgs["9-12"], M, (imgs["9-12"].shape[1],
                                                   imgs["9-12"].shape[0]))
        out = os.path.join(DEBUG_DIR, f"spell_{v}_CALIB.png")
        analyze_variant(src, v, rel[v], out)
        print("  saved", os.path.relpath(out, BACKEND))

    print("\n===== RESULT =====")
    print("Measured shifts vs intended (see above) validate the pan model.")
    print("Review frames: backend/data/calib_debug/spell_<variant>_CALIB.png")
    print("Points live in scripts/calib_spell_points.py SPELL_POINTS (edit + re-run).")
    if "--apply" in sys.argv:
        print("\n=== applying to dragon_balloon.json ===")
        apply_to_scenario()


if __name__ == "__main__":
    main()
