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


def _variants(doc):
    """The doc's variant list, with the legacy single-`slots` doc wrapped."""
    return doc.get("variants") or [
        {"nodes": [{"id": "n0", "after": [], "delay": 0, "slots": doc.get("slots", [])}]}
    ]


def _normalise(variant):
    """A variant whose nodes are usable (legacy `slots` wrapped into a node)."""
    if "slots" in variant and "nodes" not in variant:
        variant = dict(variant)
        variant["nodes"] = [{"id": "n0", "after": [], "delay": 0, "slots": variant.pop("slots")}]
    return variant


def pick_variant(doc):
    """Weighted-pick one variant (normalised). The deploy bar uses one variant per
    attack, so training and deploying must agree on the SAME pick — pick once
    here and pass the name to ``variant_nodes_by_name``."""
    import random

    variants = _variants(doc)
    chosen = random.choices(variants, weights=[v.get("weight", 1) for v in variants])[0]
    return _normalise(chosen)


def variant_nodes_by_name(doc, name):
    """Nodes of the variant called ``name`` (so deploy reuses ensure_troops'
    pick). Falls back to a fresh weighted pick when ``name`` is missing/unknown."""
    if name:
        for v in _variants(doc):
            if v.get("name") == name:
                v = _normalise(v)
                return v.get("nodes", []), v.get("name", "?")
    chosen = pick_variant(doc)
    return chosen.get("nodes", []), chosen.get("name", "?")


def chosen_variant_nodes(doc):
    """Weighted-pick a variant's deploy nodes (mirrors AttackScreen scenario logic)."""
    chosen = pick_variant(doc)
    return chosen.get("nodes", []), chosen.get("name", "?")
