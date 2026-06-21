"""Unified perception helpers.

This module is the stable boundary between bot logic and recognition backends.
Callers ask for normalized facts (screen state, troop-bar slots later), while
the backend can be template matching, YOLO, or a hybrid fallback.
"""
import logging
import os

from core.troop_recognition import recognize_bar as recognize_template_bar
from core.troop_yolo import detect_bar as detect_yolo_bar

logger = logging.getLogger(__name__)

PROTECTED_PREFIXES = ("units/heroes/", "units/siege/")
UNAVAILABLE_TOKENS = ("empty", "disabled", "spent", "used", "unavailable", "grey", "gray")
EVENT_TOKENS = ("event", "unknown", "temporary", "bonus")

def cfg(settings: dict | None) -> dict:
    return ((settings or {}).get("perception") or {})

def troop_bar_cfg(settings: dict | None) -> dict:
    return cfg(settings).get("troop_bar") or {}

def _deploy_cfg(settings: dict | None) -> dict:
    return (((settings or {}).get("attack") or {}).get("deploy") or {})

def _bar_region(settings: dict | None, region=None):
    if region and len(region) == 4:
        return [int(v) for v in region]
    return [int(v) for v in _deploy_cfg(settings).get("troop_bar_region", [0, 730, 1600, 910])]

def _kind(key: str) -> str:
    low = key.lower()
    if "/heroes/" in low or low.startswith("hero") or "king" in low or "queen" in low or "warden" in low or "champion" in low:
        return "hero"
    if (
        "/siege/" in low or low.startswith("siege") or "launcher" in low or
        "blimp" in low or "slammer" in low or "wrecker" in low or
        "barracks" in low or "flinger" in low or "drill" in low or "battle_ram" in low
    ):
        return "siege"
    if "/spells/" in low or low.startswith("spell"):
        return "spell"
    return "troop"

def _status(key: str) -> str:
    low = key.lower()
    if any(tok in low for tok in UNAVAILABLE_TOKENS):
        return "unavailable"
    return "available"

def _role(key: str, kind: str, status: str) -> str:
    low = key.lower()
    if status != "available":
        return "ignore"
    if kind in ("hero", "siege"):
        return "protected"
    if any(tok in low for tok in EVENT_TOKENS):
        return "event"
    return "deployable"

def _slot_index(x: int, settings: dict | None, region) -> int | None:
    pitch = int(troop_bar_cfg(settings).get("slot_pitch") or _deploy_cfg(settings).get("bar_slot_pitch") or 95)
    if pitch <= 0 or not region:
        return None
    return max(0, int((int(x) - int(region[0])) // pitch))

def _normalize_detection(det: dict, source: str, settings: dict | None, region) -> dict:
    key = str(det.get("key") or det.get("name") or "")
    kind = str(det.get("kind") or _kind(key))
    # YOLO class names may be bare labels; normalize common generic kind.
    if kind == "unit":
        kind = _kind(key)
    status = str(det.get("status") or _status(key))
    role = _role(key, kind, status)
    x = int(det.get("x", 0) or 0)
    out = dict(det)
    out.update({
        "key": key,
        "name": str(det.get("name") or key.rsplit("/", 1)[-1]),
        "kind": kind,
        "status": status,
        "role": role,
        "source": source,
        "slot": _slot_index(x, settings, region),
    })
    return out

def _yolo_enabled(settings: dict | None, model_path=None) -> bool:
    path = str(model_path or ((settings or {}).get("troop_yolo") or {}).get("model_path") or "").strip()
    return bool(path and os.path.isfile(path))

def detect_troop_bar(screen, settings: dict | None, mode=None, region=None, conf=None, threshold=None, model_path=None) -> dict:
    """Return normalized troop-bar detections.

    mode:
      - auto: use YOLO when a model exists, otherwise template recognizer
      - yolo: require YOLO model; returns ok=false if unavailable
      - template: asset-template recognizer
    """
    mode = str(mode or troop_bar_cfg(settings).get("mode") or "auto").lower()
    reg = _bar_region(settings, region)
    if screen is None:
        return {"ok": False, "source": "none", "error": "no screen", "detections": [], "region": None}

    if mode in ("auto", "yolo") and _yolo_enabled(settings, model_path=model_path):
        try:
            raw = detect_yolo_bar(screen, settings, model_path=model_path, region=reg, conf=conf)
        except RuntimeError as e:
            if mode == "yolo":
                return {"ok": False, "source": "yolo", "error": str(e), "detections": [], "region": reg}
            logger.info("[PERCEPTION] YOLO troop bar unavailable, falling back to template: %s", e)
        else:
            if raw.get("ok"):
                used_region = raw.get("region") or reg
                dets = [_normalize_detection(d, "yolo", settings, used_region) for d in raw.get("detections") or []]
                return {**raw, "ok": True, "source": "yolo", "detections": dets, "region": used_region}
            if mode == "yolo":
                return {**raw, "ok": False, "source": "yolo", "region": raw.get("region") or reg}

    if mode == "yolo":
        return {"ok": False, "source": "yolo", "error": "troop_yolo.model_path is empty or missing", "detections": [], "region": reg}

    raw = recognize_template_bar(screen, settings, region=reg, threshold=threshold)
    used_region = raw.get("region") or reg
    dets = [_normalize_detection(d, "template", settings, used_region) for d in raw.get("detections") or []]
    return {**raw, "ok": True, "source": "template", "detections": dets, "region": used_region}

def protected_centers(result: dict) -> list[int]:
    return [int(d["x"]) for d in result.get("detections") or [] if d.get("role") == "protected"]

def deployable_centers(result: dict, include_unknown=True) -> list[int]:
    roles = {"deployable"}
    if include_unknown:
        roles.add("event")
    return [int(d["x"]) for d in result.get("detections") or [] if d.get("role") in roles]
