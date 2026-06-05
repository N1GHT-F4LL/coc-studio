import type { Edge, Node } from "reactflow";
import type { BlockSpec, GraphDoc, GraphNode } from "../blocks/types";
import type { BlockNodeData } from "../canvas/BlockNode";
import { parseHandle, CTL_IN, CTL_OUT, ctlOutBranch, dataHandleId } from "../canvas/handleId";

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
      // Branch edge (if then/else) -> {from, branch}; plain ordering -> bare id.
      tgt.after.push(src.branch ? { from: e.source, branch: src.branch } : e.source);
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
      const from = typeof dep === "string" ? dep : (dep as any).from;
      const branch = typeof dep === "string" ? null : (dep as any).branch ?? null;
      edges.push({
        id: `ctl-${from}-${branch ?? ""}-${gn.id}`,
        source: from,
        target: gn.id,
        sourceHandle: branch ? ctlOutBranch(branch) : CTL_OUT,
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

// Auto-layout the block graph horizontally (suits a 16:9 screen): control flow
// runs left-to-right, so a node's level = longest control-edge chain from a root
// and becomes its column; siblings in a column stack vertically, centred on a
// midline. Data edges are ignored for levelling so the control spine stays
// straight.
const G_X = 260; // horizontal gap between levels (columns)
const G_Y = 130; // vertical gap between siblings in a column
const G_X0 = 80;
const G_MID = 300; // y midline each column is balanced around

export function layoutGraphNodes(nodes: RFNode[], edges: Edge[]): RFNode[] {
  // Control-edge predecessors only (handle ids start with "ctl").
  const preds: Record<string, string[]> = {};
  for (const n of nodes) preds[n.id] = [];
  for (const e of edges) {
    const isControl =
      (e.sourceHandle?.startsWith("ctl") ?? false) || (e.targetHandle?.startsWith("ctl") ?? false);
    if (isControl && preds[e.target]) preds[e.target].push(e.source);
  }

  const level: Record<string, number> = {};
  const visiting = new Set<string>();
  const levelOf = (id: string): number => {
    if (level[id] !== undefined) return level[id];
    if (visiting.has(id)) return 0; // cycle guard
    visiting.add(id);
    const ps = preds[id] ?? [];
    const lv = ps.length ? Math.max(...ps.map(levelOf)) + 1 : 0;
    visiting.delete(id);
    level[id] = lv;
    return lv;
  };
  for (const n of nodes) levelOf(n.id);

  const byLevel: Record<number, RFNode[]> = {};
  for (const n of nodes) (byLevel[level[n.id]] ??= []).push(n);

  return nodes.map((n) => {
    const lv = level[n.id];
    const col = byLevel[lv];
    const idx = col.indexOf(n);
    const y = G_MID + (idx - (col.length - 1) / 2) * G_Y;
    return { ...n, position: { x: G_X0 + lv * G_X, y } };
  });
}
