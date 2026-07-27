import type { Node } from "reactflow";
import type { PortSpec } from "../blocks/types";
import type { BlockNodeData } from "../canvas/BlockNode";
import { thumbUrl } from "../api/client";

interface Props {
  node: Node<BlockNodeData> | null;
  connectedInputs: Set<string>; // input ports fed by a data edge (literal is overridden)
  assets: string[];
  graphs: string[];
  scenarios: string[];
  onChangeParam: (nodeId: string, name: string, value: unknown) => void;
  onChangeLabel: (nodeId: string, label: string) => void;
  onDelete: (nodeId: string) => void;
}

// Dropdown of dynamic values (saved graphs / scenarios) for params with a source.
function SourceSelect({
  id,
  value,
  options,
  onChange,
}: {
  id: string;
  value: unknown;
  options: string[];
  onChange: (v: unknown) => void;
}) {
  return (
    <select id={id} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
      <option value="">- select -</option>
      {options.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
      {/* keep a stale saved value visible even if it's no longer in the list */}
      {value && !options.includes(String(value)) ? (
        <option value={String(value)}>{String(value)} (?)</option>
      ) : null}
    </select>
  );
}

// One form field per spec input. Data-edge inputs (M5) override these literals
// at run time; here we only edit literal params.
function Field({
  p,
  value,
  assets,
  graphs,
  scenarios,
  onChange,
}: {
  p: PortSpec;
  value: unknown;
  assets: string[];
  graphs: string[];
  scenarios: string[];
  onChange: (v: unknown) => void;
}) {
  const id = `param-${p.name}`;
  // Dynamic dropdown (pick a saved graph / scenario) instead of typing a name.
  if (p.source === "graphs" || p.source === "scenarios") {
    const opts = p.source === "graphs" ? graphs : scenarios;
    return (
      <label className="field" htmlFor={id}>
        <span>{p.label}</span>
        <SourceSelect id={id} value={value} options={opts} onChange={onChange} />
      </label>
    );
  }
  if (p.choices && p.choices.length) {
    return (
      <label className="field" htmlFor={id}>
        <span>{p.label}</span>
        <select id={id} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
          {p.choices.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </label>
    );
  }
  if (p.kind === "Template") {
    return (
      <label className="field" htmlFor={id}>
        <span>{p.label}</span>
        <select id={id} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
          <option value="">- select asset -</option>
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
  assets,
  graphs,
  scenarios,
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
      {spec.description ? <p className="block-desc">{spec.description}</p> : null}
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
            graphs={graphs}
            scenarios={scenarios}
            onChange={(v) => onChangeParam(node.id, p.name, v)}
          />
        )
      )}

      {/* Deploy-specific UI: drop_style, multi_targets, spline tuning */}
      {spec.category === "CoC" ? (
        <div className="deploy-options">
          <h3>Deploy Options</h3>
          <label className="field" htmlFor="drop-style">
            <span>Drop style</span>
            <select
              id="drop-style"
              value={String(params["drop_style"] ?? "")}
              onChange={(e) => onChangeParam(node.id, "drop_style", e.target.value || null)}
            >
              <option value="">- default -</option>
              <option value="drag">drag (single-finger)</option>
              <option value="spline">spline (curved path)</option>
            </select>
          </label>

          <label className="field" htmlFor="multi-targets">
            <span>Multi targets</span>
            <input
              id="multi-targets"
              type="text"
              placeholder="x1,y1; x2,y2; ..."
              value={Array.isArray(params["multi_targets"]) ? (params["multi_targets"] as any[])
                .map((p) => Array.isArray(p) ? `${p[0]},${p[1]}` : String(p)).join("; ") : String(params["multi_targets"] ?? "")}
              onChange={(e) => {
                const v = e.target.value.trim();
                if (!v) return onChangeParam(node.id, "multi_targets", null);
                const parts = v.split(";").map((s) => s.trim()).filter(Boolean);
                const pts: number[][] = [];
                let ok = true;
                for (const p of parts) {
                  const nums = p.split(",").map((s) => Number(s.trim()));
                  if (nums.length !== 2 || nums.some(Number.isNaN)) {
                    ok = false;
                    break;
                  }
                  pts.push([Math.round(nums[0]), Math.round(nums[1])]);
                }
                if (ok) onChangeParam(node.id, "multi_targets", pts);
                else onChangeParam(node.id, "multi_targets", v); // keep raw for visibility
              }}
            />
          </label>

          <label className="field" htmlFor="spline-min-steps">
            <span>Spline min steps</span>
            <input
              id="spline-min-steps"
              type="number"
              value={String(params["spline_min_steps"] ?? "")}
              onChange={(e) => onChangeParam(node.id, "spline_min_steps", e.target.value === "" ? null : Number(e.target.value))}
            />
          </label>
          <label className="field" htmlFor="spline-max-steps">
            <span>Spline max steps</span>
            <input
              id="spline-max-steps"
              type="number"
              value={String(params["spline_max_steps"] ?? "")}
              onChange={(e) => onChangeParam(node.id, "spline_max_steps", e.target.value === "" ? null : Number(e.target.value))}
            />
          </label>
          <label className="field" htmlFor="spline-px-per-step">
            <span>Spline px / step</span>
            <input
              id="spline-px-per-step"
              type="number"
              value={String(params["spline_px_per_step"] ?? "")}
              onChange={(e) => onChangeParam(node.id, "spline_px_per_step", e.target.value === "" ? null : Number(e.target.value))}
            />
          </label>
        </div>
      ) : null}

      <button className="danger" onClick={() => onDelete(node.id)}>
        Delete node
      </button>
    </aside>
  );
}
