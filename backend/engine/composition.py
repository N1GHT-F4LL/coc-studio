"""Derive the required army composition from a deploy scenario.

A scenario (``data/scenarios/<name>.json``) is a deploy-bar program:
``variants -> nodes -> (slots)``. Each unit slot carries ``type``
(troop / hero / spell / siege / delay), a ``template`` (e.g.
``"units/troops/thrower"``) and ``taps`` (how many were dropped).

``ensure_troops`` needs to know how many of each *troop* to train. Only
``type == "troop"`` slots are trainable here:
  - heroes are not trained (they just need to be alive),
  - sieges are built in the Workshop,
  - spells are brewed — and the JSON can't tell us how many to brew, because
    spells are tapped per drop-point, not per unit. So spells/sieges/heroes are
    returned only as the *set* of distinct templates.

Counting rules for troops:
  - Within a variant: sum ``taps`` per troop template (each tap = one troop).
  - Across variants: take the MAX per troop, so we train enough for the
    heaviest variant (``deploy`` picks a variant at random).

Pure module — no I/O, no engine deps — so it is trivially unit-testable. The
caller passes an already-loaded scenario dict (see ``scenario_store``).
"""
from dataclasses import dataclass, field


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
    """What an army must contain to run a scenario."""
    troops: dict = field(default_factory=dict)   # template -> count to train
    heroes: list = field(default_factory=list)   # distinct hero templates (not trained)
    spells: list = field(default_factory=list)   # distinct spell templates (brew counts unknown)
    sieges: list = field(default_factory=list)   # distinct siege templates (built in Workshop)

    def summary(self) -> str:
        """Human one-liner, e.g. ``thrower×16, healer×6, archer×12``."""
        parts = [f"{tpl.rsplit('/', 1)[-1]}×{n}" for tpl, n in self.troops.items()]
        return ", ".join(parts) if parts else "(no trainable troops)"

    def to_json(self) -> dict:
        return {
            "troops": self.troops,
            "heroes": self.heroes,
            "spells": self.spells,
            "sieges": self.sieges,
        }


def required_composition(doc) -> Composition:
    """Resolve a scenario dict into the army it requires."""
    troops: dict = {}
    heroes, spells, sieges = set(), set(), set()

    for slots in _iter_variant_slots(doc):
        per_variant: dict = {}
        for slot in slots:
            kind = (slot.get("type") or "").lower()
            tpl = slot.get("template")
            if not tpl:
                continue
            if kind == "troop":
                per_variant[tpl] = per_variant.get(tpl, 0) + int(slot.get("taps", 0) or 0)
            elif kind == "hero":
                heroes.add(tpl)
            elif kind == "spell":
                spells.add(tpl)
            elif kind == "siege":
                sieges.add(tpl)
        # Max per troop across variants (train enough for the heaviest variant).
        for tpl, n in per_variant.items():
            troops[tpl] = max(troops.get(tpl, 0), n)

    return Composition(
        troops=dict(sorted(troops.items())),
        heroes=sorted(heroes),
        spells=sorted(spells),
        sieges=sorted(sieges),
    )
