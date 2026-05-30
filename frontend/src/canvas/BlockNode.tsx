import { memo, useContext } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import type { BlockSpec } from "../blocks/types";
import { kindColor } from "./kindColors";
import { CTL_IN, CTL_OUT, dataHandleId } from "./handleId";
import { RunStateContext } from "../run/RunStateContext";

export interface BlockNodeData {
  spec: BlockSpec;
  label: string;
  params: Record<string, unknown>;
}

// Vertical position for the i-th port handle among n, as a CSS top %.
const slot = (i: number, n: number) => `${((i + 1) / (n + 1)) * 100}%`;

function BlockNodeImpl({ id, data, selected }: NodeProps<BlockNodeData>) {
  const { spec, label } = data;
  const runState = useContext(RunStateContext).get(id);
  return (
    <div
      className={`block-node${selected ? " selected" : ""}${
        runState ? ` run-${runState}` : ""
      }`}
    >
      {/* control flow (after-edges): top in, bottom out */}
      <Handle id={CTL_IN} type="target" position={Position.Top} className="ctl-handle" />
      <Handle id={CTL_OUT} type="source" position={Position.Bottom} className="ctl-handle" />

      <div className="block-title">{label || spec.label}</div>
      <div className="block-type">{spec.type}</div>

      {/* data inputs on the left */}
      {spec.inputs.map((p, i) => (
        <Handle
          key={`in-${p.name}`}
          id={dataHandleId("in", p.name, p.kind)}
          type="target"
          position={Position.Left}
          style={{ top: slot(i, spec.inputs.length), background: kindColor(p.kind) }}
          title={`${p.label}: ${p.kind}`}
        />
      ))}

      {/* data outputs on the right */}
      {spec.outputs.map((p, i) => (
        <Handle
          key={`out-${p.name}`}
          id={dataHandleId("out", p.name, p.kind)}
          type="source"
          position={Position.Right}
          style={{ top: slot(i, spec.outputs.length), background: kindColor(p.kind) }}
          title={`${p.label}: ${p.kind}`}
        />
      ))}
    </div>
  );
}

export const BlockNode = memo(BlockNodeImpl);
