"""Asset studio REST — list/serve template assets + save a crop from the device.

Ports the PyQt studio (coc-tools gui/tabs/studio.py + _CAT_TO_FOLDER): the
browser draws a crop rect over a live device frame and POSTs the region; the
backend captures the current screen, crops it, writes the PNG under
``assets/<folder>/<name>.png`` and hot-loads it into ``vision.cache`` so it's
usable immediately (no restart, no cv2.imread in loops).
"""
import glob
import json
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
    "Roster (train faces)": "units/roster",
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


_VALID_FOLDERS = set(CAT_TO_FOLDER.values())


def _rel_to_path(rel: str) -> str:
    """Resolve an asset key (rel posix, no .png) to its file path, guarding traversal."""
    if ".." in rel or rel.startswith("/"):
        raise HTTPException(status_code=400, detail="bad asset path")
    return os.path.join(app_paths.ASSETS_DIR, *rel.split("/")) + ".png"


def _sanitize_name(raw: str) -> str:
    name = re.sub(r"[^a-z0-9_]", "_", (raw or "").strip().lower())
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    return name


def _evict_cache(rel: str) -> None:
    """Drop an asset from the vision cache by its rel key, plus its bare-stem key
    only when that key still points at THIS image (load_assets keys by both, but
    the stem is shared-first-wins — don't evict another asset's stem)."""
    img = vision.cache.pop(rel, None)
    stem = rel.split("/")[-1]
    if img is not None and vision.cache.get(stem) is img:
        vision.cache.pop(stem, None)


def _load_into_cache(path: str, folder: str, name: str) -> None:
    """Mirror load_assets: cache the GRAYSCALE image under both folder/name and
    bare stem (stem only if free)."""
    key = f"{folder}/{name}"
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return
    if name not in vision.cache:
        vision.cache[name] = img
    vision.cache[key] = img


@router.get("/categories")
def categories() -> dict:
    return {"categories": [{"label": k, "folder": v} for k, v in CAT_TO_FOLDER.items()]}


@router.get("")
def list_assets(cat: str = "") -> dict:
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
def thumb(rel: str) -> FileResponse:
    path = _rel_to_path(rel)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="asset not found")
    return FileResponse(path, media_type="image/png")


@router.post("/crop")
def save_crop(body: dict = Body(...)) -> dict:
    """Capture the live screen, crop ``region``, save as ``<folder>/<name>.png``.

    body: { "region": [x1,y1,x2,y2], "folder": "units/troops", "name": "thrower" }
    """
    region = body.get("region")
    folder = (body.get("folder") or "").strip("/")
    if not (isinstance(region, list) and len(region) == 4):
        raise HTTPException(status_code=400, detail="region must be [x1,y1,x2,y2]")
    if folder not in _VALID_FOLDERS:
        raise HTTPException(status_code=400, detail="unknown asset folder")
    name = _sanitize_name(body.get("name", ""))

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

    # Hot-load into the vision cache under both keys (like the old studio). Re-read
    # as grayscale so the cache matches load_assets (the matcher works in gray).
    key = f"{folder}/{name}"
    _evict_cache(key)
    _load_into_cache(dest, folder, name)
    logger.info("Saved asset %s (%dx%d)", key, x2 - x1, y2 - y1)
    return {"ok": True, "key": key, "width": x2 - x1, "height": y2 - y1}


@router.post("/move")
def move_asset(body: dict = Body(...)) -> dict:
    """Rename / re-categorise an asset: move ``src`` -> ``<folder>/<name>.png``.

    body: { "src": "units/troops/archer", "folder": "units/troops", "name": "archer2" }
    """
    src = (body.get("src") or "").strip("/")
    folder = (body.get("folder") or "").strip("/")
    if not src:
        raise HTTPException(status_code=400, detail="src is required")
    if folder not in _VALID_FOLDERS:
        raise HTTPException(status_code=400, detail="unknown asset folder")
    name = _sanitize_name(body.get("name", ""))

    src_path = _rel_to_path(src)
    if not os.path.isfile(src_path):
        raise HTTPException(status_code=404, detail="asset not found")

    key = f"{folder}/{name}"
    dest_dir = os.path.join(app_paths.ASSETS_DIR, *folder.split("/"))
    dest = os.path.join(dest_dir, f"{name}.png")
    if os.path.abspath(dest) != os.path.abspath(src_path) and os.path.exists(dest):
        raise HTTPException(status_code=409, detail=f"{key} already exists")

    os.makedirs(dest_dir, exist_ok=True)
    os.replace(src_path, dest)
    _evict_cache(src)
    _load_into_cache(dest, folder, name)
    logger.info("Moved asset %s -> %s", src, key)
    return {"ok": True, "key": key}


@router.get("/usage/{rel:path}")
def asset_usage(rel: str) -> dict:
    """Where an asset key is referenced, so the UI can warn before rename/delete.

    Templates are stored as strings — either the full ``folder/name`` rel key or
    the bare stem — so match both. Scans data/graphs + data/scenarios JSON.
    """
    if ".." in rel or rel.startswith("/"):
        raise HTTPException(status_code=400, detail="bad asset path")
    targets = {rel, rel.split("/")[-1]}

    def _hits(path: str) -> bool:
        try:
            with open(path, "r", encoding="utf-8") as f:
                blob = f.read()
        except OSError:
            return False
        # Cheap string scan first; only parse if a candidate substring is present.
        if not any(t in blob for t in targets):
            return False
        try:
            doc = json.loads(blob)
        except ValueError:
            return False
        found = {"v": False}

        def walk(x):
            if isinstance(x, str):
                if x in targets:
                    found["v"] = True
            elif isinstance(x, dict):
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)

        walk(doc)
        return found["v"]

    graphs = sorted(
        os.path.splitext(os.path.basename(p))[0]
        for p in glob.glob(os.path.join(app_paths.GRAPHS_DIR, "*.json"))
        if _hits(p)
    )
    scenarios = sorted(
        os.path.splitext(os.path.basename(p))[0]
        for p in glob.glob(os.path.join(app_paths.SCENARIOS_DIR, "*.json"))
        if _hits(p)
    )
    return {"graphs": graphs, "scenarios": scenarios}


@router.delete("/{rel:path}")
def delete_asset(rel: str) -> dict:
    path = _rel_to_path(rel)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="asset not found")
    os.remove(path)
    _evict_cache(rel)
    logger.info("Deleted asset %s", rel)
    return {"ok": True}
