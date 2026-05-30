// Mirrors backend engine/registry.py serialization (GET /api/blocks).

export type Kind =
  | "Coord"
  | "Number"
  | "Template"
  | "Region"
  | "Bool"
  | "Text"
  | "Trigger";

export interface PortSpec {
  name: string;
  kind: Kind;
  label: string;
  default?: unknown;
}

export interface BlockSpec {
  type: string;
  label: string;
  category: string;
  inputs: PortSpec[];
  outputs: PortSpec[];
}

// Backend graph JSON shape (engine/graph.py).
export interface GraphNode {
  id: string;
  type: string;
  label: string;
  x: number;
  y: number;
  params: Record<string, unknown>;
  after: string[];
  data_in: Record<string, { from: string; port: string }>;
  on_error: string | null;
}

export interface GraphDoc {
  name: string;
  nodes: GraphNode[];
  meta: Record<string, unknown>;
}
