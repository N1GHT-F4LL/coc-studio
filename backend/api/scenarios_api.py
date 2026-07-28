"""REST CRUD for deploy scenarios (data/scenarios/).

A scenario is the deploy-bar program consumed by ``TroopDeployer.deploy_slots``
— ``{name, variants:[{name,weight,nodes:[...]}]}`` where each node is a deploy
slot (troop/spell/siege/hero/delay with template/taps/strategy/points/line).
The ``deploy`` + ``ensure_troops`` blocks read these by name; this module lets
the web scenario editor create/edit them (previously only the migrator could).
"""
import logging
import os
import re

from fastapi import APIRouter, Body, HTTPException

import app_paths
import scenario_store
from engine.composition import required_composition

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _check_name(name: str) -> str:
    # Reject path traversal / odd names — scenarios live as flat files.
    if not _NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="invalid scenario name")
    return name


@router.get("")
def list_scenarios() -> dict:
    return {"scenarios": scenario_store.list_scenarios()}


@router.get("/{name}")
def get_scenario(name: str) -> dict:
    _check_name(name)
    try:
        return scenario_store.load_scenario(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="scenario not found")


@router.get("/{name}/composition")
def get_composition(name: str) -> dict:
    _check_name(name)
    try:
        doc = scenario_store.load_scenario(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="scenario not found")
    return required_composition(doc).to_json()


@router.put("/{name}")
def put_scenario(name: str, doc: dict = Body(...)) -> dict:
    _check_name(name)
    if not isinstance(doc.get("variants"), list):
        raise HTTPException(status_code=400, detail="scenario must have a 'variants' list")
    # Persist under the URL name; keep the doc's own name field in sync.
    doc = {**doc, "name": name}
    scenario_store.save_scenario(name, doc)
    logger.info("scenario %r saved (%d variant(s))", name, len(doc["variants"]))
    return {"ok": True}


@router.delete("/{name}")
def delete_scenario(name: str) -> dict:
    _check_name(name)
    path = os.path.join(app_paths.SCENARIOS_DIR, f"{name}.json")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="scenario not found")
    os.remove(path)
    return {"ok": True}
