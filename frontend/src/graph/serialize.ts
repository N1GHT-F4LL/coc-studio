import type { Edge, Node } from "reactflow";
import type { BlockSpec, GraphDoc, GraphNode } from "../blocks/types";
import type { BlockNodeData } from "../canvas/BlockNode";
import { parseHandle, CTL_IN, CTL_OUT, dataHandleId } from "../canvas/handleId";

type RFNode = Node<BlockNodeData>;

// React Flow graph -> backend GraphDoc.
export function toGraphDoc(name: string, nodes: RFNode[], edges: Edge[]): GraphDoc {
  const out: Record<string, GraphNode> = {};
  for (const n of nodes) {
    out[n.id] = {
      id: n.id,
      type: n.data.spec.type,
      label: n.data.label ?? "",
      x: Math.round(n.position.x),
      y: Math.round(n.position.y),
      params: n.data.params ?? {},
      after: [],
      data_in: {},
      on_error: null,
    };
  }
  for (const e of edges) {
    const src = parseHandle(e.sourceHandle);
    const dst = parseHandle(e.targetHandle);
    const tgt = out[e.target];
    if (!tgt || !src || !dst) continue;
    if (src.flow === "control") {
      if (!tgt.after.includes(e.source)) tgt.after.push(e.source);
    } else if (dst.flow === "data") {
      tgt.data_in[dst.port] = { from: e.source, port: src.port };
    }
  }
  return { name, nodes: Object.values(out), meta: {} };
}

// backend GraphDoc -> React Flow graph (needs the block specs to rebuild handles).
export function fromGraphDoc(
  doc: GraphDoc,
  specByType: Map<string, BlockSpec>
): { nodes: RFNode[]; edges: Edge[] } {
  const nodes: RFNode[] = [];
  const edges: Edge[] = [];
  for (const gn of doc.nodes) {
    const spec = specByType.get(gn.type);
    if (!spec) continue; // unknown type — skip rather than crash the editor
    nodes.push({
      id: gn.id,
      type: "block",
      position: { x: gn.x, y: gn.y },
      data: { spec, label: gn.label, params: gn.params ?? {} },
    });
    for (const dep of gn.after ?? []) {
      edges.push({
        id: `ctl-${dep}-${gn.id}`,
        source: dep,
        target: gn.id,
        sourceHandle: CTL_OUT,
        targetHandle: CTL_IN,
      });
    }
    for (const [port, src] of Object.entries(gn.data_in ?? {})) {
      const from = specByType.get(doc.nodes.find((n) => n.id === src.from)?.type ?? "");
      const fromKind = from?.outputs.find((o) => o.name === src.port)?.kind;
      const toKind = spec.inputs.find((ip) => ip.name === port)?.kind;
      if (!fromKind || !toKind) continue;
      edges.push({
        id: `data-${src.from}.${src.port}-${gn.id}.${port}`,
        source: src.from,
        target: gn.id,
        sourceHandle: dataHandleId("out", src.port, fromKind),
        targetHandle: dataHandleId("in", port, toKind),
      });
    }
  }
  return { nodes, edges };
}
