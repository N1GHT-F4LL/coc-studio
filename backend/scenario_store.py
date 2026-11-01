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


# Round-robin state persists here (per scenario name: index of the last chosen
# variant), so rotation continues across backend restarts and run loops — same
# machine-local pattern as data/coord_cache.json (gitignored).
_STATE_PATH = os.path.join(app_paths.DATA_DIR, "scenario_state.json")


def _load_state():
    try:
        with open(_STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(state):
    try:
        with open(_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=1)
    except OSError:
        pass  # rotation still works in-memory for this run


def pick_variant_rotating(doc, name):
    """Round-robin variant pick: variant 0, 1, 2, ... then wrap to 0.

    Unlike ``pick_variant`` (weighted random), this cycles the variants in their
    listed order so consecutive attacks use consecutive variants. The last
    chosen index is persisted per scenario name, so the rotation survives a
    backend restart. Variant weights are ignored here (rotation = equal turns).
    """
    variants = _variants(doc)
    key = name or doc.get("name") or "_anonymous"
    state = _load_state()
    last = state.get(key)
    idx = 0 if not isinstance(last, int) else (last + 1) % len(variants)
    state[key] = idx
    _save_state(state)
    return _normalise(variants[idx])


# Snapshot of the scaled army a scenario trains — RUN-LIFETIME cache
# (in-memory, NOT persisted): {"troop": 240, "spell": 11, "siege": 3,
# "capacity": 240, "counts": {"units/troops/dragon": 9, ...}}. ensure_troops
# records it right after a successful training pass and later cycles verify
# against it; RunHub clears it on Stop and on Start, so each Run session
# re-derives it for whatever camp the account actually has.
# KEYED BY SCENARIO ONLY (not per variant): rotation plans train the SAME army
# for every variant, so a per-variant key would miss on every rotation cycle
# and force a full retrain each attack.
_ARMY_CACHE = {}

# Run-session flags (e.g. "village_zoomed") — same lifecycle as the army
# cache: set during a Run session, cleared by RunHub on Stop/Start.
_SESSION_FLAGS = {}


def get_session_flag(key, default=None):
    return _SESSION_FLAGS.get(key, default)


def set_session_flag(key, value):
    _SESSION_FLAGS[key] = value


def get_army_totals(scenario, variant=None):
    return _ARMY_CACHE.get(scenario)


def set_army_totals(scenario, variant=None, data=None):
    _ARMY_CACHE[scenario] = data


def clear_army_cache():
    _ARMY_CACHE.clear()
    _SESSION_FLAGS.clear()


def variant_nodes_by_name(doc, name, selection="random"):
    """Nodes of the variant called ``name`` (so deploy reuses ensure_troops'
    pick). Falls back to a fresh pick when ``name`` is missing/unknown —
    weighted-random by default, or round-robin when ``selection="rotate"``."""
    if name:
        for v in _variants(doc):
            if v.get("name") == name:
                v = _normalise(v)
                return v.get("nodes", []), v.get("name", "?")
    chosen = (
        pick_variant_rotating(doc, doc.get("name"))
        if selection == "rotate"
        else pick_variant(doc)
    )
    return chosen.get("nodes", []), chosen.get("name", "?")


def chosen_variant_nodes(doc):
    """Weighted-pick a variant's deploy nodes (mirrors AttackScreen scenario logic)."""
    chosen = pick_variant(doc)
    return chosen.get("nodes", []), chosen.get("name", "?")
