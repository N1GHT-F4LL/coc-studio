"""Event troop detection module.

Detect available (non-deployed) troops in the troop bar using:
1. YOLO model (if available) — best accuracy
2. Template matching + color-fraction fallback

Exports:
  - detect_available_troops(screen, settings, region) -> list[dict]
  - get_troop_count_by_name(screen, settings, region) -> dict[name, count]
"""
import cv2
import logging
from core.perception import detect_troop_bar, protected_centers

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


def detect_available_troops(screen: cv2.Mat, settings: dict, region=None) -> list[dict]:
    """Detect all available troops in the troop bar.

    Uses perception API (YOLO if available, else template matching).
    Falls back to color-fraction scan for unknown event troops.

    Returns:
        List of dicts with keys: slot_index, x, y, kind, name, score, source
        - source: "yolo" | "template" | "color"
        - For event troops without template: kind="unknown_event", name="event_N"

    Example:
        troops = detect_available_troops(screen, settings)
        for t in troops:
            print(f"Slot {t['slot_index']}: {t['name']} ({t['kind']}) @ ({t['x']},{t['y']})")
    """
    if screen is None:
        logger.warning("[EVENT_DETECT] no screen")
        return []

    bar_region = _get_bar_region(settings, region)
    result = detect_troop_bar(screen, settings, mode="auto", region=bar_region)

    available = []
    if result.get("ok") and result.get("detections"):
        # Use perception results (YOLO or template)
        for i, det in enumerate(result["detections"]):
            role = det.get("role", "deployable")
            if role in ("deployable", "event"):
                available.append({
                    "slot_index": det.get("slot", i),
                    "x": det["x"],
                    "y": det["y"],
                    "kind": det.get("kind", "unknown"),
                    "name": det.get("name", "unknown"),
                    "score": det.get("score", 0.0),
                    "source": result.get("source", "template"),
                    "box": det.get("box"),
                })
        logger.info("[EVENT_DETECT] found %d available troops via %s", len(available), result["source"])
    else:
        # Fallback: pure color-fraction scan (for event troops with no template/YOLO)
        sat_min, val_min, frac_thr = _get_detection_thresholds(settings)
        slot_pitch = _get_slot_pitch(settings)
        available = _scan_slots_by_color(screen, bar_region, slot_pitch, sat_min, val_min, frac_thr)
        for i, slot in enumerate(available):
            slot["name"] = f"event_{i}"
            slot["source"] = "color"
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
