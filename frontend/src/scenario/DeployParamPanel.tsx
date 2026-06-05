import { thumbUrl } from "../api/client";
import {
  DEPLOY_TYPES,
  TYPE_FOLDER,
  type DeployNode as DeployNodeT,
  type DeployType,
  type Strategy,
} from "./types";

interface Props {
  node: DeployNodeT | null;
  assets: string[];
  onChange: (id: string, patch: Partial<DeployNodeT>) => void;
  onDelete: (id: string) => void;
  // Phase C wires these to the battle-canvas picker; optional until then.
  onPickPoints?: (id: string) => void;
  onPickLine?: (id: string) => void;
}

export function DeployParamPanel({
  node,
  assets,
  onChange,
  onDelete,
  onPickPoints,
  onPickLine,
}: Props) {
  if (!node) {
    return (
      <aside className="param-panel">
        <h2>Deploy unit</h2>
        <div className="muted">Select a unit to edit it, or “+ Unit” to add one.</div>
      </aside>
    );
  }

  const isDelay = node.type === "delay";
  const set = (patch: Partial<DeployNodeT>) => onChange(node.id, patch);

  // Templates relevant to this unit type (e.g. units/troops/* for a troop).
  const folder = isDelay ? null : TYPE_FOLDER[node.type as Exclude<DeployType, "delay">];
  const typeAssets = folder ? assets.filter((a) => a.startsWith(folder + "/")) : [];

  return (
    <aside className="param-panel">
      <h2>Deploy unit</h2>
      <div className="param-meta">
        <span className="muted">id</span> {node.id}
      </div>

      <label className="field">
        <span>Label</span>
        <input value={node.label} onChange={(e) => set({ label: e.target.value })} />
      </label>

      <label className="field">
        <span>Type</span>
        <select
          value={node.type}
          onChange={(e) => {
            const t = e.target.value as DeployType;
            // Switching to/from delay flips the relevant fields.
            set(
              t === "delay"
                ? { type: t, strategy: "delay", seconds: node.seconds ?? 1 }
                : { type: t, strategy: node.strategy === "delay" ? "line" : node.strategy }
            );
          }}
        >
          {DEPLOY_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </label>

      {isDelay ? (
        <label className="field">
          <span>Seconds</span>
          <input
            type="number"
            min={0}
            value={node.seconds ?? 0}
            onChange={(e) => set({ seconds: Number(e.target.value) || 0 })}
          />
        </label>
      ) : (
        <>
          <label className="field">
            <span>Template</span>
            <select
              value={node.template ?? ""}
              onChange={(e) => set({ template: e.target.value })}
            >
              <option value="">— select unit —</option>
              {typeAssets.map((a) => (
                <option key={a} value={a}>
                  {a.split("/").pop()}
                </option>
              ))}
              {node.template && !typeAssets.includes(node.template) ? (
                <option value={node.template}>{node.template} (?)</option>
              ) : null}
            </select>
            {node.template ? (
              <img className="tpl-thumb" src={thumbUrl(node.template)} alt={node.template} />
            ) : null}
          </label>

          <label className="field">
            <span>
              Taps <em className="muted">(count to train / drop)</em>
            </span>
            <input
              type="number"
              min={0}
              value={node.taps ?? 0}
              onChange={(e) => set({ taps: Number(e.target.value) || 0 })}
            />
          </label>

          <label className="field">
            <span>Strategy</span>
            <select
              value={node.strategy ?? "line"}
              onChange={(e) => set({ strategy: e.target.value as Strategy })}
            >
              <option value="line">line (spread along a line)</option>
              <option value="points">points (tap fixed spots)</option>
            </select>
          </label>

          {node.strategy === "points" ? (
            <label className="field">
              <span>
                Points <em className="muted">(x,y per line)</em>
              </span>
              <textarea
                className="points-area"
                value={(node.points ?? []).map((p) => `${p[0]}, ${p[1]}`).join("\n")}
                placeholder={"142, 428\n200, 410"}
                onChange={(e) => {
                  const pts = e.target.value
                    .split("\n")
                    .map((ln) => ln.split(",").map((s) => Number(s.trim())))
                    .filter((a) => a.length === 2 && a.every((n) => !Number.isNaN(n))) as [
                    number,
                    number
                  ][];
                  set({ points: pts });
                }}
              />
              {onPickPoints ? (
                <button type="button" onClick={() => onPickPoints(node.id)}>
                  Pick points on device
                </button>
              ) : null}
            </label>
          ) : (
            <label className="field">
              <span>
                Line <em className="muted">(x1, y1, x2, y2)</em>
              </span>
              <div className="field-row">
                <input
                  type="text"
                  value={[node.x1, node.y1, node.x2, node.y2]
                    .map((v) => (v === undefined ? "" : v))
                    .join(", ")}
                  placeholder="1213, 267, 1015, 120"
                  onChange={(e) => {
                    const n = e.target.value
                      .split(",")
                      .map((s) => Number(s.trim()));
                    if (n.length === 4 && n.every((v) => !Number.isNaN(v))) {
                      set({ x1: n[0], y1: n[1], x2: n[2], y2: n[3] });
                    }
                  }}
                />
                {onPickLine ? (
                  <button type="button" onClick={() => onPickLine(node.id)}>
                    Pick
                  </button>
                ) : null}
              </div>
            </label>
          )}
        </>
      )}

      <button className="danger" onClick={() => onDelete(node.id)}>
        Delete unit
      </button>
    </aside>
  );
}
