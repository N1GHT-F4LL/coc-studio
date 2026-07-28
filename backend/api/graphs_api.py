"""REST CRUD for graph JSON files in data/graphs/.

Minimal persistence so graphs (incl. the M2 parity graph) can be saved/loaded;
rounds out the API surface the frontend (M3) will use.
"""
import json
import logging
import os
import re

from fastapi import APIRouter, Body, HTTPException

import app_paths
from engine.graph import Graph

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/graphs", tags=["graphs"])

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _path(name: str) -> str:
    # Reject path traversal / odd names — graphs live as flat files.
    if not _NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="invalid graph name")
    return os.path.join(app_paths.GRAPHS_DIR, f"{name}.json")


@router.get("")
def list_graphs() -> dict:
    os.makedirs(app_paths.GRAPHS_DIR, exist_ok=True)
    names = [
        f[:-5] for f in os.listdir(app_paths.GRAPHS_DIR) if f.endswith(".json")
    ]
    return {"graphs": sorted(names)}


@router.get("/{name}")
def get_graph(name: str) -> dict:
    path = _path(name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="graph not found")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@router.put("/{name}")
def put_graph(name: str, graph: dict = Body(...)) -> dict:
    # Structural validation before persisting (unknown type / cycle / dangling ref).
    errors = Graph.from_dict(graph).validate()
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})
    os.makedirs(app_paths.GRAPHS_DIR, exist_ok=True)
    with open(_path(name), "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2)
    logger.info("graph %r saved", name)
    return {"ok": True}


@router.delete("/{name}")
def delete_graph(name: str) -> dict:
    path = _path(name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="graph not found")
    os.remove(path)
    return {"ok": True}
