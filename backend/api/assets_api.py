"""Asset studio REST — list/serve template assets + save a crop from the device.

Ports the PyQt studio (coc-tools gui/tabs/studio.py + _CAT_TO_FOLDER): the
browser draws a crop rect over a live device frame and POSTs the region; the
backend captures the current screen, crops it, writes the PNG under
``assets/<folder>/<name>.png`` and hot-loads it into ``vision.cache`` so it's
usable immediately (no restart, no cv2.imread in loops).
"""
import logging
import os
import re

import cv2
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse

import app_paths
from core.vision import vision
from device_manager import manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/assets", tags=["assets"])

# Friendly category -> asset subfolder (ported verbatim from coc-tools).
CAT_TO_FOLDER = {
    "Troops": "units/troops",
    "Super Troops": "units/super_troops",
    "Heroes": "units/heroes",
    "Spells": "units/spells",
    "Siege": "units/siege",
    "Clan Capital / Troops": "units/clan_capital/troops",
    "Clan Capital / Spells": "units/clan_capital/spells",
    "Buildings / Defenses": "buildings/defenses",
    "Buildings / Collectors": "buildings/resource_collectors",
    "Buildings / Storages": "buildings/storages",
    "Buildings / Utility": "buildings/utility",
    "Buildings / Walls": "buildings/walls",
    "Buttons / Attack": "buttons/attack",
    "Buttons / Battle": "buttons/battle",
    "Buttons / Home": "buttons/home",
    "Buttons / Popup": "buttons/popup",
    "Icons / Resources": "icons/resources",
    "Icons / Status": "icons/status",
}


@router.get("/categories")
def categories():
    return {"categories": [{"label": k, "folder": v} for k, v in CAT_TO_FOLDER.items()]}


@router.get("")
def list_assets(cat: str = ""):
    """Asset keys (rel posix paths without .png). ``cat`` filters by folder prefix."""
    root = app_paths.ASSETS_DIR
    keys = []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if not f.endswith(".png"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, f), root).replace(os.sep, "/")
            rel = rel[:-4]  # strip .png
            if cat and not rel.startswith(cat):
                continue
            keys.append(rel)
    return {"assets": sorted(keys)}


@router.get("/thumb/{rel:path}")
def thumb(rel: str):
    # Guard against path traversal; assets are flat .png under ASSETS_DIR.
    if ".." in rel or rel.startswith("/"):
        raise HTTPException(status_code=400, detail="bad asset path")
    path = os.path.join(app_paths.ASSETS_DIR, *rel.split("/")) + ".png"
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="asset not found")
    return FileResponse(path, media_type="image/png")


@router.post("/crop")
def save_crop(body: dict = Body(...)):
    """Capture the live screen, crop ``region``, save as ``<folder>/<name>.png``.

    body: { "region": [x1,y1,x2,y2], "folder": "units/troops", "name": "thrower" }
    """
    region = body.get("region")
    folder = (body.get("folder") or "").strip("/")
    raw_name = (body.get("name") or "").strip()
    if not (isinstance(region, list) and len(region) == 4):
        raise HTTPException(status_code=400, detail="region must be [x1,y1,x2,y2]")
    if not folder:
        raise HTTPException(status_code=400, detail="folder is required")
    name = re.sub(r"[^a-z0-9_]", "_", raw_name.lower())
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    frame = manager.capture_bgr()
    if frame is None:
        raise HTTPException(status_code=409, detail="device not connected / no frame")

    h, w = frame.shape[:2]
    x1, y1, x2, y2 = (int(v) for v in region)
    x1, x2 = sorted((max(0, min(w, x1)), max(0, min(w, x2))))
    y1, y2 = sorted((max(0, min(h, y1)), max(0, min(h, y2))))
    if x2 - x1 < 2 or y2 - y1 < 2:
        raise HTTPException(status_code=400, detail="crop region too small")

    crop = frame[y1:y2, x1:x2].copy()
    dest_dir = os.path.join(app_paths.ASSETS_DIR, *folder.split("/"))
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"{name}.png")
    if not cv2.imwrite(dest, crop):
        raise HTTPException(status_code=500, detail=f"failed to write {dest}")

    # Hot-load into the vision cache under both keys (like the old studio).
    key = f"{folder}/{name}"
    vision.cache[name] = crop
    vision.cache[key] = crop
    logger.info("Saved asset %s (%dx%d)", key, x2 - x1, y2 - y1)
    return {"ok": True, "key": key, "width": x2 - x1, "height": y2 - y1}
