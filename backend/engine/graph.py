"""Graph model — a superset of the old scenario format.

A graph is nodes + two edge kinds:
  - control edges: ``after`` (ordering / activation). Each entry is either a bare
    node id (default branch — always taken once the source ran) or
    ``{"from": id, "branch": "then"|"else"|...}`` (a branch edge, taken only when
    the source's chosen branch matches — used by the ``if`` block).
  - data edges:    ``data_in`` (port -> port, typed; resolved at run time). A data
    edge also implies ordering: the consumer runs after its producer.
  - ``on_error``:  optional node to jump to when this node raises (fail-stop).

JSON shape (per node):
    { "id","type","label","x","y",
      "params": {...},                                   # literal inputs
      "after": ["id", {"from":"id","branch":"then"} ...], # control edges
      "data_in": {"port": {"from":"nodeId","port":"out"}},
      "on_error": "nodeId" | null }
"""
from dataclasses import dataclass, field

from .registry import REGISTRY


def _edge_from(entry):
    """Source node id of an ``after`` entry (str or {"from","branch"})."""
    return entry["from"] if isinstance(entry, dict) else entry


def _edge_branch(entry):
    """Branch label of an ``after`` entry, or None for a default ordering edge."""
    return entry.get("branch") if isinstance(entry, dict) else None


@dataclass
class Node:
    id: str
    type: str
    label: str = ""
    x: float = 0.0
    y: float = 0.0
    params: dict = field(default_factory=dict)
    after: list = field(default_factory=list)   # raw entries: str | {"from","branch"}
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

    # -- normalized edge views (used by validate + executor) ---------------
    def control_edges(self):
        """[(from_id, branch_or_None), ...] over control (``after``) edges."""
        return [(_edge_from(e), _edge_branch(e)) for e in self.after]

    def data_sources(self):
        """Node ids this node reads data from (data_in)."""
        out = []
        for src in self.data_in.values():
            if isinstance(src, dict) and "from" in src:
                out.append(src["from"])
        return out

    def dep_ids(self):
        """All upstream ids (control + data) — the ordering predecessors."""
        return {f for f, _ in self.control_edges()} | set(self.data_sources())


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
        ``after`` / ``on_error`` / ``data_in``, and cycles over the combined
        control + data dependency graph (Kahn).
        """
        errors = []
        ids = [n.id for n in self.nodes]
        id_set = set(ids)

        seen = set()
        for nid in ids:
            if nid in seen:
                errors.append(f"duplicate node id: {nid!r}")
            seen.add(nid)

        for n in self.nodes:
            if n.type not in REGISTRY:
                errors.append(f"node {n.id!r}: unknown block type {n.type!r}")
            for frm, _branch in n.control_edges():
                if frm not in id_set:
                    errors.append(f"node {n.id!r}: after -> unknown node {frm!r}")
            if n.on_error and n.on_error not in id_set:
                errors.append(f"node {n.id!r}: on_error -> unknown node {n.on_error!r}")
            for port, src in n.data_in.items():
                frm = src.get("from") if isinstance(src, dict) else None
                if frm not in id_set:
                    errors.append(
                        f"node {n.id!r}: data_in[{port!r}] -> unknown node {frm!r}"
                    )

        # Cycle detection over control + data edges (Kahn). Only if refs are ok.
        if not errors:
            indeg = {n.id: 0 for n in self.nodes}
            adj = {n.id: [] for n in self.nodes}
            for n in self.nodes:
                for dep in n.dep_ids():
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
                errors.append("dependency cycle detected (graph is not a DAG)")

        return errors
