import { memo } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import { thumbUrl } from "../api/client";
import type { DeployNode as DeployNodeT, DeployType } from "./types";

export interface DeployNodeData {
  node: DeployNodeT;
}

const TYPE_COLOR: Record<DeployType, string> = {
  troop: "#2b7de0",
  spell: "#a64ce0",
  siege: "#e0a32b",
  hero: "#d4356b",
  delay: "#6b7280",
};

function DeployNodeImpl({ data, selected }: NodeProps<DeployNodeData>) {
  const n = data.node;
  const color = TYPE_COLOR[n.type] ?? "#6b7280";
  const isDelay = n.type === "delay";

  return (
    <div
      className={`deploy-node${selected ? " selected" : ""}`}
      style={{ borderColor: color }}
    >
      <Handle id="in" type="target" position={Position.Left} className="ctl-handle" />

      <div className="deploy-node-row">
        {!isDelay && n.template ? (
          <img className="deploy-thumb" src={thumbUrl(n.template)} alt="" />
        ) : (
          <span className="deploy-badge" style={{ background: color }}>
            {n.type[0].toUpperCase()}
          </span>
        )}
        <div className="deploy-node-text">
          <div className="deploy-node-title">{n.label || n.type}</div>
          <div className="deploy-node-sub">
            {isDelay
              ? `delay ${n.seconds ?? 0}s`
              : `${(n.template || "—").split("/").pop()} ×${n.taps ?? 0} · ${n.strategy ?? "line"}`}
          </div>
        </div>
      </div>

      <Handle id="out" type="source" position={Position.Right} className="ctl-handle" />
    </div>
  );
}

export const DeployNode = memo(DeployNodeImpl);
