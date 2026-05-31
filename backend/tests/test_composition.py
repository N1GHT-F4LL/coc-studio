"""Unit tests for engine.composition.required_composition (no device needed).

Run directly:  python backend/tests/test_composition.py
Or under pytest if available.
"""
import json
import os
import sys

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _BACKEND)

from engine.composition import required_composition  # noqa: E402


def test_thrower_scenario():
    with open(os.path.join(_BACKEND, "data", "scenarios", "Thrower.json"), encoding="utf-8") as f:
        doc = json.load(f)
    c = required_composition(doc)
    assert c.troops == {
        "units/troops/archer": 12,
        "units/troops/healer": 6,
        "units/troops/thrower": 16,
    }, c.troops
    assert c.heroes == [
        "units/heroes/archer_queen",
        "units/heroes/barbarian_king",
        "units/heroes/grand_warden",
        "units/heroes/royal_champion",
    ], c.heroes
    assert c.spells == ["units/spells/rage", "units/spells/totem"], c.spells
    assert c.sieges == ["units/siege/log_launcher"], c.sieges


def test_legacy_slots_shape():
    # Old format: no variants, top-level slots list; repeated troop sums.
    doc = {
        "name": "x",
        "slots": [
            {"type": "troop", "template": "units/troops/giant", "taps": 5},
            {"type": "troop", "template": "units/troops/giant", "taps": 3},
            {"type": "spell", "template": "units/spells/heal", "taps": 2},
            {"type": "delay", "seconds": 2},
        ],
    }
    c = required_composition(doc)
    assert c.troops == {"units/troops/giant": 8}, c.troops
    assert c.spells == ["units/spells/heal"], c.spells


def test_max_across_variants():
    # Different variants -> train enough for the heaviest one (max per troop).
    doc = {
        "name": "x",
        "variants": [
            {"name": "a", "nodes": [{"type": "troop", "template": "units/troops/archer", "taps": 10}]},
            {"name": "b", "nodes": [{"type": "troop", "template": "units/troops/archer", "taps": 14}]},
        ],
    }
    c = required_composition(doc)
    assert c.troops == {"units/troops/archer": 14}, c.troops


if __name__ == "__main__":
    test_thrower_scenario()
    test_legacy_slots_shape()
    test_max_across_variants()
    print("OK: all composition tests passed")
