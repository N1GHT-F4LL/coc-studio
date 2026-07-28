import type { Connection, Edge } from "reactflow";
import { parseHandle } from "./handleId";

// Mirrors backend engine/graph.py:validate at edit time:
//  - control edges only connect control handles; adding one must not create a
//    control-flow cycle (graph stays a DAG).
//  - data edges only connect data handles of the SAME Kind.
//  - flows can't be mixed (control <-> data).

function controlAdjacency(edges: Edge[]): Map<string, string[]> {
  const adj = new Map<string, string[]>();
  for (const e of edges) {
    if (parseHandle(e.sourceHandle)?.flow !== "control") continue;
    if (!adj.has(e.source)) adj.set(e.source, []);
    adj.get(e.source)!.push(e.target);
  }
  return adj;
}

// Can we reach `target` from `start` following existing control edges?
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

/**
 * Returns a human-readable error message if the connection is invalid,
 * or null if it is valid.
 */
export function connectionError(c: Connection, edges: Edge[]): string | null {
  if (!c.source || !c.target) return "Incomplete connection.";
  if (c.source === c.target) return "Cannot connect a node to itself.";

  const src = parseHandle(c.sourceHandle);
  const dst = parseHandle(c.targetHandle);

  if (!src || !dst) return "Unknown handle type.";
  if (src.dir !== "out") return "Drag from an output (right-side) handle.";
  if (dst.dir !== "in") return "Drop onto an input (left-side) handle.";

  if (src.flow !== dst.flow) {
    return `Cannot mix ${src.flow} and ${dst.flow} handles — connect control→control or data→data.`;
  }

  if (src.flow === "data" && dst.flow === "data") {
    if (src.kind !== dst.kind) {
      return `Type mismatch: ${src.kind} → ${dst.kind}. Both ends must have the same port type.`;
    }
  }

  if (src.flow === "control") {
    const adj = controlAdjacency(edges);
    if (reaches(c.target, c.source, adj)) {
      return "This connection would create a cycle. Graphs must be acyclic (use loop blocks for repetition).";
    }
  }

  return null;
}

export function validateConnection(c: Connection, edges: Edge[]): boolean {
  return connectionError(c, edges) === null;
}
