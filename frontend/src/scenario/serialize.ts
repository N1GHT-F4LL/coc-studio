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
// left-to-right and stack siblings vertically. Every column is centred on the
// same horizontal midline so chains read straight across and branches fan out
// symmetrically above/below — no drift.
const LAYOUT_X = 240; // horizontal gap between levels (columns)
const LAYOUT_Y = 120; // vertical gap between siblings in a column
const LAYOUT_X0 = 60;
const LAYOUT_MID = 300; // y of the centre line each column is balanced around

export function layoutNodes(nodes: RFNode[], edges: Edge[]): RFNode[] {
  // preds[id] = nodes this one runs after (incoming edges).
  const preds: Record<string, string[]> = {};
  for (const n of nodes) preds[n.id] = [];
  for (const e of edges) if (preds[e.target]) preds[e.target].push(e.source);

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

  // Group by level (column); stack siblings vertically, centred on the midline.
  const byLevel: Record<number, RFNode[]> = {};
  for (const n of nodes) (byLevel[level[n.id]] ??= []).push(n);

  return nodes.map((n) => {
    const lv = level[n.id];
    const col = byLevel[lv];
    const idx = col.indexOf(n);
    // Centre this column's siblings around LAYOUT_MID.
    const y = LAYOUT_MID + (idx - (col.length - 1) / 2) * LAYOUT_Y;
    return {
      ...n,
      position: { x: LAYOUT_X0 + lv * LAYOUT_X, y },
    };
  });
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
