"""Graph model — a superset of the old scenario format.

A graph is nodes + two edge kinds:
  - control edges: ``after`` (ordering, like today's deploy nodes)
  - data edges:    ``data_in`` (port -> port, typed; resolved at run time)
  - ``on_error``:  optional node to jump to when this node raises (fail-stop).

JSON shape (per node):
    { "id","type","label","x","y",
      "params": {...},                                  # literal inputs
      "after": ["id", ...],                             # control edges
      "data_in": {"port": {"from":"nodeId","port":"out"}},
      "on_error": "nodeId" | null }
"""
from dataclasses import dataclass, field

from .registry import REGISTRY


@dataclass
class Node:
    id: str
    type: str
    label: str = ""
    x: float = 0.0
    y: float = 0.0
    params: dict = field(default_factory=dict)
    after: list = field(default_factory=list)
    data_in: dict = field(default_factory=dict)
    on_error: str = None

    @classmethod
    def from_dict(cls, d: dict) -> "Node":
        return cls(
            id=d["id"],
            type=d["type"],
            label=d.get("label", ""),
            x=d.get("x", 0.0),
            y=d.get("y", 0.0),
            params=dict(d.get("params", {})),
            after=list(d.get("after", [])),
            data_in=dict(d.get("data_in", {})),
            on_error=d.get("on_error"),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "label": self.label,
            "x": self.x,
            "y": self.y,
            "params": self.params,
            "after": self.after,
            "data_in": self.data_in,
            "on_error": self.on_error,
        }


@dataclass
class Graph:
    name: str
    nodes: list = field(default_factory=list)   # list[Node], original order preserved
    meta: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "Graph":
        return cls(
            name=d.get("name", "untitled"),
            nodes=[Node.from_dict(n) for n in d.get("nodes", [])],
            meta=dict(d.get("meta", {})),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "nodes": [n.to_dict() for n in self.nodes],
            "meta": self.meta,
        }

    def validate(self) -> list:
        """Return a list of human-readable errors ([] == valid).

        Checks: duplicate ids, unknown block types, dangling references in
        ``after`` / ``on_error`` / ``data_in``, and control-edge cycles (Kahn).
        """
        errors = []
        ids = [n.id for n in self.nodes]
        id_set = set(ids)

        # Duplicate ids.
        seen = set()
        for nid in ids:
            if nid in seen:
                errors.append(f"duplicate node id: {nid!r}")
            seen.add(nid)

        for n in self.nodes:
            if n.type not in REGISTRY:
                errors.append(f"node {n.id!r}: unknown block type {n.type!r}")
            for dep in n.after:
                if dep not in id_set:
                    errors.append(f"node {n.id!r}: after -> unknown node {dep!r}")
            if n.on_error and n.on_error not in id_set:
                errors.append(f"node {n.id!r}: on_error -> unknown node {n.on_error!r}")
            for port, src in n.data_in.items():
                frm = src.get("from") if isinstance(src, dict) else None
                if frm not in id_set:
                    errors.append(
                        f"node {n.id!r}: data_in[{port!r}] -> unknown node {frm!r}"
                    )

        # Cycle detection over control edges (Kahn). Only meaningful if refs ok.
        if not errors:
            indeg = {n.id: 0 for n in self.nodes}
            adj = {n.id: [] for n in self.nodes}
            for n in self.nodes:
                for dep in n.after:
                    adj[dep].append(n.id)   # dep -> n
                    indeg[n.id] += 1
            queue = [nid for nid, d in indeg.items() if d == 0]
            visited = 0
            while queue:
                cur = queue.pop()
                visited += 1
                for nxt in adj[cur]:
                    indeg[nxt] -= 1
                    if indeg[nxt] == 0:
                        queue.append(nxt)
            if visited != len(self.nodes):
                errors.append("control-edge cycle detected (graph is not a DAG)")

        return errors
