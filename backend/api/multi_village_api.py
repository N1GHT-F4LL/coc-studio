"""Multi-Village management REST — config, per-village Load/Save/Apply, stats.

Load   POST /api/multi_village/load/{idx}   -> returns the village config and
        points the backend's active_village_idx at it (NO account switch).
Save   POST /api/multi_village/save/{idx}   -> guarded write of the editor's
        config into villages[idx] (allowed only for the active village with an
        existing config — exact plan rule).
Apply  POST /api/multi_village/apply/{idx}  -> one-time onboarding commit:
        switch-verify the account, persist config, capture home_v{idx}.png,
        mark confirmed. Requires the device and NO active run.
"""
import logging
import os
import time

import cv2
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse

import app_paths
import multi_village as mv
from api.run_api import controller

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/multi_village", tags=["multi_village"])

INTERVAL_OPTIONS = mv.INTERVAL_OPTIONS
def _require_run_idle():
    if controller.running:
        raise HTTPException(
            status_code=409,
            detail="A run is active — stop it before switching accounts.")


def _validate_interval(cfg: dict) -> dict:
    mins = cfg.get("interval_mins")
    if not isinstance(mins, int) or mins < 1:
        raise HTTPException(status_code=400,
                            detail="interval_mins must be an integer >= 1 (minutes)")
    return cfg


@router.get("")
def get_multi_village():
    cfg = mv.load_config()
    return {
        "config": cfg,
        "active_village_idx": mv.get_state()["active_village_idx"],
        "current_village_idx": mv.get_state()["current_village_idx"],
        "stats": {v["idx"]: mv.load_stats(v["idx"])
                  for v in cfg.get("villages", [])},
        "template_ready": os.path.isfile(mv.SETTINGS_TAB_TEMPLATE),
        "coords_calibrated": (
            cfg.get("coords", {}).get("scid_switch_id") is not None
            and any(v.get("scid_row") for v in cfg.get("villages", []))),
    }


@router.put("/config")
def put_config(cfg: dict = Body(...)):
    _validate_interval(cfg)
    villages = cfg.get("villages")
    if not isinstance(villages, list):
        raise HTTPException(status_code=400, detail="villages must be a list")
    mv.save_config(cfg)
    logger.info("multi_village.json updated via API")
    return {"ok": True}


@router.post("/load/{idx}")
def load_village(idx: int):
    """Point the editor at village idx. A village with no saved config yet
    (first-time setup) returns config=None — the editor opens with defaults
    and the first Save creates the config."""
    cfg = mv.load_config()
    v = mv.village(cfg, idx)
    if v is None:
        raise HTTPException(status_code=404, detail=f"Village_{idx} does not exist.")
    mv.set_active_village_idx(idx)
    logger.info("[MV] Load: editor pointed at village %s (config saved: %s)",
                idx, v.get("config") is not None)
    return {"ok": True, "idx": idx, "config": v.get("config")}


@router.post("/save/{idx}")
def save_village(idx: int, body: dict = Body(...)):
    state = mv.get_state()
    if state["active_village_idx"] != idx:
        raise HTTPException(
            status_code=409,
            detail="Cannot save configuration: this village has not been "
                   "loaded into the editor (press Load first).")
    cfg = mv.load_config()
    v = mv.village(cfg, idx)
    config = body.get("config")
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="body must be {\"config\": {...}}")
    v["config"] = config
    mv.save_config(cfg)
    logger.info("[MV] Save: village %s config written.", idx)
    return {"ok": True, "idx": idx, "config": config}


@router.post("/apply/{idx}")
def apply_village(idx: int, body: dict = Body(...)):
    _require_run_idle()
    cfg = mv.load_config()
    v = mv.village(cfg, idx)
    if v is None:
        raise HTTPException(status_code=404, detail=f"Village_{idx} does not exist.")
    config = body.get("config")
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="body must be {\"config\": {...}}")

    # persist the config BEFORE the switch so apply_village_config (called by
    # the switch flow via ctx-less path) reads it
    v["config"] = config
    mv.save_config(cfg)

    import multi_village as _m
    if not _m.switch_to_village(idx):
        raise HTTPException(status_code=502,
                            detail=f"Switch to Village_{idx} failed — row NOT locked. "
                                   "Check the [MV] logs; fix coords and retry.")

    # verify home was reached (switch_to_village already did) + capture icon
    _m.apply_village_config(idx, ctx=None)
    os.makedirs(_m.MV_DIR, exist_ok=True)
    frame = _m._screencap()
    if frame is not None:
        cv2.imwrite(os.path.join(_m.MV_DIR, f"home_v{idx}.png"), frame)
    cfg = mv.load_config()
    mv.village(cfg, idx)["confirmed"] = True
    mv.save_config(cfg)
    with mv._lock:
        mv._state["current_village_idx"] = idx
        mv._state["active_village_idx"] = idx
        mv._state["last_switch_ts"] = time.time()
    logger.info("[MV] Apply: village %s confirmed + locked.", idx)
    return {"ok": True, "idx": idx, "confirmed": True,
            "icon": os.path.join(_m.MV_DIR, f"home_v{idx}.png")}


@router.get("/icon/{idx}")
def village_icon(idx: int):
    path = os.path.join(mv.MV_DIR, f"home_v{idx}.png")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="no snapshot yet")
    return FileResponse(path, media_type="image/png")


@router.post("/delete_all")
def delete_all():
    cfg = mv.load_config()
    for v in cfg.get("villages", []):
        v["config"] = None
        v["confirmed"] = False
        v["enabled"] = False
    cfg["enabled"] = False
    mv.save_config(cfg)
    mv.reset_all_stats()
    removed = []
    for idx in range(1, 6):
        p = os.path.join(mv.MV_DIR, f"home_v{idx}.png")
        if os.path.isfile(p):
            os.remove(p)
            removed.append(os.path.basename(p))
    with mv._lock:
        mv._state["active_village_idx"] = None
        mv._state["current_village_idx"] = None
        mv._state["last_switch_ts"] = 0.0
    logger.info("[MV] Delete All: configs + %d snapshot(s) removed.", len(removed))
    return {"ok": True, "removed_icons": removed}
