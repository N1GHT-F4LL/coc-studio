import { DeviceCanvas } from "../device/DeviceCanvas";

export type PickMode = "points" | "line" | null;

interface Props {
  pickMode: PickMode;
  onPoint: (x: number, y: number) => void; // points mode: one tap
  onLine: (x1: number, y1: number, x2: number, y2: number) => void; // line mode: drag
  overlayPoints?: [number, number][];
  overlayLine?: [number, number, number, number] | null;
}

// Battlefield picker for the scenario editor — a thin wrapper over the shared
// DeviceCanvas that picks deploy coordinates (click = point, drag = line) with
// an overlay of the current node's points/line.
export function BattleCanvas({ pickMode, onPoint, onLine, overlayPoints, overlayLine }: Props) {
  return (
    <DeviceCanvas
      mode={pickMode ?? "none"}
      onPoint={onPoint}
      onLine={onLine}
      overlayPoints={overlayPoints}
      overlayLine={overlayLine}
      label="Battle view"
    />
  );
}
