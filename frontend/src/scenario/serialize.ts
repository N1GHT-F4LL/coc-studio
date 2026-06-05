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
