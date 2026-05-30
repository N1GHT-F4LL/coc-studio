import type { Node } from "reactflow";
import type { PortSpec } from "../blocks/types";
import type { BlockNodeData } from "../canvas/BlockNode";

interface Props {
  node: Node<BlockNodeData> | null;
  connectedInputs: Set<string>; // input ports fed by a data edge (literal is overridden)
  onChangeParam: (nodeId: string, name: string, value: unknown) => void;
  onChangeLabel: (nodeId: string, label: string) => void;
  onDelete: (nodeId: string) => void;
}

// One form field per spec input. Data-edge inputs (M5) override these literals
// at run time; here we only edit literal params.
function Field({
  p,
  value,
  onChange,
}: {
  p: PortSpec;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const id = `param-${p.name}`;
  if (p.kind === "Bool") {
    return (
      <label className="field" htmlFor={id}>
        <span>{p.label}</span>
        <input
          id={id}
          type="checkbox"
          checked={Boolean(value)}
          onChange={(e) => onChange(e.target.checked)}
        />
      </label>
    );
  }
  if (p.kind === "Number") {
    return (
      <label className="field" htmlFor={id}>
        <span>{p.label}</span>
        <input
          id={id}
          type="number"
          value={value === undefined || value === null ? "" : String(value)}
          onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        />
      </label>
    );
  }
  if (p.kind === "Coord" || p.kind === "Region") {
    // Comma-separated ints; Coord=2, Region=4.
    const text = Array.isArray(value) ? value.join(", ") : "";
    return (
      <label className="field" htmlFor={id}>
        <span>
          {p.label} <em className="muted">({p.kind === "Coord" ? "x, y" : "x1, y1, x2, y2"})</em>
        </span>
        <input
          id={id}
          type="text"
          value={text}
          placeholder={p.kind === "Coord" ? "100, 200" : "0, 70, 420, 360"}
          onChange={(e) => {
            const nums = e.target.value
              .split(",")
              .map((s) => s.trim())
              .filter((s) => s !== "")
              .map(Number);
            onChange(nums.some(Number.isNaN) ? e.target.value : nums);
          }}
        />
      </label>
    );
  }
  // Template / Text / Trigger fall back to text.
  return (
    <label className="field" htmlFor={id}>
      <span>{p.label}</span>
      <input
        id={id}
        type="text"
        value={value === undefined || value === null ? "" : String(value)}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

export function ParamPanel({
  node,
  connectedInputs,
  onChangeParam,
  onChangeLabel,
  onDelete,
}: Props) {
  if (!node) {
    return (
      <aside className="param-panel">
        <h2>Parameters</h2>
        <div className="muted">Select a node to edit its parameters.</div>
      </aside>
    );
  }
  const { spec, params, label } = node.data;
  return (
    <aside className="param-panel">
      <h2>{spec.label}</h2>
      <div className="param-meta">
        <span className="muted">type</span> {spec.type}
        <br />
        <span className="muted">id</span> {node.id}
      </div>

      <label className="field" htmlFor="node-label">
        <span>Label</span>
        <input
          id="node-label"
          type="text"
          value={label}
          onChange={(e) => onChangeLabel(node.id, e.target.value)}
        />
      </label>

      {spec.inputs.length === 0 && <div className="muted">No parameters.</div>}
      {spec.inputs.map((p) =>
        connectedInputs.has(p.name) ? (
          <label key={p.name} className="field">
            <span>{p.label}</span>
            <input type="text" value="← from data edge" disabled />
          </label>
        ) : (
          <Field
            key={p.name}
            p={p}
            value={params[p.name] ?? p.default}
            onChange={(v) => onChangeParam(node.id, p.name, v)}
          />
        )
      )}

      <button className="danger" onClick={() => onDelete(node.id)}>
        Delete node
      </button>
    </aside>
  );
}
