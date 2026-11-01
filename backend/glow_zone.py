"""Glowing-border red-zone detection (Simplicity bot mechanism, 1:1 rebuild).

Reference: ``RED_ZONE_ANALYSIS.md`` (reverse-engineered from the Simplicity
bot's main.py code objects). Replaces the old diff-the-red-fill detector:
classifying RED pixels is fragile (buildings, shadows and dirt share the red
tone), while the red zone is always BOUNDED BY A GLOWING WHITE BORDER — the
line the game draws between the red fill and the green grass — which is stable
across every base. Pipeline:

  1. find bright-white straight segments (the glow border) inside the ROI,
  2. spread drop points along the longest segments at a fixed spacing,
  3. nudge each point toward the most "grass-green" neighbouring pixel so the
     tap lands just INSIDE the deployable grass, off the border itself.

Why the angular filter (12-85 deg / 95-168 deg): the battle HUD is made of
horizontal and vertical bars; only DIAGONAL segments can belong to the isometric
red-zone diamond, so axis-aligned UI lines are discarded outright.
Why the nudge scores ``g - (r + b) / 2``: grass is the only thing in the ROI
whose green channel dominates red+blue; the glow line and the red fill both
score <= 0. Moving a border point 12px toward the highest greenness puts it on
valid ground without needing any red classification at all.
"""
import math

import cv2
import numpy as np

# Drop points spaced ~180px apart along the glow border (Simplicity's tuned
# value: dense enough to cover a village edge, sparse enough to stay distinct).
DROP_SPACING = 180
BRIGHT_EDGE_MARGIN = 10     # ROI padding so a border hugging the ROI edge survives
_TOPHAT_K = 21              # top-hat kernel: keeps THIN bright structures (the glow
                            # line) and kills broad bright blobs (buildings, effects)
_MIN_SEP = 18               # dedup: a new point must be >18px apart on x OR y
_MAX_POINTS = 12

# Default glow ROI as FRACTIONS of the frame — Simplicity's 1600x900 box
# (235,210)-(1549,722) (the central playfield, HUD excluded). Fractions (not
# pixels) so other emulator resolutions map onto the same field region.
GLOW_ROI_FRAC = (235 / 1600.0, 210 / 900.0, 1549 / 1600.0, 722 / 900.0)

# Fallback cache: the last successfully detected point set. A frame where the
# border is momentarily invisible (spell effect, mid-animation) returns this
# instead of garbage — conf 0.15 marks it as unverified.
_last_good_points = []

# Red fill acts ONLY as a gate/veto (never as the border locator): the glow
# detector must not fire when there is no red zone up at all — white fog
# (battle-enter transition), spell effects and bright decorations would
# otherwise read as "border" (their diagonals are just as bright as the glow).
# Measured on real frames: fog/home frames top out at ~3.7% (scattered red
# decorations), a real refused-drop fill covers ~25%+ of the ROI — the gate
# sits at 10%.
RED_FILL_MIN = 0.10   # min ROI fraction of the LARGEST red blob to accept

_DIRS = ((1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1))


def _strong_red(r, g, b):
    return (r > 120) & (r - g > 50) & (r - b > 50)


def red_fill_fraction(img_bgr, roi):
    """Fraction of the ROI covered by the LARGEST connected strong-red blob —
    the 'is the red-zone fill actually up?' gate. Connectedness (not the raw
    red-pixel count) is what separates the one big translucent fill from
    scattered red decorations/badges, which top out an order of magnitude
    lower on fog/home frames."""
    try:
        x1, y1, x2, y2 = [int(v) for v in roi]
        patch = img_bgr[y1:y2, x1:x2].astype(np.int16)
        r, g, b = patch[:, :, 2], patch[:, :, 1], patch[:, :, 0]
        mask = _strong_red(r, g, b).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            return 0.0
        area = max(1, (x2 - x1) * (y2 - y1))
        return max(cv2.contourArea(c) for c in cnts) / area
    except Exception:
        return 0.0


def _in_thick_red(img_bgr, pt):
    """True when most of the 8px neighbourhood of ``pt`` is strongly red — the
    point sits INSIDE the fill (nudge failed to find grass) and must be vetoed."""
    try:
        x, y = int(pt[0]), int(pt[1])
        h, w = img_bgr.shape[:2]
        red = 0
        for dx, dy in _DIRS:
            xx = _clip(x + dx * 8, 0, w - 1)
            yy = _clip(y + dy * 8, 0, h - 1)
            b, g, r = img_bgr[yy, xx]
            if _strong_red(int(r), int(g), int(b)):
                red += 1
        return red >= 5   # 5+/8 neighbours red = deep inside the fill
    except Exception:
        return False


def _clip(v, lo, hi):
    return max(lo, min(hi, int(v)))


def frac_roi(frame_bgr):
    """Absolute (x1, y1, x2, y2) of the default glow ROI for this frame size."""
    h, w = frame_bgr.shape[:2]
    return (int(GLOW_ROI_FRAC[0] * w), int(GLOW_ROI_FRAC[1] * h),
            int(GLOW_ROI_FRAC[2] * w), int(GLOW_ROI_FRAC[3] * h))


def _sorted_box(tl, br, shape):
    """Sort two corners into (x1, y1, x2, y2) and clip to the frame bounds."""
    h, w = shape[:2]
    x1, y1 = int(tl[0]), int(tl[1])
    x2, y2 = int(br[0]), int(br[1])
    return (max(0, min(x1, x2)), max(0, min(y1, y2)),
            min(w, max(x1, x2)), min(h, max(y1, y2)))


def _points_along(x1, y1, x2, y2, spacing):
    """Spread points along a segment at ``spacing``: n = L//spacing + 1 points,
    each at the CENTRE of its subdivision — never two points crowded at the
    segment ends, so the border ring stays evenly spaced."""
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length < spacing:
        return [(int(round((x1 + x2) / 2)), int(round((y1 + y2) / 2)))]
    n = int(length // spacing) + 1
    return [(int(round(x1 + (i + 0.5) / n * dx)),
             int(round(y1 + (i + 0.5) / n * dy))) for i in range(n)]


def _dedup_cap(pts, min_sep=_MIN_SEP, cap=_MAX_POINTS):
    """Keep points that are >min_sep apart on x OR y from every kept point
    (the glow band yields 2 Hough edges per border side; this collapses them),
    then cap the ring size."""
    out = []
    for px, py in pts:
        if all(abs(px - qx) > min_sep or abs(py - qy) > min_sep for qx, qy in out):
            out.append((px, py))
    return out[:cap]


def _nudge_inside(pt, img_bgr, step=12):
    """Move a border point INTO deployable ground: sample 8px out in 8
    directions, score each by grass-greenness (``g - (r + b) / 2`` — only
    grass has a dominant green channel here; the glow line and the red fill
    score <= 0) and step ``step``px toward the winner. Never raises."""
    try:
        x, y = int(pt[0]), int(pt[1])
        h, w = img_bgr.shape[:2]
        best_score, best_dir = 0, None
        for dx, dy in _DIRS:
            xx = _clip(x + dx * 8, 0, w - 1)
            yy = _clip(y + dy * 8, 0, h - 1)
            b, g, r = img_bgr[yy, xx]
            score = int(g) - (int(r) + int(b)) // 2
            if score > best_score:
                best_score, best_dir = score, (dx, dy)
        if best_dir is None:
            return (x, y)   # no green anywhere nearby — leave the point as-is
        dx, dy = best_dir
        return (_clip(x + dx * step, 0, w - 1), _clip(y + dy * step, 0, h - 1))
    except Exception:
        return (int(pt[0]), int(pt[1]))


def get_glow_drop_points(img_bgr, tl=None, br=None, spacing=DROP_SPACING):
    """Pipeline A: bright-white mask -> Hough -> spread points along the 6
    longest segments of the glow border. Returns up to 12 (x, y) points in
    absolute frame coordinates; a ROI with no glow collapses to its centre."""
    try:
        h, w = img_bgr.shape[:2]
        if tl is None or br is None:
            rx1, ry1, rx2, ry2 = frac_roi(img_bgr)
            tl, br = (rx1, ry1), (rx2, ry2)
        x1, y1, x2, y2 = _sorted_box(tl, br, img_bgr.shape)
        if x2 - x1 < 4 or y2 - y1 < 4:
            return [((x1 + x2) // 2, (y1 + y2) // 2)]

        roi = img_bgr[y1:y2, x1:x2]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        _hc, sc, vc = cv2.split(hsv)
        # Bright WHITE only (low saturation + very high value): the glow border
        # is drawn near-pure-white, while red fill / grass / buildings all have
        # either saturated colour or darker value.
        mask = ((sc < 80) & (vc > 220)).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8),
                                iterations=2)   # the glow is drawn DASHED — close the gaps
        mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)
        edges = cv2.Canny(mask, 50, 150)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 60, minLineLength=12)
        if lines is None:
            return [((x1 + x2) // 2, (y1 + y2) // 2)]

        # OpenCV <5 returns (N,1,4), OpenCV 5 returns (N,4) — flatten both.
        segs = sorted((tuple(map(int, row)) for row in np.asarray(lines).reshape(-1, 4)),
                      key=lambda L: math.hypot(L[2] - L[0], L[3] - L[1]),
                      reverse=True)[:6]           # the 6 longest = the border's edges
        pts = []
        for xa, ya, xb, yb in segs:
            pts += _points_along(x1 + xa, y1 + ya, x1 + xb, y1 + yb, spacing)
        return _dedup_cap(pts)
    except Exception:
        h, w = img_bgr.shape[:2]
        return [(w // 2, h // 2)]


def _norm_roi_any(shape, roi_spec, margin=BRIGHT_EDGE_MARGIN):
    """Normalise a ROI given as (x1,y1,x2,y2) OR (x,y,w,h) into a clipped,
    margin-expanded box. Disambiguation: if the 3rd/4th values are small
    (<= W//3, H//3) they cannot be bottom-right corners of this frame — they
    are a width/height pair (this is exactly how Simplicity reads its
    ``(1549,722,235,210)`` bottom-right ROI). Returns None for an empty box."""
    h, w = shape[:2]
    a, b, c, d = [int(v) for v in roi_spec]
    if c <= w // 3 and d <= h // 3:
        x2, y2 = a + c, b + d          # (x, y, w, h)
        x1, y1 = a, b
    else:                              # (x1, y1, x2, y2)
        x1, y1, x2, y2 = a, b, c, d
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    x1, y1 = max(0, x1 - margin), max(0, y1 - margin)
    x2, y2 = min(w, x2 + margin), min(h, y2 + margin)
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None
    return (x1, y1, x2, y2)


def _white_tophat(gray, k=_TOPHAT_K):
    """Bright SMALL structures only: top-hat = image minus its morphological
    opening. Broad bright areas (large buildings, bright effects) survive the
    opening and cancel out; the thin glow line does not and stays."""
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    return cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)


def _auto_binary(hat):
    """Otsu (global) OR adaptive-mean (local) binarisation of the top-hat, then
    close 5x5 (reconnect dashed glow) and open 3x3 (drop speckle). The union
    keeps the border whether the local contrast is even or spotty."""
    _ret, t1 = cv2.threshold(hat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    t2 = cv2.adaptiveThreshold(hat, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                               cv2.THRESH_BINARY, 31, -3)
    m = cv2.bitwise_or(t1, t2)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return m


def _angle_ok(x1, y1, x2, y2):
    """Only DIAGONAL segments can belong to the isometric red-zone diamond;
    horizontal/vertical segments are battle-HUD bars (buttons, banners, the
    troop bar rim) and are rejected."""
    ang = abs(math.degrees(math.atan2(y2 - y1, x2 - x1)))
    return (12 <= ang <= 85) or (95 <= ang <= 168)


def _find_lines_hough(mask, xa, ya, fw, fh):
    med = float(np.median(mask))
    low = int(max(0, 0.66 * med))
    high = int(min(255, 1.33 * med))
    edges = cv2.Canny(mask, low, high)
    min_len = max(80, int(0.12 * math.hypot(fw, fh)))
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 60,
                            minLineLength=min_len, maxLineGap=16)
    out = []
    if lines is None:
        return out
    for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4):   # OpenCV 4: (N,1,4) / 5: (N,4)
        if _angle_ok(int(x1), int(y1), int(x2), int(y2)):
            out.append((xa + int(x1), ya + int(y1), xa + int(x2), ya + int(y2)))
    return out


def _find_lines_lsd(hat, xa, ya):
    """Line Segment Detector on the top-hat — catches faint border parts the
    Hough pass misses. Some OpenCV builds ship without LSD; treat that as
    'no extra lines', never an error."""
    out = []
    try:
        lsd = cv2.createLineSegmentDetector(0)
        lines = lsd.detect(hat)[0]
        if lines is None:
            return out
        for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4):
            if _angle_ok(x1, y1, x2, y2):
                out.append((xa + int(x1), ya + int(y1), xa + int(x2), ya + int(y2)))
    except Exception:
        pass
    return out


def _hide_obstacles(mask, roi_bgr):
    """RED_ZONE_ANALYSIS.md §7 names bright obstacles as the detector's weak
    spot: trees, bushes and white decorations inside the ROI carry the same
    bright pixels as the glow border. "Hiding" them keeps only THIN white
    structures: morphological opening strips broad bright bodies (obstacle
    blobs, building roofs) and the subtraction keeps what only exists as thin
    strokes — the 2-3px glow line. The glow ring survives; obstacle bodies do
    not. (Per-component area filtering is deliberately NOT used: the border
    ring itself is one long thin component and a naive area cap kills it.)"""
    try:
        # vegetation exclusion: green foliage pixels never belong to the glow
        hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
        veg = cv2.inRange(hsv, (35, 60, 40), (85, 255, 255))
        mask = cv2.bitwise_and(mask, cv2.bitwise_not(veg))
        # broad-blob removal: opening(15) keeps blobs, drops thin strokes
        broad = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                                 cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))
        return cv2.bitwise_and(mask, cv2.bitwise_not(broad))
    except Exception:
        return mask


def _pipeline_segments(img_bgr, roi_spec, hide_obstacles=False, debug=None):
    """Pipeline B core (RED_ZONE_ANALYSIS.md §3): ROI normalise -> white top-hat
    -> auto binary -> Hough(+LSD) with the diagonal-only angular filter -> the
    6 longest segments. Returns (segments, conf, box); segments is [] when no
    border measures (conf 0.15 marks the no-line fallback)."""
    box = _norm_roi_any(img_bgr.shape, roi_spec, BRIGHT_EDGE_MARGIN)
    if not box:
        return [], 0.0, None
    x1, y1, x2, y2 = box
    h, w = img_bgr.shape[:2]
    roi = img_bgr[y1:y2, x1:x2]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    hat = _white_tophat(gray)
    mask = _auto_binary(hat)
    if hide_obstacles:
        mask = _hide_obstacles(mask, roi)

    lines = _find_lines_hough(mask, x1, y1, w, h)
    if len(lines) < 2:
        lines = sorted(lines + _find_lines_lsd(hat, x1, y1),
                       key=lambda L: math.hypot(L[2] - L[0], L[3] - L[1]),
                       reverse=True)

    if debug:
        try:
            dbg = img_bgr.copy()
            cv2.rectangle(dbg, (x1, y1), (x2, y2), (255, 0, 0), 2)   # blue ROI
            for xa, ya, xb, yb in lines[:8]:
                cv2.line(dbg, (xa, ya), (xb, yb), (0, 0, 255), 2)    # red segments
            cv2.imwrite(f"{debug}_dbg.png", dbg)
            cv2.imwrite(f"{debug}_hat.png", hat)
            cv2.imwrite(f"{debug}_mask.png", mask)
        except Exception:
            pass

    if not lines:
        return [], 0.15, box
    segs = sorted(lines, key=lambda L: math.hypot(L[2] - L[0], L[3] - L[1]),
                  reverse=True)[:6]
    diag = math.hypot(x2 - x1, y2 - y1) or 1.0
    total = sum(math.hypot(L[2] - L[0], L[3] - L[1]) for L in segs)
    conf = min(1.0, max(0.0, total / diag))
    return segs, conf, box


def detect_bright_field_drop_points(img_bgr, roi_spec, debug=None, hide_obstacles=False):
    """Pipeline B: top-hat -> auto-binary -> Hough(+LSD) -> spread -> nudge.

    Returns (points, conf) where conf = total detected border length over the
    ROI diagonal (a rough 'did we see enough border' proxy, clamped to [0,1]).
    Never raises: any CV failure yields the previous good points (cached) with
    conf 0.15, or ([ROI centre], 0.15) when there is no cache. ``debug`` is a
    path PREFIX — when set, <prefix>_dbg/_hat/_mask.png are written for tuning.
    ``hide_obstacles`` masks broad bright blobs (trees/decorations) out of the
    white mask before line finding — the §7 noise source."""
    global _last_good_points
    try:
        segs, conf, box = _pipeline_segments(img_bgr, roi_spec, hide_obstacles, debug)
        if box is None:
            return (list(_last_good_points), 0.0) if _last_good_points else ([], 0.0)
        x1, y1, x2, y2 = box

        if not segs:
            return (list(_last_good_points), 0.15) if _last_good_points \
                else ([((x1 + x2) // 2, (y1 + y2) // 2)], 0.15)

        pts = []
        for xa, ya, xb, yb in segs:
            pts += _points_along(xa, ya, xb, yb, DROP_SPACING)
        uniq = []
        for px, py in pts:   # dedup on the raw point, store the NUDGED one
            if all(abs(px - ux) > _MIN_SEP or abs(py - uy) > _MIN_SEP for ux, uy in uniq):
                uniq.append(_nudge_inside((px, py), img_bgr, step=12))
        # Veto points the nudge could not rescue (still deep inside the red
        # fill) — they would bounce exactly like unanchored static points.
        uniq = [p for p in uniq if not _in_thick_red(img_bgr, p)]
        _last_good_points = list(uniq)
        return uniq[:_MAX_POINTS], conf
    except Exception:
        return (list(_last_good_points), 0.0) if _last_good_points else ([], 0.0)


def point_segment_dist(px, py, seg):
    """Distance from a point to a segment (x1,y1,x2,y2) — used by the deploy
    diagnostic to score static pattern points against the measured ring."""
    x1, y1, x2, y2 = seg
    dx, dy = x2 - x1, y2 - y1
    ln = math.hypot(dx, dy)
    if ln < 1e-6:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (ln * ln)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def detect_border_ring_segments(img_bgr, roi_spec, hide_obstacles=True, debug=None):
    """Diagnostic variant of pipeline B: returns the raw glow-border line
    segments (up to 6, sorted longest-first) WITHOUT the point-spreading step,
    so callers can score their own static points against the measured ring.
    Used by battle_screen's one-shot deploy diagnostic (diagnostics only — it
    never steers the deploy)."""
    try:
        segs, conf, _box = _pipeline_segments(img_bgr, roi_spec, hide_obstacles, debug)
        return segs, conf
    except Exception:
        return [], 0.0


def get_glow_drop_points_poly(img_bgr, poly_abs, spacing=DROP_SPACING):
    """Pipeline C: like pipeline A but restricted to a polygon (absolute
    vertices) — only glow INSIDE the polygon is detected (the poly AND-ed with
    the white mask before Canny/Hough). Use it to hunt one specific field."""
    try:
        h, w = img_bgr.shape[:2]
        poly = np.array(poly_abs, np.int32)
        rx1, ry1 = poly.min(axis=0)
        rx2, ry2 = poly.max(axis=0)
        rx1, ry1 = max(0, int(rx1)), max(0, int(ry1))
        rx2, ry2 = min(w, int(rx2)), min(h, int(ry2))
        if rx2 - rx1 < 4 or ry2 - ry1 < 4:
            return [((rx1 + rx2) // 2, (ry1 + ry2) // 2)]
        roi = img_bgr[ry1:ry2, rx1:rx2]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        _hc, sc, vc = cv2.split(hsv)
        mask = ((sc < 80) & (vc > 220)).astype(np.uint8) * 255
        poly_mask = np.zeros(roi.shape[:2], np.uint8)
        cv2.fillPoly(poly_mask, [poly - [rx1, ry1]], 255)
        mask = cv2.bitwise_and(mask, poly_mask)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8),
                                iterations=2)
        mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)
        edges = cv2.Canny(mask, 50, 150)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 60, minLineLength=12)
        if lines is None:
            return [((rx1 + rx2) // 2, (ry1 + ry2) // 2)]
        segs = sorted((tuple(map(int, row)) for row in np.asarray(lines).reshape(-1, 4)),
                      key=lambda L: math.hypot(L[2] - L[0], L[3] - L[1]),
                      reverse=True)[:6]
        pts = []
        for xa, ya, xb, yb in segs:
            pts += _points_along(rx1 + xa, ry1 + ya, rx1 + xb, ry1 + yb, spacing)
        return _dedup_cap(pts)
    except Exception:
        h, w = img_bgr.shape[:2]
        return [(w // 2, h // 2)]


def save_glow_debug(img_bgr, path):
    """Tuning dump: the found segments (red), the final nudged drop points
    (red dots r=10) and the ROI box (blue) onto a copy of the frame, written
    to ``path``. Re-runs the detection so it always reflects current thresholds."""
    try:
        roi = frac_roi(img_bgr)
        dbg = img_bgr.copy()
        x1, y1, x2, y2 = roi
        cv2.rectangle(dbg, (x1, y1), (x2, y2), (255, 0, 0), 2)
        gray = cv2.cvtColor(img_bgr[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
        hat = _white_tophat(gray)
        mask = _auto_binary(hat)
        h, w = img_bgr.shape[:2]
        lines = _find_lines_hough(mask, x1, y1, w, h)
        if len(lines) < 2:
            lines += _find_lines_lsd(hat, x1, y1)
        for xa, ya, xb, yb in lines[:8]:
            cv2.line(dbg, (xa, ya), (xb, yb), (0, 0, 255), 2)
        for px, py in get_glow_drop_points(img_bgr):
            cv2.circle(dbg, (int(px), int(py)), 10, (0, 0, 255), -1)
        cv2.imwrite(path, dbg)
        return True
    except Exception:
        return False
