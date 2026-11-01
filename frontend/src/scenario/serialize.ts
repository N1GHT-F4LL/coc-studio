import type { Edge, Node } from "reactflow";
import type { DeployNode as DeployNodeT, Variant } from "./types";
import type { DeployNodeData } from "./DeployNode";

type RFNode = Node<DeployNodeData>;

// React Flow canvas -> variant.nodes. An edge A->B means B runs after A, so it
// becomes B.after.push(A) (mirror of graph/serialize.ts control edges).
export function toVariant(nodes: RFNode[], edges: Edge[]): DeployNodeT[] {
  const byId: Record<string, DeployNodeT> = {};
  for (const n of nodes) {
    byId[n.id] = {
      ...n.data.node,
      id: n.id,
      after: [],
      x: Math.round(n.position.x),
      y: Math.round(n.position.y),
    };
  }
  for (const e of edges) {
    const tgt = byId[e.target];
    if (tgt && byId[e.source]) tgt.after.push(e.source);
  }
  return Object.values(byId);
}

// Auto-layout (horizontal, suits a 16:9 screen): assign each node a level =
// longest dependency chain from a root (via after-edges), lay levels out
// left-to-right and stack siblings vertically. Within each column, order nodes
// by the BARYCENTRE of their neighbours (mean rank of preds going forward, of
// succs going backward) and sweep a few times — the standard layered-graph
// heuristic (Sugiyama) that pulls connected nodes onto the same row and so
// minimises edge crossings. Every column is centred on the same midline so
// chains read straight across and branches fan out symmetrically.
const LAYOUT_X = 240; // horizontal gap between levels (columns)
const LAYOUT_Y = 120; // vertical gap between siblings in a column
const LAYOUT_X0 = 60;
const LAYOUT_MID = 300; // y of the centre line each column is balanced around
const LAYOUT_SWEEPS = 4; // down/up barycentre passes — converges quickly

export function layoutNodes(nodes: RFNode[], edges: Edge[]): RFNode[] {
  // preds[id] = nodes this one runs after; succs[id] = nodes that run after it.
  const preds: Record<string, string[]> = {};
  const succs: Record<string, string[]> = {};
  for (const n of nodes) {
    preds[n.id] = [];
    succs[n.id] = [];
  }
  for (const e of edges) {
    if (preds[e.target] && succs[e.source]) {
      preds[e.target].push(e.source);
      succs[e.source].push(e.target);
    }
  }

  // Longest-path level via memoised DFS (cycles guarded by a visiting set).
  const level: Record<string, number> = {};
  const visiting = new Set<string>();
  const levelOf = (id: string): number => {
    if (level[id] !== undefined) return level[id];
    if (visiting.has(id)) return 0; // cycle — break
    visiting.add(id);
    const ps = preds[id] ?? [];
    const lv = ps.length ? Math.max(...ps.map(levelOf)) + 1 : 0;
    visiting.delete(id);
    level[id] = lv;
    return lv;
  };
  for (const n of nodes) levelOf(n.id);

  // Columns by level, seeded in insertion order.
  const maxLevel = nodes.reduce((m, n) => Math.max(m, level[n.id]), 0);
  const cols: string[][] = Array.from({ length: maxLevel + 1 }, () => []);
  for (const n of nodes) cols[level[n.id]].push(n.id);

  // rank[id] = current row index within its column (updated after each reorder).
  const rank: Record<string, number> = {};
  const reindex = () => cols.forEach((col) => col.forEach((id, i) => (rank[id] = i)));
  reindex();

  // Mean rank of a node's neighbours; null when it has none with a known rank.
  const barycentre = (ids: string[]): number | null => {
    const rs = ids.map((id) => rank[id]).filter((r) => r !== undefined);
    return rs.length ? rs.reduce((a, b) => a + b, 0) / rs.length : null;
  };
  // Stable sort by key; nodes with no neighbour (null key) keep their slot.
  const orderBy = (col: string[], key: (id: string) => number | null): string[] =>
    col
      .map((id, i) => {
        const k = key(id);
        return { id, k: k === null ? i : k, i };
      })
      .sort((a, b) => a.k - b.k || a.i - b.i)
      .map((w) => w.id);

  for (let s = 0; s < LAYOUT_SWEEPS; s++) {
    for (let l = 1; l <= maxLevel; l++) {
      cols[l] = orderBy(cols[l], (id) => barycentre(preds[id]));
      reindex();
    }
    for (let l = maxLevel - 1; l >= 0; l--) {
      cols[l] = orderBy(cols[l], (id) => barycentre(succs[id]));
      reindex();
    }
  }

  // Position: column = level (x), row = final rank centred on the midline (y).
  const pos: Record<string, { x: number; y: number }> = {};
  cols.forEach((col, l) => {
    col.forEach((id, idx) => {
      pos[id] = {
        x: LAYOUT_X0 + l * LAYOUT_X,
        y: LAYOUT_MID + (idx - (col.length - 1) / 2) * LAYOUT_Y,
      };
    });
  });

  return nodes.map((n) => ({ ...n, position: pos[n.id] }));
}

// variant.nodes -> React Flow canvas. Rebuilds after-edges; lays out nodes that
// lack a saved position in a simple vertical stack.
export function fromVariant(variant: Variant): { nodes: RFNode[]; edges: Edge[] } {
  const nodes: RFNode[] = [];
  const edges: Edge[] = [];
  variant.nodes.forEach((dn, i) => {
    nodes.push({
      id: dn.id,
      type: "deploy",
      position: { x: dn.x ?? 120, y: dn.y ?? 60 + i * 90 },
      data: { node: dn },
    });
    for (const dep of dn.after ?? []) {
      edges.push({
        id: `${dep}->${dn.id}`,
        source: dep,
        target: dn.id,
        sourceHandle: "out",
        targetHandle: "in",
      });
    }
  });
  return { nodes, edges };
}
