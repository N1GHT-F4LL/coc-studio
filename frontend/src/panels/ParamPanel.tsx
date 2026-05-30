import type { Node } from "reactflow";
import type { PortSpec } from "../blocks/types";
import type { BlockNodeData } from "../canvas/BlockNode";
import { thumbUrl } from "../api/client";

interface Props {
  node: Node<BlockNodeData> | null;
  connectedInputs: Set<string>; // input ports fed by a data edge (literal is overridden)
  assets: string[];
  onChangeParam: (nodeId: string, name: string, value: unknown) => void;
  onChangeLabel: (nodeId: string, label: string) => void;
  onDelete: (nodeId: string) => void;
  onPick: (port: string, kind: "Coord" | "Region") => void;
}

// One form field per spec input. Data-edge inputs (M5) override these literals
// at run time; here we only edit literal params.
function Field({
  p,
  value,
  assets,
  onChange,
  onPick,
}: {
  p: PortSpec;
  value: unknown;
  assets: string[];
  onChange: (v: unknown) => void;
  onPick: (port: string, kind: "Coord" | "Region") => void;
}) {
  const id = `param-${p.name}`;
  if (p.kind === "Template") {
    return (
      <label className="field" htmlFor={id}>
        <span>{p.label}</span>
        <select id={id} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
          <option value="">— select asset —</option>
          {assets.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
        {value ? (
          <img className="tpl-thumb" src={thumbUrl(String(value))} alt={String(value)} />
        ) : null}
      </label>
    );
  }
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
        <div className="field-row">
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
          <button type="button" onClick={() => onPick(p.name, p.kind as "Coord" | "Region")}>
            Pick
          </button>
        </div>
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
  assets,
  onChangeParam,
  onChangeLabel,
  onDelete,
  onPick,
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
            assets={assets}
            onChange={(v) => onChangeParam(node.id, p.name, v)}
            onPick={onPick}
          />
        )
      )}

      <button className="danger" onClick={() => onDelete(node.id)}>
        Delete node
      </button>
    </aside>
  );
}
