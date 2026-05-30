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
      {/* control flow in (top) */}
      <Handle id={CTL_IN} type="target" position={Position.Top} className="ctl-handle" />

      <div className="block-title">{label || spec.label}</div>
      <div className="block-type">{spec.type}</div>

      {/* data inputs on the left */}
      {dataInputs.map((p, i) => (
        <Handle
          key={`in-${p.name}`}
          id={dataHandleId("in", p.name, p.kind)}
          type="target"
          position={Position.Left}
          style={{ top: slot(i, dataInputs.length), background: kindColor(p.kind) }}
          title={`${p.label}: ${p.kind}`}
        />
      ))}

      {/* data outputs on the right */}
      {dataOutputs.map((p, i) => (
        <Handle
          key={`out-${p.name}`}
          id={dataHandleId("out", p.name, p.kind)}
          type="source"
          position={Position.Right}
          style={{ top: slot(i, dataOutputs.length), background: kindColor(p.kind) }}
          title={`${p.label}: ${p.kind}`}
        />
      ))}

      {/* control flow out (bottom): branch handles for Trigger outputs, else default */}
      {branches.length === 0 ? (
        <Handle id={CTL_OUT} type="source" position={Position.Bottom} className="ctl-handle" />
      ) : (
        branches.map((p, i) => (
          <div
            key={`br-${p.name}`}
            className="branch-label"
            style={{ left: hslot(i, branches.length) }}
          >
            {p.name}
            <Handle
              id={ctlOutBranch(p.name)}
              type="source"
              position={Position.Bottom}
              className="ctl-handle"
              style={{ left: "50%" }}
              title={`branch: ${p.name}`}
            />
          </div>
        ))
      )}
    </div>
  );
}

export const BlockNode = memo(BlockNodeImpl);
