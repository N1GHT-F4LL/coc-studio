import { useEffect, useRef, useState } from "react";
import { useDeviceStream } from "../device/DeviceStreamContext";

export type PickMode = "points" | "line" | null;

interface Props {
  pickMode: PickMode;
  onPoint: (x: number, y: number) => void; // points mode: one tap
  onLine: (x1: number, y1: number, x2: number, y2: number) => void; // line mode: drag
  overlayPoints?: [number, number][];
  overlayLine?: [number, number, number, number] | null;
}

// Live device view for the scenario editor: streams /ws/device onto a <canvas>
// and lets you pick deploy coordinates on the real battlefield — click to add a
// point (points strategy), drag to set a line (line strategy). Mirrors the
// streaming + coordinate-mapping logic of panels/DeviceView but specialised for
// deploy picking with an overlay of the current node's points/line.
export function BattleCanvas({
  pickMode,
  onPoint,
  onLine,
  overlayPoints,
  overlayLine,
}: Props) {
  const { connected, goToDevice, subscribe } = useDeviceStream();
  const [drag, setDrag] = useState<{ x1: number; y1: number; x2: number; y2: number } | null>(
    null
  );
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const dragStart = useRef<{ x: number; y: number } | null>(null);
  const lastFrame = useRef<ImageBitmap | null>(null);

  // Redraw the last frame + overlay (points/line + in-progress drag).
  const redraw = () => {
    const cv = canvasRef.current;
    const ctx = cv?.getContext("2d");
    if (!cv || !ctx) return;
    if (lastFrame.current) ctx.drawImage(lastFrame.current, 0, 0, cv.width, cv.height);
    ctx.lineWidth = 3;
    if (overlayLine) {
      const [x1, y1, x2, y2] = overlayLine;
      ctx.strokeStyle = "#2bd4a3";
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
    }
    for (const [px, py] of overlayPoints ?? []) {
      ctx.fillStyle = "#e0a32b";
      ctx.beginPath();
      ctx.arc(px, py, 7, 0, Math.PI * 2);
      ctx.fill();
    }
    if (drag) {
      ctx.strokeStyle = "#2b7de0";
      ctx.beginPath();
      ctx.moveTo(drag.x1, drag.y1);
      ctx.lineTo(drag.x2, drag.y2);
      ctx.stroke();
    }
  };

  // Draw frames from the shared device stream. The provider closes the bitmap
  // right after the callback, so clone it (createImageBitmap) to keep a copy for
  // overlay-only redraws between frames.
  useEffect(
    () =>
      subscribe((bmp) => {
        const cv = canvasRef.current;
        if (!cv) return;
        cv.width = bmp.width;
        cv.height = bmp.height;
        createImageBitmap(bmp).then((copy) => {
          lastFrame.current?.close();
          lastFrame.current = copy;
          redraw();
        });
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [subscribe]
  );

  // Redraw overlay when it changes (even between frames).
  useEffect(redraw, [overlayPoints, overlayLine, drag]);

  const toOrig = (e: React.MouseEvent) => {
    const cv = canvasRef.current!;
    const r = cv.getBoundingClientRect();
    return {
      ox: Math.round(((e.clientX - r.left) * cv.width) / r.width),
      oy: Math.round(((e.clientY - r.top) * cv.height) / r.height),
    };
  };

  const onDown = (e: React.MouseEvent) => {
    if (pickMode !== "line" || !canvasRef.current?.width) return;
    const { ox, oy } = toOrig(e);
    dragStart.current = { x: ox, y: oy };
    setDrag({ x1: ox, y1: oy, x2: ox, y2: oy });
  };
  const onMove = (e: React.MouseEvent) => {
    if (!dragStart.current) return;
    const { ox, oy } = toOrig(e);
    setDrag({ x1: dragStart.current.x, y1: dragStart.current.y, x2: ox, y2: oy });
  };
  const onUp = (e: React.MouseEvent) => {
    if (!canvasRef.current?.width) return;
    const { ox, oy } = toOrig(e);
    if (pickMode === "points") {
      onPoint(ox, oy);
    } else if (pickMode === "line" && dragStart.current) {
      const s = dragStart.current;
      dragStart.current = null;
      setDrag(null);
      onLine(s.x, s.y, ox, oy);
    }
  };

  return (
    <div className="battle-canvas">
      <div className="device-bar">
        <span>Battle view</span>
        <span className="muted device-info">
          {connected ? (pickMode ? `pick ${pickMode}…` : "streaming") : "chưa kết nối"}
        </span>
      </div>
      <div className={`device-stage${pickMode ? " picking" : ""}`}>
        <canvas
          ref={canvasRef}
          className="device-canvas"
          onMouseDown={onDown}
          onMouseMove={onMove}
          onMouseUp={onUp}
        />
        {!connected && (
          <div className="device-offline">
            <div className="muted">Chưa kết nối thiết bị.</div>
            <button onClick={goToDevice}>Mở tab Device</button>
          </div>
        )}
      </div>
    </div>
  );
}
