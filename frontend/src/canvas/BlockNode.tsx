import { memo, useContext, useLayoutEffect, useRef, useState } from "react";
import { Handle, Position, useStore, type NodeProps } from "reactflow";
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
  const [hovered, setHovered] = useState(false);

  // Trigger-kind ports are control flow; everything else is a typed data port.
  const dataInputs = spec.inputs.filter((p) => p.kind !== "Trigger");
  const dataOutputs = spec.outputs.filter((p) => p.kind !== "Trigger");
  const branches = spec.outputs.filter((p) => p.kind === "Trigger");

  // Data ports are advanced (most graphs just set literals in the panel), so
  // keep them hidden to reduce clutter — reveal them on hover, when the node is
  // selected, or for any port that actually has an edge connected.
  const connectedHandles = useStore((s) => {
    const ids = new Set<string>();
    for (const e of s.edges) {
      if (e.source === id && e.sourceHandle) ids.add(e.sourceHandle);
      if (e.target === id && e.targetHandle) ids.add(e.targetHandle);
    }
    return ids;
  });
  const showData = hovered || selected;
  const dataHidden = (hid: string) => !showData && !connectedHandles.has(hid);

  // Measure the node box so the callout leaders can be drawn to scale.
  const boxRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 160, h: 64 });
  useLayoutEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      setSize({ w: el.offsetWidth, h: el.offsetHeight });
    });
    ro.observe(el);
    setSize({ w: el.offsetWidth, h: el.offsetHeight });
    return () => ro.disconnect();
  }, []);

  return (
    <div
      ref={boxRef}
      className={`block-node${selected ? " selected" : ""}${
        runState ? ` run-${runState}` : ""
      }`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* control flow in (left) — the graph flows left-to-right */}
      <Handle id={CTL_IN} type="target" position={Position.Left} className="ctl-handle" />

      <div className="block-title">{label || spec.label}</div>
      <div className="block-type">{spec.type}</div>

      {/* data input/output handle dots; the field name lives in the callout. */}
      {dataInputs.map((p, i) => {
        const hid = dataHandleId("in", p.name, p.kind);
        return (
          <Handle
            key={`in-${p.name}`}
            id={hid}
            type="target"
            position={Position.Top}
            className="data-handle"
            style={{
              left: hslot(i, dataInputs.length),
              background: kindColor(p.kind),
              display: dataHidden(hid) ? "none" : undefined,
            }}
            title={`${p.label}: ${p.kind}`}
          />
        );
      })}
      {dataOutputs.map((p, i) => {
        const hid = dataHandleId("out", p.name, p.kind);
        return (
          <Handle
            key={`out-${p.name}`}
            id={hid}
            type="source"
            position={Position.Bottom}
            className="data-handle"
            style={{
              left: hslot(i, dataOutputs.length),
              background: kindColor(p.kind),
              display: dataHidden(hid) ? "none" : undefined,
            }}
            title={`${p.label}: ${p.kind}`}
          />
        );
      })}

      {/* Callout layer: on hover, input-port labels float above the node and
          output-port labels below, each with an elbow leader to its port dot. */}
      {showData && (dataInputs.length > 0 || dataOutputs.length > 0) && (
        <PortCallouts w={size.w} h={size.h} inputs={dataInputs} outputs={dataOutputs} />
      )}


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

// --- port callouts ---------------------------------------------------------
// Label boxes float off the edge the port lives on: input ports (top edge) get
// callouts stacked ABOVE the node, output ports (bottom edge) get callouts
// BELOW. Each box has an elbow leader (square marker at the box, dot at the
// port) — like a video lower-third.
import type { PortSpec } from "../blocks/types";

const BOX_GAP = 30;   // vertical distance from node edge to the box row
const BOX_H = 24;     // box height
const BOX_VGAP = 6;   // vertical gap between stacked boxes in the same row

// Render one row of callouts off a single edge. `dir = -1` floats the boxes
// above the node (for top/input ports), `dir = +1` below (bottom/output).
function CalloutRow({
  ports,
  w,
  edgeY,
  dir,
}: {
  ports: PortSpec[];
  w: number;
  edgeY: number; // node-local y of the port row (0 = top edge, h = bottom edge)
  dir: -1 | 1;
}) {
  return (
    <>
      {ports.map((port, i) => {
        const px = ((i + 1) / (ports.length + 1)) * w;
        // Stagger stacked boxes outward so neighbours don't overlap.
        const by = edgeY + dir * (BOX_GAP + i * (BOX_H + BOX_VGAP));
        return (
          <Callout key={`${edgeY}-${port.name}`} port={port} px={px} py={edgeY} bx={px} by={by} />
        );
      })}
    </>
  );
}

function PortCallouts({
  w,
  h,
  inputs,
  outputs,
}: {
  w: number;
  h: number;
  inputs: PortSpec[];
  outputs: PortSpec[];
}) {
  return (
    <div className="port-callouts">
      <CalloutRow ports={inputs} w={w} edgeY={0} dir={-1} />
      <CalloutRow ports={outputs} w={w} edgeY={h} dir={1} />
    </div>
  );
}

function Callout({
  port,
  px,
  py,
  bx,
  by,
}: {
  port: PortSpec;
  px: number; // port dot x
  py: number; // port dot y (edge)
  bx: number; // box centre x
  by: number; // box centre y (off the edge)
}) {
  const color = kindColor(port.kind);
  // Straight leader from the box marker down/up to the port dot.
  const pts = `${bx},${by} ${px},${py}`;
  return (
    <>
      <svg className="callout-svg">
        <polyline points={pts} fill="none" stroke="var(--border)" strokeWidth={1} />
        <rect x={bx - 3} y={by - 3} width={6} height={6} fill={color} />
        <circle cx={px} cy={py} r={3} fill={color} />
      </svg>
      <div className="callout-box" style={{ left: bx, top: by }}>
        <span className="callout-name">{port.name}</span>
        <span className="callout-kind">{port.kind}</span>
      </div>
    </>
  );
}
