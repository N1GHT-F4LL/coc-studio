"""Measure the hammer template against real device frames (offline, no device).

Reads backend/data/calib_debug/treasure_{active,chest,clean}.png (captured by
scripts/capture_treasure_frames.py) and reports:
  - active_max / clean_max: best _match_template score of popups/hammer.png
    inside TREASURE_HAMMER_ROI — uses popup_guard's own matcher (scale sweep
    included) so the numbers ARE the runtime's.
  - Return Home check: best match of buttons/battle/btn_return_home.png near
    TREASURE_HOME_TAP on the chest frame -> measured centre vs the constant.
  - debug frames (ROI + tap markers + match locations) for human review.

  --recrop x1,y1,x2,y2   re-crop the hammer from treasure_active.png (old PNG
                         backed up to _calib/), re-measure, suggest threshold.

Run (from backend/):  ..\\.venv\\Scripts\\python.exe -X utf8 scripts\\measure_treasure_template.py
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import popup_guard  # noqa: E402  (runtime matcher + constants, single source)

DEBUG_DIR = os.path.join(BACKEND, "data", "calib_debug")
HAMMER = popup_guard.POPUP_TPL_DIR / "hammer.png"
RETURN_HOME_TPL = os.path.join(BACKEND, "assets", "buttons", "battle", "btn_return_home.png")
HAMMER_BAK = os.path.join(BACKEND, "_calib", "hammer.cross_capture.bak.png")


def load(name):
    path = os.path.join(DEBUG_DIR, name)
    img = cv2.imread(path)
    if img is None:
        sys.exit(f"missing frame: {path} — run scripts/capture_treasure_frames.py first")
    return img


def draw_debug(active, chest, roi_max_loc, rh_loc):
    dbg = active.copy()
    x1, y1, x2, y2 = popup_guard.TREASURE_HAMMER_ROI
    cv2.rectangle(dbg, (x1, y1), (x2, y2), (0, 255, 255), 2)
    cv2.putText(dbg, "TREASURE_HAMMER_ROI", (x1, y1 - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1, cv2.LINE_AA)
    if roi_max_loc is not None:
        cv2.drawMarker(dbg, roi_max_loc, (0, 0, 255), cv2.MARKER_CROSS, 30, 2)
    tx, ty = popup_guard.TREASURE_TAP
    cv2.circle(dbg, (tx, ty), 12, (0, 0, 255), 2)
    cv2.putText(dbg, f"TREASURE_TAP {popup_guard.TREASURE_TAP}", (tx + 14, ty + 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 1, cv2.LINE_AA)
    cv2.imwrite(os.path.join(DEBUG_DIR, "treasure_debug.png"), dbg)

    if rh_loc is not None:
        cb = chest.copy()
        hx, hy = popup_guard.TREASURE_HOME_TAP
        cv2.circle(cb, (hx, hy), 12, (255, 0, 255), 2)
        cv2.putText(cb, f"TREASURE_HOME_TAP {popup_guard.TREASURE_HOME_TAP}",
                    (hx - 180, hy - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (255, 0, 255), 1, cv2.LINE_AA)
        mx, my = rh_loc
        cv2.drawMarker(cb, (mx, my), (0, 255, 0), cv2.MARKER_CROSS, 30, 2)
        cv2.putText(cb, "measured Return Home", (mx + 14, my + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1, cv2.LINE_AA)
        cv2.imwrite(os.path.join(DEBUG_DIR, "treasure_chest_debug.png"), cb)


def measure(active, clean):
    roi = popup_guard.TREASURE_HAMMER_ROI
    active_max = popup_guard._match_template(active, HAMMER, region=roi)
    clean_max = popup_guard._match_template(clean, HAMMER, region=roi)
    return float(active_max), float(clean_max)


def hammer_loc_in_roi(active):
    """Top-left of the best hammer match inside the ROI (for the debug frame)."""
    tpl = popup_guard.imread_template(str(HAMMER), cv2.IMREAD_GRAYSCALE)
    if tpl is None:
        return None
    x1, y1, x2, y2 = popup_guard.TREASURE_HAMMER_ROI
    crop = cv2.cvtColor(active[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    res = cv2.matchTemplate(crop, tpl, cv2.TM_CCOEFF_NORMED)
    _, _, _, ml = cv2.minMaxLoc(res)
    return (x1 + ml[0] + tpl.shape[1] // 2, y1 + ml[1] + tpl.shape[0] // 2)


def return_home_check(chest):
    """Where is the Return Home button really, vs TREASURE_HOME_TAP?"""
    tpl = cv2.imread(RETURN_HOME_TPL, cv2.IMREAD_GRAYSCALE)
    if tpl is None:
        print("  (no btn_return_home template — skip location check)")
        return None
    hx, hy = popup_guard.TREASURE_HOME_TAP
    win = 220
    H, W = chest.shape[:2]
    x1, y1 = max(0, hx - win), max(0, hy - win)
    x2, y2 = min(W, hx + win), min(H, hy + win)
    crop = cv2.cvtColor(chest[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    res = cv2.matchTemplate(crop, tpl, cv2.TM_CCOEFF_NORMED)
    _, mv, _, ml = cv2.minMaxLoc(res)
    centre = (x1 + ml[0] + tpl.shape[1] // 2, y1 + ml[1] + tpl.shape[0] // 2)
    off = (centre[0] - hx, centre[1] - hy)
    print(f"  Return Home on chest frame: conf {mv:.3f} at {centre} "
          f"(constant {popup_guard.TREASURE_HOME_TAP}, offset {off})")
    return centre if mv >= 0.6 else None


def recrop(active, box):
    x1, y1, x2, y2 = (int(v) for v in box.split(","))
    crop = active[y1:y2, x1:x2]
    if crop.size == 0:
        sys.exit("recrop box empty")
    os.makedirs(os.path.dirname(HAMMER_BAK), exist_ok=True)
    if not os.path.isfile(HAMMER_BAK):
        shutil.copy2(HAMMER, HAMMER_BAK)
        print(f"old template backed up -> {os.path.relpath(HAMMER_BAK, BACKEND)}")
    ok, buf = cv2.imencode(".png", crop)
    assert ok
    buf.tofile(str(HAMMER))
    print(f"hammer.png re-cropped {x2 - x1}x{y2 - y1} from treasure_active.png")


def main():
    recrop_box = next((a.split("=", 1)[1] for a in sys.argv[1:]
                       if a.startswith("--recrop=")), None)
    active, clean, chest = load("treasure_active.png"), load("treasure_clean.png"), load("treasure_chest.png")
    if recrop_box:
        recrop(active, recrop_box)

    active_max, clean_max = measure(active, clean)
    gap = active_max - clean_max
    print(f"\nactive_max = {active_max:.3f}")
    print(f"clean_max  = {clean_max:.3f}")
    print(f"gap        = {gap:.3f}")
    print(f"current TREASURE_HAMMER_THRESHOLD = {popup_guard.TREASURE_HAMMER_THRESHOLD}")
    if active_max >= 0.8 and gap >= 0.15:
        print("DECISION: template passes as-is (active_max >= 0.8) — keep 0.8.")
    else:
        mid = round((active_max + clean_max) / 2, 3)
        print(f"DECISION: template cross-capture unreliable -> suggest "
              f"TREASURE_HAMMER_THRESHOLD = midpoint = {mid} "
              f"({'gap OK' if gap >= 0.15 else 'gap < 0.15 — RECROP the template from the active frame instead'})")

    rh = return_home_check(chest)
    hloc = hammer_loc_in_roi(active)
    if hloc:
        print(f"hammer best-match centre in ROI: {hloc} vs TREASURE_TAP "
              f"{popup_guard.TREASURE_TAP}")
    draw_debug(active, chest, hloc, rh)
    print("debug frames: data/calib_debug/treasure_debug.png + treasure_chest_debug.png")

    print("\n===== RESULT =====")
    print(f"active_max={active_max:.3f} clean_max={clean_max:.3f} "
          f"threshold_now={popup_guard.TREASURE_HAMMER_THRESHOLD} "
          f"home_offset={None if rh is None else (rh[0] - popup_guard.TREASURE_HOME_TAP[0], rh[1] - popup_guard.TREASURE_HOME_TAP[1])}")
    print("=====")


if __name__ == "__main__":
    main()
