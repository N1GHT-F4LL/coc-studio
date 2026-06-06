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
// Modern callouts: pill labels arched over the node on the SAME side as the
// ports — inputs (top edge) bow upward, outputs (bottom edge) downward. Ports
// split left/right of centre; on each wing the box nearest the node centre sits
// closest in (rank 0), and ranks step out along a convex arc: an even vertical
// pitch (so boxes never overlap) with a horizontal offset that eases out (grows
// fast low, then flattens) and is capped, so the lower boxes splay toward their
// side while the upper boxes stand upright and hug — a canopy that wraps the
// node instead of shooting straight out to its flanks. The cluster auto-sizes
// to the port count. Each port joins its box with an elbow leader (diagonal
// rib, then a short horizontal segment); ribs only travel away from the edge,
// so they never cross the node body.
import type { PortSpec } from "../blocks/types";

const V0 = 50;     // vertical offset of the innermost box from the edge
const VS = 34;     // vertical pitch per rank outward (>= box height, no overlap)
const X0 = 56;     // horizontal offset of the innermost box from the node centre
const XSPAN = 96;  // max extra horizontal offset (capped so boxes stay off the flank)
const HSEG = 18;   // length of the horizontal leader segment into the box

// `dir = -1` floats the boxes above the node (top/input ports), `dir = +1`
// below (bottom/output ports). cx is the node centre x in node-local coords.
function CalloutFan({
  ports,
  cx,
  edgeY,
  dir,
}: {
  ports: PortSpec[];
  cx: number; // node centre x
  edgeY: number; // node-local y of the port row (0 = top edge, h = bottom edge)
  dir: -1 | 1;
}) {
  const items = ports.map((port, i) => ({ port, px: ((i + 1) / (ports.length + 1)) * (cx * 2) }));

  // A lone callout sits straight off the edge.
  if (items.length === 1) {
    return <Callout {...items[0]} py={edgeY} bx={cx} by={edgeY + dir * V0} sign={0} />;
  }

  // Rank each wing from the centre outward. Vertical pitch is even; the
  // horizontal offset eases out via sin() so the arc is convex (hugs at the top,
  // splays at the bottom) rather than a straight diagonal.
  const place = (arr: typeof items, sign: -1 | 1) => {
    const last = arr.length - 1;
    return arr.map(({ port, px }, rank) => {
      const t = last > 0 ? rank / last : 0; // 0 (innermost) .. 1 (outermost)
      return {
        port,
        px,
        sign,
        bx: cx + sign * (X0 + XSPAN * Math.sin((t * Math.PI) / 2)),
        by: edgeY + dir * (V0 + rank * VS),
      };
    });
  };
  const lefts = place(items.filter((it) => it.px < cx).sort((a, b) => b.px - a.px), -1);
  const rights = place(items.filter((it) => it.px >= cx).sort((a, b) => a.px - b.px), 1);

  return (
    <>
      {[...lefts, ...rights].map(({ port, px, bx, by, sign }) => (
        <Callout key={`${edgeY}-${port.name}`} port={port} py={edgeY} px={px} bx={bx} by={by} sign={sign} />
      ))}
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
      <CalloutFan ports={inputs} cx={w / 2} edgeY={0} dir={-1} />
      <CalloutFan ports={outputs} cx={w / 2} edgeY={h} dir={1} />
    </div>
  );
}

function Callout({
  port,
  px,
  py,
  bx,
  by,
  sign,
}: {
  port: PortSpec;
  px: number; // port dot x
  py: number; // port dot y (edge)
  bx: number; // box inner-edge x (node-facing side)
  by: number; // box centre y (off the edge)
  sign: -1 | 0 | 1; // which wing: -1 left, +1 right, 0 centred
}) {
  const color = kindColor(port.kind);
  // Elbow leader: diagonal rib out from the port to a knee, then a horizontal
  // segment into the box. `bx` is the box's inner edge (boxes are anchored by
  // the side facing the node centre, see .callout-left/.callout-right), so the
  // horizontal segment lands exactly on the box edge regardless of its width.
  const kneeX = sign === 0 ? bx : bx - sign * HSEG;
  const pts = `${px},${py} ${kneeX},${by} ${bx},${by}`;
  return (
    <>
      <svg className="callout-svg">
        <polyline points={pts} fill="none" stroke="var(--leader)" strokeWidth={1.25} opacity={0.7} strokeLinejoin="round" />
        <circle cx={px} cy={py} r={3.5} fill={color} stroke="var(--panel)" strokeWidth={1.5} />
      </svg>
      <div
        className={`callout-box${sign < 0 ? " callout-left" : sign > 0 ? " callout-right" : ""}`}
        style={{ left: bx, top: by, ["--kind" as string]: color }}
      >
        <span className="callout-name">{port.name}</span>
        <span className="callout-kind">{port.kind}</span>
      </div>
    </>
  );
}
