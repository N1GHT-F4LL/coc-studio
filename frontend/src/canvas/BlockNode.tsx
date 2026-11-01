import { memo, useContext, useState } from "react";
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
// Data ports share the left/right edge with control flow, so keep them below
// the midpoint control handle instead of stacking on the top/bottom edge.
const dataSlot = (i: number, n: number) => `${50 + ((i + 1) / (n + 1)) * 42}%`;

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

  return (
    <div
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
            position={Position.Left}
            className="data-handle"
            style={{
              top: dataSlot(i, dataInputs.length),
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
            position={Position.Right}
            className="data-handle"
            style={{
              top: dataSlot(i, dataOutputs.length),
              background: kindColor(p.kind),
              display: dataHidden(hid) ? "none" : undefined,
            }}
            title={`${p.label}: ${p.kind}`}
          />
        );
      })}

      {/* Data ports reveal as side dots on hover/selection. */}
      {showData && (dataInputs.length > 0 || dataOutputs.length > 0) && (
        <PortCallouts w={160} h={64} inputs={dataInputs} outputs={dataOutputs} />
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
// Modern callouts: pill labels arranged as a half-ring (rainbow) over the node
// on the SAME side as the ports — inputs (top edge) above, outputs (bottom edge)
// below. Ports split left/right of centre; on each wing the boxes sit at EQUAL
// angular steps on a circular arc, so the box nearest the node centre rides the
// apex (farthest from the node, near the centreline) and each rank steps an even
// angle down-and-out toward the flank (lowest, closest to the node). Equal
// angles make the dome look uniform. The radius is sized to the port count so
// the apex pair clears vertically (no overlap) — the wider the fan, the larger
// the ring. Each port joins its box with an elbow leader (diagonal rib, then a
// short horizontal segment); ribs only travel away from the edge, so they never
// cross the node body.
import type { PortSpec } from "../blocks/types";

const A0 = 18;       // apex box angle (deg from vertical)
const A_MAX = 72;    // flank box max angle (deg from vertical; <90 so the lowest
                     // boxes lift off the edge instead of lying flat at 180°)
const BW = 54;       // representative box width, for even edge spacing
const BH = 22;       // representative box height
const GAP = 4;       // target edge gap between adjacent callouts (kept constant)
const R_ONE = 70;    // arc radius when a wing holds a single box
const SOLO_A = 42;   // angle for a wing's only box (chosen so a 1-per-side node
                     // sits up-and-out, not chevroned tight at the apex)
const R_CAP = 200;   // safety clamp on the computed radius (keeps leaders short)
const LONE_OFF = 64; // offset for a single callout sitting straight off the edge
const HSEG = 18;     // length of the horizontal leader segment into the box
const RAD = Math.PI / 180;

// Even-gap placement: walk the arc from the apex outward, advancing each step by
// the angle that keeps a CONSTANT edge gap between adjacent boxes. Because the
// boxes are wide pills, the gap-preserving angular step is large near the apex
// (boxes sit side-by-side, separated by their width) and small at the flank
// (boxes stack vertically, separated by their short height) — the rectangle's
// support length W·|cos a| + H·|sin a| projected on the arc tangent. The radius
// is solved (binary search) so those uneven angular steps span exactly A0..A_MAX
// for the given box count; equal angles would instead give uneven visual gaps.
function wingAngles(n: number): { angles: number[]; R: number } {
  if (n <= 1) return { angles: [SOLO_A * RAD], R: R_ONE };
  const stepDeg = (a: number, R: number) =>
    (BW * Math.abs(Math.cos(a * RAD)) + BH * Math.abs(Math.sin(a * RAD)) + GAP) / R / RAD;
  const span = (R: number) => {
    let a = A0;
    for (let k = 1; k < n; k++) a += stepDeg(a, R);
    return a; // final flank angle for this radius
  };
  // Larger R => smaller steps => smaller final angle, so span() is monotonic.
  let lo = 40, hi = 2000;
  for (let it = 0; it < 50; it++) {
    const mid = (lo + hi) / 2;
    if (span(mid) > A_MAX) lo = mid; else hi = mid;
  }
  const R = Math.min(R_CAP, hi);
  const angles = [A0];
  for (let k = 1; k < n; k++) angles.push(angles[k - 1] + stepDeg(angles[k - 1], R));
  return { angles: angles.map((d) => d * RAD), R };
}

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
    return <Callout {...items[0]} py={edgeY} bx={cx} by={edgeY + dir * LONE_OFF} sign={0} />;
  }

  // rank 0 = nearest the centre (apex); ranks step out to the flank.
  const place = (arr: typeof items, sign: -1 | 1) => {
    const { angles, R } = wingAngles(arr.length);
    return arr.map(({ port, px }, rank) => {
      const a = angles[rank];
      return { port, px, sign, bx: cx + sign * R * Math.sin(a), by: edgeY + dir * R * Math.cos(a) };
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
