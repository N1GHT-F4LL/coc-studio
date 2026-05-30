"""Block registry — declarative BlockSpec + typed ports + @register.

A block declares its typed ``inputs`` (literals/params, edited in the GUI) and
``outputs`` (data ports). ``Kind`` drives both engine validation and the React
Flow handle colors (M3). The GUI param form is auto-generated from ``inputs``.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class Kind(str, Enum):
    """Port/param value kinds. ``str`` mixin → JSON-serializes to its name."""
    Coord = "Coord"        # (x, y)
    Number = "Number"
    Template = "Template"  # asset key, e.g. "buttons/home/btn_attack"
    Region = "Region"      # (x1, y1, x2, y2)
    Bool = "Bool"
    Text = "Text"
    Trigger = "Trigger"    # pure control pulse (no value)


@dataclass
class Param:
    """A literal/configurable input, rendered as a form field in the GUI.

    ``choices`` (optional) turns the field into a dropdown of allowed values.
    """
    name: str
    kind: Kind
    default: Any = None
    label: Optional[str] = None
    choices: Optional[list] = None

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "default": self.default,
            "label": self.label or self.name,
            "choices": self.choices,
        }


@dataclass
class Port:
    """A typed data output (or input) port for data edges."""
    name: str
    kind: Kind
    label: Optional[str] = None

    def to_json(self) -> dict:
        return {"name": self.name, "kind": self.kind.value, "label": self.label or self.name}


class BlockSpec:
    """Base class for all blocks. Subclasses set class attrs + implement run().

    Class attributes (override in subclasses):
        label    : human-readable name (palette)
        category : palette grouping
        inputs   : list[Param]  — literal params (auto-formed in GUI)
        outputs  : list[Port]   — typed data outputs
    """
    label: str = ""
    category: str = "General"
    inputs: list = []
    outputs: list = []

    def run(self, ctx, inputs: dict) -> dict:
        """Execute the block. Return a dict of {output_name: value} (or {})."""
        raise NotImplementedError


# type_name -> BlockSpec subclass
REGISTRY: dict = {}


def register(type_name: str):
    """Class decorator: register a BlockSpec under ``type_name``."""
    def deco(cls):
        if type_name in REGISTRY:
            raise ValueError(f"Block type already registered: {type_name!r}")
        cls.type_name = type_name
        REGISTRY[type_name] = cls
        return cls
    return deco


def spec_json(type_name: str) -> dict:
    cls = REGISTRY[type_name]
    return {
        "type": type_name,
        "label": cls.label or type_name,
        "category": cls.category,
        "inputs": [p.to_json() for p in cls.inputs],
        "outputs": [p.to_json() for p in cls.outputs],
    }


def all_specs() -> list:
    """All registered specs as JSON — drives the frontend palette (M3)."""
    return [spec_json(t) for t in sorted(REGISTRY)]
