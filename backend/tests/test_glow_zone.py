"""Unit tests for glow_zone.py — synthetic images only, no device.

Run:  cd backend && ..\\.venv\\Scripts\\python.exe tests\\test_glow_zone.py

Covers the acceptance criteria of the glowing-border red-zone spec:
  1. white 3px line at ~45deg on green bg -> get_glow_drop_points returns >=4
     points ON the line (<=15px off)
  2. plain green frame, no line -> [ROI centre], no raise
  3. _nudge_inside on the white line moves the point to a GREENER pixel
  4. dedup: two points 10px apart collapse to one; 20 candidates -> <=12
  5. detect_bright_field_drop_points: (x,y,w,h) and (x1,y1,x2,y2) for the same
     region agree; conf in [0,1]
  6. line vanishes on a later frame -> cached _last_good_points, conf 0.15
"""
import math
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import glow_zone
from glow_zone import (detect_bright_field_drop_points, get_glow_drop_points,
                       _nudge_inside, _dedup_cap, _points_along,
                       red_fill_fraction, _in_thick_red, _hide_obstacles,
                       _auto_binary, _white_tophat, point_segment_dist,
                       detect_border_ring_segments)

passed = 0
failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS {name}")
    else:
        failed += 1
        print(f"  FAIL {name} {extra}")


GREEN = (60, 160, 60)     # BGR grass
WHITE = (255, 255, 255)


def green_frame(w, h):
    return np.full((h, w, 3), GREEN, np.uint8)


def draw_white_line(img, p1, p2, thick=3):
    cv2.line(img, p1, p2, WHITE, thick)
    return img


def dist_point_line(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    ln = math.hypot(dx, dy) or 1.0
    return abs((px - x1) * dy - (py - y1) * dx) / ln


def greenness(img, x, y):
    b, g, r = img[int(y), int(x)]
    return int(g) - (int(r) + int(b)) // 2


def test_pipeline_a_line():
    print("[1] 45deg white line on green -> >=4 points on the line")
    img = green_frame(600, 600)
    p1, p2 = (40, 40), (560, 560)          # ~45deg across the whole frame
    draw_white_line(img, p1, p2)
    pts = get_glow_drop_points(img, tl=(0, 0), br=(599, 599))
    check("returns >=4 points", isinstance(pts, list) and len(pts) >= 4,
          f"got {len(pts) if isinstance(pts, list) else pts}")
    on_line = [p for p in pts
               if dist_point_line(p[0], p[1], p1[0], p1[1], p2[0], p2[1]) <= 15]
    check(">=4 points within 15px of the line", len(on_line) >= 4,
          f"on-line: {len(on_line)} of {len(pts)}")


def test_pipeline_a_no_line():
    print("[2] plain green, no line -> [ROI centre], no raise")
    img = green_frame(600, 600)
    pts = get_glow_drop_points(img, tl=(100, 100), br=(500, 500))
    check("returns the ROI centre", pts == [(300, 300)], f"got {pts}")


def test_nudge_inside():
    print("[3] _nudge_inside moves an on-line point toward green")
    img = green_frame(400, 400)
    # horizontal white line at y=200; test point sits ON it
    draw_white_line(img, (0, 200), (399, 200))
    pt = (200, 200)
    before = greenness(img, *pt)
    nx, ny = _nudge_inside(pt, img, step=12)
    after = greenness(img, nx, ny)
    check("new point is greener than the old one", after > before,
          f"before={before} after={after} at {(nx, ny)}")
    check("point actually moved off the line", abs(ny - 200) >= 1)


def test_dedup_cap():
    print("[4] dedup 10px pair -> 1; 20 candidates -> <=12")
    kept = _dedup_cap([(100, 100), (110, 100)])           # 10px apart on x, same y
    check("10px-apart pair collapses to 1", len(kept) == 1, f"got {len(kept)}")
    twenty = [(i * 25, (i * 37) % 500) for i in range(20)]  # well separated
    kept = _dedup_cap(twenty)
    check("20 candidates capped at 12", len(kept) <= 12, f"got {len(kept)}")
    # and _points_along midpoints, not ends
    pts = _points_along(0, 0, 360, 0, 180)                # n=3: 60/180/300
    check("_points_along spreads midpoints", pts == [(60, 0), (180, 0), (300, 0)],
          f"got {pts}")


def test_detect_roi_forms_and_conf():
    print("[5] detect: (x,y,w,h) == (x1,y1,x2,y2); conf in [0,1]")
    frame = green_frame(1200, 900)
    # diagonal white line inside region (600,450)-(900,650)
    draw_white_line(frame, (610, 640), (890, 460))
    w_form = (600, 450, 300, 200)          # w=300 <= 1200//3, h=200 <= 900//3
    c_form = (600, 450, 900, 650)          # x2=900 > 400 -> corner form
    glow_zone._last_good_points = []
    try:
        pts_w, conf_w = detect_bright_field_drop_points(frame, w_form)
        glow_zone._last_good_points = []
        pts_c, conf_c = detect_bright_field_drop_points(frame, c_form)
        check("both ROI forms find points",
              len(pts_w) >= 1 and len(pts_c) >= 1,
              f"w:{len(pts_w)} c:{len(pts_c)}")
        check("both forms agree on the point set", pts_w == pts_c,
              f"w:{pts_w} c:{pts_c}")
        check("conf_w in [0,1]", 0.0 <= conf_w <= 1.0, f"conf_w={conf_w}")
        check("conf_c in [0,1]", 0.0 <= conf_c <= 1.0, f"conf_c={conf_c}")
        check("conf reflects found border (>0.15)", conf_w > 0.15, f"conf={conf_w}")
        # nudged points must sit on green (outside the white band)
        on_green = all(greenness(frame, px, py) > 0 for px, py in pts_w)
        check("all returned points are on grass-green pixels", on_green)
    finally:
        glow_zone._last_good_points = []


def test_fallback_cache():
    print("[6] line vanishes -> cached points, conf 0.15")
    frame1 = green_frame(1200, 900)
    draw_white_line(frame1, (610, 640), (890, 460))
    frame2 = green_frame(1200, 900)        # same region, no line at all
    glow_zone._last_good_points = []
    try:
        pts1, conf1 = detect_bright_field_drop_points(frame1, (600, 450, 300, 200))
        check("first frame finds points (cache filled)", len(pts1) >= 1 and conf1 > 0.15)
        pts2, conf2 = detect_bright_field_drop_points(frame2, (600, 450, 300, 200))
        check("second (empty) frame returns cached points",
              pts2 == pts1, f"got {pts2}")
        check("fallback conf is 0.15", abs(conf2 - 0.15) < 1e-9, f"conf={conf2}")
    finally:
        glow_zone._last_good_points = []


def test_hide_obstacles():
    print("[8] hide obstacles: broad blobs hidden, thin glow line survives")
    roi = np.zeros((400, 400, 3), np.uint8)
    mask = np.zeros((400, 400), np.uint8)
    cv2.line(mask, (30, 30), (370, 370), 255, 3)            # thin glow line
    cv2.rectangle(mask, (150, 150), (260, 260), 255, -1)    # broad obstacle blob
    clean = _hide_obstacles(mask, roi)
    line_px = int((clean[30:40, 30:40] > 0).sum())          # near the line
    blob_px = int((clean[195:215, 195:215] > 0).sum())      # blob interior
    check("thin glow line survives hiding", line_px > 0, f"line_px={line_px}")
    check("broad obstacle blob is hidden", blob_px == 0, f"blob_px={blob_px}")
    # vegetation exclusion: green pixels are stripped even when bright
    roi_g = np.zeros((400, 400, 3), np.uint8)
    roi_g[:] = (40, 200, 40)                                # green field
    m2 = np.zeros((400, 400), np.uint8)
    cv2.rectangle(m2, (100, 100), (300, 300), 255, -1)
    clean2 = _hide_obstacles(m2, roi_g)
    check("vegetation-coloured mask is excluded", int((clean2 > 0).sum()) == 0,
          f"left={int((clean2 > 0).sum())}")


def test_point_segment_dist():
    print("[9] point_segment_dist sanity")
    check("on-segment point -> 0", abs(point_segment_dist(50, 50, (0, 0, 100, 100))) < 1e-6)
    d = point_segment_dist(100, 0, (0, 0, 100, 100))
    check("off-line distance correct", abs(d - 70.71) < 0.1, f"{d:.2f}")
    d = point_segment_dist(150, 150, (0, 0, 100, 100))
    check("beyond segment end clamps to endpoint", abs(d - math.hypot(50, 50)) < 0.1)


def test_ring_segments_diagnostic():
    print("[10] detect_border_ring_segments returns raw segments")
    frame = green_frame(900, 1600)
    draw_white_line(frame, (300, 600), (1100, 300))
    segs, conf = detect_border_ring_segments(frame, (200, 150, 1400, 750))
    check("segments found", len(segs) >= 1, f"got {len(segs)}")
    check("conf in [0,1]", 0.0 <= conf <= 1.0)
    # the segments must lie close to the drawn line
    near = [s for s in segs
            if min((point_segment_dist((s[0]+s[2])/2, (s[1]+s[3])/2, (300, 600, 1100, 300)),)) < 40
            or point_segment_dist(s[0], s[1], (300, 600, 1100, 300)) < 60]
    check("at least one segment tracks the drawn line", len(near) >= 1, f"{len(segs)} segs")


def test_red_gate_and_veto():
    print("[7] red fill = gate/veto only: fog-like frames rejected, deep-red points vetoed")
    red_frame = np.full((600, 600, 3), (60, 60, 220), np.uint8)   # BGR strong red
    green = green_frame(600, 600)
    check("red frame -> ~full fill fraction",
          red_fill_fraction(red_frame, (100, 100, 500, 500)) > 0.5)
    check("green frame -> ~0 fill fraction",
          red_fill_fraction(green, (100, 100, 500, 500)) < 0.01)
    check("point deep in red is vetoed", _in_thick_red(red_frame, (300, 300)) is True)
    check("point on grass is not vetoed", _in_thick_red(green, (300, 300)) is False)

    # PARTIAL field: white line over green + a red blob covering the line's
    # top-right half — surviving points must all be off the thick red.
    mixed = green_frame(600, 600)
    draw_white_line(mixed, (40, 560), (560, 40))
    cv2.rectangle(mixed, (300, 0), (599, 299), (60, 60, 220), -1)   # top-right red
    glow_zone._last_good_points = []
    try:
        pts, conf = detect_bright_field_drop_points(mixed, (50, 50, 500, 500))
        check("partial-field detection returns points without raising",
              isinstance(pts, list), f"got {type(pts).__name__}")
        check("points survived on the green half", len(pts) >= 1, f"got {pts}")
        deep_red = [p for p in pts if _in_thick_red(mixed, p)]
        check("no returned point sits deep inside the red fill", not deep_red,
              f"offenders: {deep_red}")
    finally:
        glow_zone._last_good_points = []

    # GATE calibration on the measured real frames: fog/home views top out
    # ~3.7% largest-blob red, a real refused-drop fill covers ~25%+ -> 10%.
    real = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "_calib", "zone_fail_1029_013042_pre.png")
    if os.path.exists(real):
        img = cv2.imread(real)
        roi = (int(0.147 * 1600), int(0.233 * 900), int(0.968 * 1600), int(0.802 * 900))
        frac = red_fill_fraction(img, roi)
        check("fog zone_fail frame is BELOW the gate (rejected)", frac < glow_zone.RED_FILL_MIN,
              f"frac={frac:.4f} gate={glow_zone.RED_FILL_MIN}")
    else:
        print("  (skip real-frame check — _calib/zone_fail_1029_013042_pre.png not present)")
    # ...while a synthetic battle fill clears it comfortably.
    battle = green_frame(900, 1600)
    cv2.fillPoly(battle, [np.array([(800, 250), (1250, 450), (800, 650), (350, 450)], np.int32)],
                 (60, 60, 200))
    check("simulated battle fill is ABOVE the gate (accepted)",
          red_fill_fraction(battle, (int(0.147 * 1600), int(0.233 * 900),
                                     int(0.968 * 1600), int(0.802 * 900))) >= glow_zone.RED_FILL_MIN)


if __name__ == "__main__":
    test_pipeline_a_line()
    test_pipeline_a_no_line()
    test_nudge_inside()
    test_dedup_cap()
    test_detect_roi_forms_and_conf()
    test_fallback_cache()
    test_hide_obstacles()
    test_point_segment_dist()
    test_ring_segments_diagnostic()
    test_red_gate_and_veto()
    print(f"\n=== {passed} passed, {failed} failed ===")
    sys.exit(1 if failed else 0)
