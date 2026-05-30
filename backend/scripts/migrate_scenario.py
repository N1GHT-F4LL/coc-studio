"""Migrate an old coc-tools scenario JSON into coc-studio.

Old scenarios (``d:\\coc-tools\\coc_bot\\scenarios\\*.json``) are already in the
deploy-bar node format that ``BattleScreen._slot_deploy`` consumes, so the
scenario itself is copied (normalized) into ``data/scenarios/<name>.json`` and a
runnable block-graph ``data/graphs/<name>_farm.json`` is generated:

    collect_resources -> find_match -> deploy(scenario=<name>) -> return_home

The ``deploy`` block's ``scenario`` param points back at the migrated scenario,
so running the graph drives the exact same deploy logic as the old PyQt bot
(deploy parity).

Usage (from backend/):
    ..\\.venv\\Scripts\\python.exe scripts\\migrate_scenario.py <source.json> [name]
"""
import json
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import app_paths  # noqa: E402
import scenario_store  # noqa: E402


def normalize(doc, name):
    """Ensure {name, variants:[{name,weight,nodes:[...]}]}; wrap legacy 'slots'."""
    variants = doc.get("variants")
    if not variants:
        # Legacy flat scenario: a single 'slots' list.
        variants = [{
            "name": "Default", "weight": 1,
            "nodes": [{"id": "n0", "after": [], "delay": 0, "slots": doc.get("slots", [])}],
        }]
    out = []
    for v in variants:
        nv = dict(v)
        if "slots" in nv and "nodes" not in nv:
            nv["nodes"] = [{"id": "n0", "after": [], "delay": 0, "slots": nv.pop("slots")}]
        out.append(nv)
    return {"name": name, "variants": out}


def farm_graph(name):
    """ensure_home -> collect -> find_match -> deploy(scenario=name) -> return_home."""
    return {
        "name": f"{name}_farm",
        "nodes": [
            {"id": "home0", "type": "ensure_home", "label": "Ensure Home",
             "x": 100, "y": 40, "params": {"zoom_out": True, "timeout": 10},
             "after": [], "data_in": {}, "on_error": None},
            {"id": "collect", "type": "collect_resources", "label": "Collect Resources",
             "x": 100, "y": 180, "params": {}, "after": ["home0"], "data_in": {}, "on_error": None},
            {"id": "find", "type": "find_match", "label": "Find Match",
             "x": 100, "y": 320, "params": {}, "after": ["collect"], "data_in": {}, "on_error": None},
            {"id": "deploy", "type": "deploy", "label": f"Deploy ({name})",
             "x": 100, "y": 460, "params": {"scenario": name}, "after": ["find"],
             "data_in": {}, "on_error": None},
            {"id": "home", "type": "return_home", "label": "Return Home",
             "x": 100, "y": 600, "params": {}, "after": ["deploy"], "data_in": {}, "on_error": None},
        ],
        "meta": {"migrated_from": name, "note": "M6 migrated scenario farm cycle"},
    }


def migrate(source_path, name=None):
    with open(source_path, "r", encoding="utf-8") as f:
        src = json.load(f)
    name = name or src.get("name") or os.path.splitext(os.path.basename(source_path))[0]

    doc = normalize(src, name)
    scenario_store.save_scenario(name, doc)

    os.makedirs(app_paths.GRAPHS_DIR, exist_ok=True)
    graph_path = os.path.join(app_paths.GRAPHS_DIR, f"{name}_farm.json")
    with open(graph_path, "w", encoding="utf-8") as f:
        json.dump(farm_graph(name), f, indent=2, ensure_ascii=False)

    total_nodes = sum(len(v.get("nodes", [])) for v in doc["variants"])
    print(f"Migrated '{name}': {len(doc['variants'])} variant(s), "
          f"{total_nodes} deploy node(s)")
    print(f"  scenario -> {os.path.join(app_paths.SCENARIOS_DIR, name + '.json')}")
    print(f"  graph    -> {graph_path}")
    return name


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: migrate_scenario.py <source.json> [name]")
        sys.exit(2)
    migrate(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
