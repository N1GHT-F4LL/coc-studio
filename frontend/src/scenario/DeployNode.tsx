import { memo } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import { thumbUrl } from "../api/client";
import type { DeployNode as DeployNodeT, DeployType } from "./types";

export interface DeployNodeData {
  node: DeployNodeT;
}

const TYPE_COLOR: Record<DeployType, string> = {
  troop: "#2b7de0",
  super_troop: "#1fa37a",
  spell: "#a64ce0",
  siege: "#e0a32b",
  hero: "#d4356b",
  delay: "#6b7280",
  surrender: "#b3402f",
  ensure_deployed: "#2f8fb3",
  pan: "#8a65d0",
};

function DeployNodeImpl({ data, selected }: NodeProps<DeployNodeData>) {
  const n = data.node;
  const color = TYPE_COLOR[n.type] ?? "#6b7280";
  const isDelay = n.type === "delay";
  const isSurrender = n.type === "surrender";
  const isEnsure = n.type === "ensure_deployed";
  const isPan = n.type === "pan";
  const noTemplate = isDelay || isSurrender || isEnsure || isPan; // control nodes — badge, not a thumb

  return (
    <div
      className={`deploy-node${selected ? " selected" : ""}`}
      style={{ borderColor: color }}
    >
      <Handle id="in" type="target" position={Position.Left} className="ctl-handle" />

      <div className="deploy-node-row">
        {!noTemplate && n.template ? (
          <img className="deploy-thumb" src={thumbUrl(n.template)} alt="" />
        ) : (
          <span className="deploy-badge" style={{ background: color }}>
            {isSurrender ? "⚑" : isEnsure ? "⇩" : isPan ? "⇄" : n.type[0].toUpperCase()}
          </span>
        )}
        <div className="deploy-node-text">
          <div className="deploy-node-title">{n.label || n.type}</div>
          <div className="deploy-node-sub">
            {isDelay
              ? `delay ${n.seconds ?? 0}s`
              : isSurrender
              ? "surrender → exit"
              : isEnsure
              ? "dump leftover troops"
              : isPan
              ? `pan (${n.x1 ?? "?"},${n.y1 ?? "?"})→(${n.x2 ?? "?"},${n.y2 ?? "?"})`
              : `${(n.template || "-").split("/").pop()} ×${n.taps ?? 0} · ${n.strategy ?? "line"}`}
          </div>
        </div>
      </div>

      <Handle id="out" type="source" position={Position.Right} className="ctl-handle" />
    </div>
  );
}

export const DeployNode = memo(DeployNodeImpl);
