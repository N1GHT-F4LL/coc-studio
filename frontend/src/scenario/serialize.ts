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

// Auto-layout: assign each node a level = longest dependency chain from a root
// (via after-edges), lay levels out top-to-bottom and siblings left-to-right so
// branches (several nodes sharing an `after`) fan out instead of overlapping.
const LAYOUT_X = 200; // horizontal gap between siblings
const LAYOUT_Y = 110; // vertical gap between levels
const LAYOUT_X0 = 80;
const LAYOUT_Y0 = 40;

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

  // Group by level, keep a stable order, spread siblings horizontally centred.
  const byLevel: Record<number, RFNode[]> = {};
  for (const n of nodes) (byLevel[level[n.id]] ??= []).push(n);
  const maxRowWidth = Math.max(1, ...Object.values(byLevel).map((r) => r.length));

  return nodes.map((n) => {
    const lv = level[n.id];
    const row = byLevel[lv];
    const idx = row.indexOf(n);
    // Centre each row against the widest row.
    const offset = (maxRowWidth - row.length) / 2;
    return {
      ...n,
      position: {
        x: LAYOUT_X0 + (idx + offset) * LAYOUT_X,
        y: LAYOUT_Y0 + lv * LAYOUT_Y,
      },
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
