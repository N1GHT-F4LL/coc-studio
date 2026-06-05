import { memo, useContext } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import type { BlockSpec } from "../blocks/types";
import { kindColor } from "./kindColors";
import { CTL_IN, CTL_OUT, ctlOutBranch, dataHandleId } from "./handleId";
import { RunStateContext } from "../run/RunStateContext";

export interface BlockNodeData {
  spec: BlockSpec;
  label: string;
  params: Record<string, unknown>;
}

// Vertical position for the i-th port handle among n, as a CSS top %.
const slot = (i: number, n: number) => `${((i + 1) / (n + 1)) * 100}%`;
// Horizontal position for the i-th branch handle among n, as a CSS left %.
const hslot = (i: number, n: number) => `${((i + 1) / (n + 1)) * 100}%`;

function BlockNodeImpl({ id, data, selected }: NodeProps<BlockNodeData>) {
  const { spec, label } = data;
  const runState = useContext(RunStateContext).get(id);

  // Trigger-kind ports are control flow; everything else is a typed data port.
  const dataInputs = spec.inputs.filter((p) => p.kind !== "Trigger");
  const dataOutputs = spec.outputs.filter((p) => p.kind !== "Trigger");
  const branches = spec.outputs.filter((p) => p.kind === "Trigger");

  return (
    <div
      className={`block-node${selected ? " selected" : ""}${
        runState ? ` run-${runState}` : ""
      }`}
    >
      {/* control flow in (left) — the graph flows left-to-right */}
      <Handle id={CTL_IN} type="target" position={Position.Left} className="ctl-handle" />

      <div className="block-title">{label || spec.label}</div>
      <div className="block-type">{spec.type}</div>

      {/* data inputs along the top */}
      {dataInputs.map((p, i) => (
        <Handle
          key={`in-${p.name}`}
          id={dataHandleId("in", p.name, p.kind)}
          type="target"
          position={Position.Top}
          style={{ left: hslot(i, dataInputs.length), background: kindColor(p.kind) }}
          title={`${p.label}: ${p.kind}`}
        />
      ))}

      {/* data outputs along the bottom */}
      {dataOutputs.map((p, i) => (
        <Handle
          key={`out-${p.name}`}
          id={dataHandleId("out", p.name, p.kind)}
          type="source"
          position={Position.Bottom}
          style={{ left: hslot(i, dataOutputs.length), background: kindColor(p.kind) }}
          title={`${p.label}: ${p.kind}`}
        />
      ))}

      {/* control flow out (right): branch handles for Trigger outputs, else default */}
      {branches.length === 0 ? (
        <Handle id={CTL_OUT} type="source" position={Position.Right} className="ctl-handle" />
      ) : (
        branches.map((p, i) => (
          <div
            key={`br-${p.name}`}
            className="branch-label-v"
            style={{ top: slot(i, branches.length) }}
          >
            {p.name}
            <Handle
              id={ctlOutBranch(p.name)}
              type="source"
              position={Position.Right}
              className="ctl-handle"
              style={{ top: "50%" }}
              title={`branch: ${p.name}`}
            />
          </div>
        ))
      )}
    </div>
  );
}

export const BlockNode = memo(BlockNodeImpl);
