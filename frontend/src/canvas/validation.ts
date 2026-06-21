import type { Connection, Edge } from "reactflow";
import { parseHandle } from "./handleId";

// Mirrors backend engine/graph.py:validate at edit time:
//  - control edges only connect control handles.
//  - data edges only connect data handles of the SAME Kind.
//  - flows can't be mixed (control <-> data).
//  - control + data edges together must stay a DAG.

function dependencyAdjacency(edges: Edge[]): Map<string, string[]> {
  const adj = new Map<string, string[]>();
  for (const e of edges) {
    if (!parseHandle(e.sourceHandle) || !parseHandle(e.targetHandle)) continue;
    if (!adj.has(e.source)) adj.set(e.source, []);
    adj.get(e.source)!.push(e.target);
  }
  return adj;
}

// Can we reach `target` from `start` following existing dependency edges?
function reaches(start: string, target: string, adj: Map<string, string[]>): boolean {
  const seen = new Set<string>();
  const stack = [start];
  while (stack.length) {
    const cur = stack.pop()!;
    if (cur === target) return true;
    if (seen.has(cur)) continue;
    seen.add(cur);
    for (const nxt of adj.get(cur) ?? []) stack.push(nxt);
  }
  return false;
}

export function validateConnection(c: Connection, edges: Edge[]): boolean {
  if (!c.source || !c.target || c.source === c.target) return false;
  const src = parseHandle(c.sourceHandle);
  const dst = parseHandle(c.targetHandle);
  if (!src || !dst) return false;
  if (src.dir !== "out" || dst.dir !== "in") return false;
  if (src.flow !== dst.flow) return false;

  if (src.flow === "data") {
    if (dst.flow !== "data") return false;
    if (src.kind !== dst.kind) return false;
  }

  // Adding source->target must not close a runtime dependency cycle, i.e.
  // target must not already reach source through control or data edges.
  const adj = dependencyAdjacency(edges);
  return !reaches(c.target, c.source, adj);
}
