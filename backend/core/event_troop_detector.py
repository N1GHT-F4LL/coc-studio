"""Event troop detection module.

Detect available (non-deployed) troops in the troop bar using:
1. YOLO model (if available) — best accuracy
2. Template matching + color-fraction fallback
3. OCR for troop count on each slot

Exports:
  - detect_available_troops(screen, settings, region) -> list[dict]
  - get_troop_count_by_name(screen, settings, region) -> dict[name, count]
"""
import cv2
import logging
from core.perception import detect_troop_bar
from core.ocr import read_number_with_confidence

logger = logging.getLogger(__name__)

SLOT_ICON_SCALES = (0.50, 0.60, 0.70, 0.80, 0.90, 1.00, 1.10, 1.20)
DEFAULT_BAR_REGION = [0, 730, 1600, 910]
DEFAULT_SLOT_PITCH = 95


def _get_bar_region(settings: dict, region=None) -> list[int]:
    """Resolve troop bar region from args or settings."""
    if region and len(region) == 4:
        return [int(v) for v in region]
    deploy = ((settings or {}).get("attack") or {}).get("deploy") or {}
    return [int(v) for v in deploy.get("troop_bar_region", DEFAULT_BAR_REGION)]


def _get_slot_pitch(settings: dict) -> int:
    """Get slot pitch from settings."""
    perception = ((settings or {}).get("perception") or {}).get("troop_bar") or {}
    deploy = ((settings or {}).get("attack") or {}).get("deploy") or {}
    return int(perception.get("slot_pitch") or deploy.get("bar_slot_pitch") or DEFAULT_SLOT_PITCH)


def _get_detection_thresholds(settings: dict) -> tuple[float, float, float]:
    """Get color-fraction thresholds for detection."""
    dump_cfg = ((settings or {}).get("attack") or {}).get("deploy") or {}
    sat_min = float(dump_cfg.get("dump_sat_min", 55.0))
    val_min = float(dump_cfg.get("dump_val_min", 45.0))
    frac_thr = float(dump_cfg.get("dump_color_frac", 0.38))
    return sat_min, val_min, frac_thr


def _scan_slots_by_color(screen: cv2.Mat, bar_region: list[int], slot_pitch: int,
                          sat_min: float, val_min: float, frac_thr: float) -> list[dict]:
    """Scan troop bar slots by color-fraction (fallback when no YOLO/template).

    Returns list of available troop slots with position and fraction info.
    """
    if screen is None:
        return []

    h, w = screen.shape[:2]
    bx1, by1, bx2, by2 = bar_region
    bx1 = max(0, min(w - 1, bx1))
    bx2 = max(1, min(w, bx2))
    by1 = max(0, min(h - 1, by1))
    by2 = max(1, min(h, by2))

    if bx2 <= bx1 or by2 <= by1:
        return []

    hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
    n_slots = max(1, int((bx2 - bx1) / slot_pitch))
    bar_cy = (by1 + by2) // 2

    available = []
    for i in range(n_slots):
        tx1 = bx1 + i * slot_pitch
        tx2 = min(bx2, tx1 + slot_pitch)
        ty1, ty2 = by1, by2
        tw, th = tx2 - tx1, ty2 - ty1
        if tw < 6 or th < 6:
            continue

        # Sample lower-central body (skip top badge/health bar)
        sx1 = tx1 + int(tw * 0.20)
        sx2 = tx2 - int(tw * 0.20)
        sy1 = ty1 + int(th * 0.45)
        sy2 = ty2 - int(th * 0.05)
        if sx2 - sx1 < 4 or sy2 - sy1 < 4:
            sx1, sy1, sx2, sy2 = tx1, ty1, tx2, ty2

        body = hsv[sy1:sy2, sx1:sx2]
        if body.size == 0:
            continue

        coloured = (body[:, :, 1] >= sat_min) & (body[:, :, 2] >= val_min)
        frac = float(coloured.mean())

        if frac >= frac_thr:
            slot_x = (tx1 + tx2) // 2
            available.append({
                "slot_index": i,
                "x": slot_x,
                "y": bar_cy,
                "color_fraction": frac,
                "kind": "unknown_event",  # template-free
            })

    logger.info("[COLOR_SCAN] found %d available slots (frac_thr=%.2f, sat=%.0f, val=%.0f)",
                len(available), frac_thr, sat_min, val_min)
    return available


def _read_slot_count(screen: cv2.Mat, slot_x: int, bar_region: list[int],
                      slot_pitch: int) -> int | None:
    """OCR the troop count number on a slot (bottom-right area of icon).

    CoC displays remaining count as a small number at the bottom-right
    of each troop icon. Returns None if no number readable (single slot).
    """
    if screen is None:
        return None

    h, w = screen.shape[:2]
    bx1, by1, bx2, by2 = bar_region
    slot_idx = max(0, int((slot_x - bx1) / slot_pitch))
    tx1 = bx1 + slot_idx * slot_pitch
    tx2 = min(bx2, tx1 + slot_pitch)

    # Number region: bottom-right of the slot icon
    # Typically 20-30px wide, 12-15px tall, offset from bottom-right
    nw = min(32, tx2 - tx1 - 4)  # number width
    nh = min(16, by2 - by1 - 4)  # number height
    num_x1 = tx2 - nw - 2
    num_y1 = by2 - nh - 2
    num_x2 = tx2 - 2
    num_y2 = by2 - 2

    if num_x2 <= num_x1 or num_y2 <= num_y1:
        return None

    ocr_region = (num_x1, num_y1, num_x2, num_y2)
    count, conf = read_number_with_confidence(screen, ocr_region, min_value=0)
    if count is not None and conf > 0.3:
        logger.debug("[COUNT] slot @ x=%d count=%d (conf=%.2f)", slot_x, count, conf)
        return count

    # Fallback: check smaller region (for single-digit numbers)
    num_x1 = tx2 - 18
    num_y1 = by2 - 14
    ocr_region = (num_x1, num_y1, num_x2, num_y2)
    count, conf = read_number_with_confidence(screen, ocr_region, min_value=0)
    if count is not None and conf > 0.3:
        logger.debug("[COUNT] slot @ x=%d count=%d (conf=%.2f, small)", slot_x, count, conf)
        return count

    return None


def _verify_slot_occupied(screen: cv2.Mat, det_x: int, bar_region: list[int],
                           slot_pitch: int, sat_min: float, val_min: float, frac_thr: float) -> float:
    """Verify a detected troop slot is actually occupied by checking color-fraction.

    Returns the color fraction of the slot. If < frac_thr, the slot is empty/spent.
    """
    if screen is None:
        return 0.0

    h, w = screen.shape[:2]
    bx1, by1, bx2, by2 = bar_region

    # Find slot index from x position
    slot_idx = max(0, int((det_x - bx1) / slot_pitch))
    tx1 = bx1 + slot_idx * slot_pitch
    tx2 = min(bx2, tx1 + slot_pitch)
    ty1, ty2 = by1, by2
    tw, th = tx2 - tx1, ty2 - ty1
    if tw < 6 or th < 6:
        return 0.0

    hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)

    # Sample lower-central body (skip top badge/health bar)
    sx1 = tx1 + int(tw * 0.20)
    sx2 = tx2 - int(tw * 0.20)
    sy1 = ty1 + int(th * 0.45)
    sy2 = ty2 - int(th * 0.05)
    if sx2 - sx1 < 4 or sy2 - sy1 < 4:
        sx1, sy1, sx2, sy2 = tx1, ty1, tx2, ty2

    body = hsv[sy1:sy2, sx1:sx2]
    if body.size == 0:
        return 0.0

    coloured = (body[:, :, 1] >= sat_min) & (body[:, :, 2] >= val_min)
    return float(coloured.mean())


def detect_available_troops(screen: cv2.Mat, settings: dict, region=None, read_counts=True) -> list[dict]:
    """Detect all available troops in the troop bar.

    Pipeline:
      1. YOLO detection (if model available) → best accuracy
      2. Template matching → finds known troop icons
      3. Color-fraction verification → filters out empty/x0 slots
      4. OCR count → reads remaining troop count on each slot
      5. Color-fraction fallback → catches unknown event troops

    Args:
        read_counts: if True, OCR each occupied slot for remaining count.

    Returns:
        List of dicts with keys: slot_index, x, y, kind, name, score,
            color_fraction, count, source
        - count: remaining troop count from OCR (None if unreadable, 0 if x0)
        - For event troops without template: kind="unknown_event", name="event_N"

    Example:
        troops = detect_available_troops(screen, settings)
        for t in troops:
            print(f"Slot {t['slot_index']}: {t['name']} count={t.get('count', '?')} frac={t['color_fraction']:.2f}")
    """
    if screen is None:
        logger.warning("[EVENT_DETECT] no screen")
        return []

    bar_region = _get_bar_region(settings, region)
    sat_min, val_min, frac_thr = _get_detection_thresholds(settings)
    slot_pitch = _get_slot_pitch(settings)

    result = detect_troop_bar(screen, settings, mode="auto", region=bar_region)

    available = []
    if result.get("ok") and result.get("detections"):
        # Use perception results (YOLO or template) but VERIFY each slot is occupied
        for i, det in enumerate(result["detections"]):
            role = det.get("role", "deployable")
            if role not in ("deployable", "event"):
                continue

            # Verify slot is actually occupied (not empty/x0)
            frac = _verify_slot_occupied(screen, det["x"], bar_region, slot_pitch, sat_min, val_min, frac_thr)
            if frac < frac_thr:
                logger.debug("[EVENT_DETECT] slot %s @ x=%d frac=%.2f < thr=%.2f — empty, skipping",
                            det.get("name", "?"), det["x"], frac, frac_thr)
                continue

            entry = {
                "slot_index": det.get("slot", i),
                "x": det["x"],
                "y": det["y"],
                "kind": det.get("kind", "unknown"),
                "name": det.get("name", "unknown"),
                "score": det.get("score", 0.0),
                "color_fraction": frac,
                "count": None,  # will be filled by OCR
                "source": result.get("source", "template"),
                "box": det.get("box"),
            }

            # OCR count if enabled
            if read_counts:
                count = _read_slot_count(screen, det["x"], bar_region, slot_pitch)
                if count is not None and count > 0:
                    entry["count"] = count
                else:
                    # OCR failed — use color-fraction as heuristic
                    # High frac = likely full stack, medium = partial
                    if frac > 0.5:
                        entry["count"] = 8  # default taps
                    else:
                        entry["count"] = 4  # partial stack

            available.append(entry)
        logger.info("[EVENT_DETECT] found %d available troops via %s (verified)", len(available), result["source"])
    else:
        # Fallback: pure color-fraction scan (for event troops with no template/YOLO)
        available = _scan_slots_by_color(screen, bar_region, slot_pitch, sat_min, val_min, frac_thr)
        for i, slot in enumerate(available):
            slot["name"] = f"event_{i}"
            slot["source"] = "color"
            slot["count"] = None
            # For color-only fallback, can't read count via OCR
            if slot["color_fraction"] > 0.5:
                slot["count"] = 8
            else:
                slot["count"] = 4
        logger.info("[EVENT_DETECT] found %d available troops via color-fraction", len(available))

    return available


def get_troop_counts(screen: cv2.Mat, settings: dict, region=None) -> dict[str, int]:
    """Count available troops by name.

    Returns:
        Dict mapping troop name -> count
        Example: {"super_minion": 7, "totem": 2, "event_0": 5}
    """
    troops = detect_available_troops(screen, settings, region)
    counts: dict[str, int] = {}
    for t in troops:
        name = t.get("name", "unknown")
        counts[name] = counts.get(name, 0) + 1
    return counts


def get_available_drop_positions(screen: cv2.Mat, settings: dict,
                                  planned_drops: list[tuple[int, int]] = None,
                                  region=None) -> list[tuple[int, int]]:
    """Get drop positions for available troops.

    If planned_drops provided, cycle through them.
    Otherwise, use default battlefield line.

    Returns list of (x, y) drop coordinates.
    """
    if planned_drops and len(planned_drops) > 0:
        return planned_drops

    deploy_cfg = ((settings or {}).get("attack") or {}).get("deploy") or {}
    def_y = int(deploy_cfg.get("battlefield_y", 750))
    x1 = int(deploy_cfg.get("battlefield_x_start", 300))
    x2 = int(deploy_cfg.get("battlefield_x_end", 1300))

    # Default: 5 evenly spaced points along the front line
    return [(x1 + i * (x2 - x1) // 4, def_y) for i in range(5)]


def detect_protected_slots(screen: cv2.Mat, settings: dict, region=None) -> list[int]:
    """Get x-coordinates of protected slots (heroes/sieges that shouldn't be dumped).

    Returns:
        List of x-coordinates of protected slots.
    """
    bar_region = _get_bar_region(settings, region)
    result = detect_troop_bar(screen, settings, mode="auto", region=bar_region)
    return protected_centers(result) if result.get("ok") else []
