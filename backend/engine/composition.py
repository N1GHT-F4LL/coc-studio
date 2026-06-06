"""Derive the required army composition from a deploy scenario.

A scenario (``data/scenarios/<name>.json``) is a deploy-bar program:
``variants -> nodes -> (slots)``. Each unit slot carries ``type``
(troop / hero / spell / siege / delay), a ``template`` (e.g.
``"units/troops/thrower"``) and ``taps`` (how many were dropped).

``ensure_troops`` trains troops, spells AND sieges to match the scenario. For
each of those one deploy tap consumes one unit, so summing ``taps`` per template
gives the count to train/brew/select:
  - troops  -> count = sum of taps   (e.g. thrower x16)
  - spells  -> count = sum of taps   (e.g. totem x7, rage x2 -- each drop = 1 spell)
  - sieges  -> count = sum of taps   (e.g. log_launcher x1)
Heroes are the exception: a hero is tapped to deploy AND again to trigger its
ability, so taps != count. Heroes are not trained anyway (they just need to be
alive), so they are returned only as the set of distinct templates.

Counting rules:
  - Within a variant: sum ``taps`` per template.
  - Across variants: take the MAX per template, so we train enough for the
    heaviest variant (``deploy`` picks a variant at random).

Pure module -- no I/O, no engine deps -- so it is trivially unit-testable. The
caller passes an already-loaded scenario dict (see ``scenario_store``).
"""
from dataclasses import dataclass, field

# Types whose taps map 1:1 to "units to train", keyed by the section they live in.
_COUNTED = ("troop", "spell", "siege")

# Super troops occupy regular troop slots, so they're trained in the troop
# section — fold them into "troop" when counting.
_SECTION_ALIAS = {"super_troop": "troop"}


def _iter_variant_slots(doc):
    """Yield, per variant, the flat list of unit-slot dicts.

    Handles both node shapes:
      - a node carrying ``type``/``template``/``taps`` directly (newer scenarios), or
      - a node holding a ``slots`` list (older format / the back-compat wrapper).
    """
    variants = doc.get("variants") or [
        {"nodes": [{"slots": doc.get("slots", [])}]}
    ]
    for variant in variants:
        slots = []
        for node in variant.get("nodes", []):
            inner = node.get("slots")
            if isinstance(inner, list):
                slots.extend(inner)
            else:
                slots.append(node)
        yield slots


@dataclass
class Composition:
    """What an army must contain to run a scenario.

    troops/spells/sieges are ``{template: count}``; heroes is a distinct set.
    """
    troops: dict = field(default_factory=dict)
    spells: dict = field(default_factory=dict)
    sieges: dict = field(default_factory=dict)
    heroes: list = field(default_factory=list)   # distinct hero templates (not trained)

    def _fmt(self, d):
        return ", ".join(f"{t.rsplit('/', 1)[-1]}x{n}" for t, n in d.items()) or "-"

    def summary(self) -> str:
        return (f"troops[{self._fmt(self.troops)}] "
                f"spells[{self._fmt(self.spells)}] "
                f"sieges[{self._fmt(self.sieges)}]")

    def to_json(self) -> dict:
        return {"troops": self.troops, "spells": self.spells,
                "sieges": self.sieges, "heroes": self.heroes}


def required_composition(doc) -> Composition:
    """Resolve a scenario dict into the army it requires."""
    counts = {"troop": {}, "spell": {}, "siege": {}}
    heroes = set()

    for slots in _iter_variant_slots(doc):
        per_variant = {"troop": {}, "spell": {}, "siege": {}}
        for slot in slots:
            kind = (slot.get("type") or "").lower()
            kind = _SECTION_ALIAS.get(kind, kind)
            tpl = slot.get("template")
            if not tpl:
                continue
            if kind in _COUNTED:
                pv = per_variant[kind]
                pv[tpl] = pv.get(tpl, 0) + int(slot.get("taps", 0) or 0)
            elif kind == "hero":
                heroes.add(tpl)
        # Max per template across variants.
        for kind in _COUNTED:
            for tpl, n in per_variant[kind].items():
                counts[kind][tpl] = max(counts[kind].get(tpl, 0), n)

    return Composition(
        troops=dict(sorted(counts["troop"].items())),
        spells=dict(sorted(counts["spell"].items())),
        sieges=dict(sorted(counts["siege"].items())),
        heroes=sorted(heroes),
    )
