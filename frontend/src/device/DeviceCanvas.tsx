import { useEffect, useRef, useState } from "react";
import { useDeviceStream } from "./DeviceStreamContext";

// One pick/crop surface shared by the scenario editor and the asset manager.
// Streams /ws/device onto a <canvas> and maps pointer events to original device
// coordinates. The interaction depends on `mode`:
//   coord  — click → onCoord(x, y)
//   points — click → onPoint(x, y)              (+ overlayPoints)
//   line   — drag  → onLine(x1, y1, x2, y2)     (+ overlayLine)
//   region — drag  → onRegion([x1, y1, x2, y2])
//   crop   — drag  → onCrop([x1, y1, x2, y2])   (ignored if < 2px)
//   none   — view only
export type PickMode = "none" | "coord" | "region" | "points" | "line" | "crop";

interface Props {
  mode: PickMode;
  onCoord?: (x: number, y: number) => void;
  onRegion?: (region: number[]) => void;
  onPoint?: (x: number, y: number) => void;
  onLine?: (x1: number, y1: number, x2: number, y2: number) => void;
  // crop mode: region in device px + a data-URL preview cut from the live frame.
  onCrop?: (region: number[], preview: string) => void;
  overlayPoints?: [number, number][];
  overlayLine?: [number, number, number, number] | null;
  // A locked-in region (device px) to keep outlined after the drag ends.
  committedRegion?: number[] | null;
  label?: string; // bar title (left)
  info?: string; // bar text (right); defaults to a pick/stream hint
}

const DRAG_MODES = new Set<PickMode>(["region", "line", "crop"]);

export function DeviceCanvas({
  mode,
  onCoord,
  onRegion,
  onPoint,
  onLine,
  onCrop,
  overlayPoints,
  overlayLine,
  committedRegion,
  label = "Device",
  info,
}: Props) {
  const { connected, goToDevice, subscribe } = useDeviceStream();
  // In-progress drag, in original device coords.
  const [drag, setDrag] = useState<{ x1: number; y1: number; x2: number; y2: number } | null>(
    null
  );
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const dragStart = useRef<{ x: number; y: number } | null>(null);
  const lastFrame = useRef<ImageBitmap | null>(null);

  const picking = mode !== "none";

  // Redraw the last frame + overlays (scenario points/line + in-progress drag).
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
    // Locked-in crop region (kept outlined after the drag ends).
    if (committedRegion && committedRegion.length === 4 && !drag) {
      const [x1, y1, x2, y2] = committedRegion;
      ctx.strokeStyle = "#2bd4a3";
      ctx.fillStyle = "#2bd4a322";
      ctx.fillRect(x1, y1, x2 - x1, y2 - y1);
      ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
    }
    if (drag) {
      if (mode === "line") {
        ctx.strokeStyle = "#2b7de0";
        ctx.beginPath();
        ctx.moveTo(drag.x1, drag.y1);
        ctx.lineTo(drag.x2, drag.y2);
        ctx.stroke();
      } else {
        // region / crop: rectangle
        ctx.strokeStyle = "#2bd4a3";
        ctx.fillStyle = "#2bd4a322";
        const x = Math.min(drag.x1, drag.x2);
        const y = Math.min(drag.y1, drag.y2);
        const w = Math.abs(drag.x2 - drag.x1);
        const h = Math.abs(drag.y2 - drag.y1);
        ctx.fillRect(x, y, w, h);
        ctx.strokeRect(x, y, w, h);
      }
    }
  };

  // Draw frames from the shared device stream. The provider closes the bitmap
  // right after the callback, so clone it to keep a copy for overlay-only
  // redraws between frames.
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
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(redraw, [overlayPoints, overlayLine, drag, committedRegion]);

  const toOrig = (e: React.MouseEvent) => {
    const cv = canvasRef.current!;
    const r = cv.getBoundingClientRect();
    return {
      ox: Math.round(((e.clientX - r.left) * cv.width) / r.width),
      oy: Math.round(((e.clientY - r.top) * cv.height) / r.height),
    };
  };

  const onDown = (e: React.MouseEvent) => {
    if (!DRAG_MODES.has(mode) || !canvasRef.current?.width) return;
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

    if (mode === "coord") {
      onCoord?.(ox, oy);
      return;
    }
    if (mode === "points") {
      onPoint?.(ox, oy);
      return;
    }
    const s = dragStart.current;
    dragStart.current = null;
    setDrag(null);
    if (!s) return;
    if (mode === "line") {
      onLine?.(s.x, s.y, ox, oy);
    } else if (mode === "region") {
      onRegion?.([Math.min(s.x, ox), Math.min(s.y, oy), Math.max(s.x, ox), Math.max(s.y, oy)]);
    } else if (mode === "crop") {
      const region = [Math.min(s.x, ox), Math.min(s.y, oy), Math.max(s.x, ox), Math.max(s.y, oy)];
      const [rx, ry, rx2, ry2] = region;
      if (rx2 - rx < 2 || ry2 - ry < 2) return;
      // Cut the region out of the last frame for a right-panel preview.
      let preview = "";
      const fr = lastFrame.current;
      if (fr) {
        const oc = document.createElement("canvas");
        oc.width = rx2 - rx;
        oc.height = ry2 - ry;
        oc.getContext("2d")?.drawImage(fr, rx, ry, rx2 - rx, ry2 - ry, 0, 0, rx2 - rx, ry2 - ry);
        preview = oc.toDataURL("image/png");
      }
      onCrop?.(region, preview);
    }
  };

  const barInfo = info ?? (connected ? (picking ? `pick ${mode}…` : "streaming") : "not connected");

  return (
    <div className="device-view">
      <div className="device-bar">
        <span>{label}</span>
        <span className="muted device-info">{barInfo}</span>
      </div>
      <div className={`device-stage${picking ? " picking" : ""}`}>
        <canvas
          ref={canvasRef}
          className="device-canvas"
          onMouseDown={onDown}
          onMouseMove={onMove}
          onMouseUp={onUp}
        />
        {!connected && (
          <div className="device-offline">
            <div className="muted">Device not connected.</div>
            <button onClick={goToDevice}>Open Device tab</button>
          </div>
        )}
      </div>
    </div>
  );
}
