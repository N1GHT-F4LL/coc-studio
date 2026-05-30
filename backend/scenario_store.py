"""coc-studio scenario store (data/scenarios/).

A *scenario* is the deploy-bar program consumed by
``BattleScreen._slot_deploy`` — i.e. ``{name, variants:[{name,weight,nodes:[...]}]}``
where each node is a deploy slot (hero/siege/troop/delay with template/taps/
strategy/points/line). The ``deploy`` block + the scenario migrator use this.

This is separate from graphs (data/graphs/) which are coc-studio block-graphs.
"""
import json
import os

import app_paths


def _path(name):
    return os.path.join(app_paths.SCENARIOS_DIR, f"{name}.json")


def list_scenarios():
    d = app_paths.SCENARIOS_DIR
    if not os.path.isdir(d):
        return []
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json"))


def load_scenario(name):
    with open(_path(name), "r", encoding="utf-8") as f:
        return json.load(f)


def save_scenario(name, doc):
    os.makedirs(app_paths.SCENARIOS_DIR, exist_ok=True)
    with open(_path(name), "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)


def chosen_variant_nodes(doc):
    """Weighted-pick a variant's deploy nodes (mirrors AttackScreen scenario logic)."""
    import random

    variants = doc.get("variants") or [
        {"nodes": [{"id": "n0", "after": [], "delay": 0, "slots": doc.get("slots", [])}]}
    ]
    chosen = random.choices(variants, weights=[v.get("weight", 1) for v in variants])[0]
    # Backward compat: a variant with "slots" instead of "nodes".
    if "slots" in chosen and "nodes" not in chosen:
        chosen = dict(chosen)
        chosen["nodes"] = [
            {"id": "n0", "after": [], "delay": 0, "slots": chosen.pop("slots")}
        ]
    return chosen.get("nodes", []), chosen.get("name", "?")
