"""REST: read/write the same settings.json contract as the upstream bot."""
import json
import logging

from fastapi import APIRouter, Body, HTTPException

from device_manager import load_settings, save_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["settings"])

# Keys the upstream requirement gate enforces (REQUIREMENT §15). We validate
# top-level groups exist on write so the GUI can't silently drop the contract.
REQUIRED_GROUPS = ("device", "farm", "delays", "jitter")


@router.get("/settings")
def get_settings():
    try:
        return load_settings()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="settings.json not found")
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"settings.json invalid: {e}")


@router.put("/settings")
def put_settings(settings: dict = Body(...)):
    missing = [g for g in REQUIRED_GROUPS if g not in settings]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"settings missing required groups: {', '.join(missing)}",
        )
    save_settings(settings)
    logger.info("settings.json updated via API")
    return {"ok": True}
