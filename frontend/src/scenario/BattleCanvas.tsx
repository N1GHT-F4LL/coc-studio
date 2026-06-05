import { useEffect, useRef, useState } from "react";
import { wsUrl } from "../api/ws";

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
  const [on, setOn] = useState(false);
  const [info, setInfo] = useState("off");
  const [drag, setDrag] = useState<{ x1: number; y1: number; x2: number; y2: number } | null>(
    null
  );
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const dragStart = useRef<{ x: number; y: number } | null>(null);
  const lastFrame = useRef<ImageBitmap | null>(null);

  // Redraw the last frame + overlay (points/line + in-progress drag).
  const redraw = () => {
    const cv = canvasRef.current;
    const ctx = cv?.getContext("2d");
    if (!cv || !ctx) return;
    if (lastFrame.current) ctx.drawImage(lastFrame.current, 0, 0, cv.width, cv.height);
    const sx = cv.width;
    const sy = cv.height;
    // device px -> canvas px (canvas already at device resolution, so 1:1)
    void sx;
    void sy;
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

  useEffect(() => {
    if (!on) {
      wsRef.current?.close();
      wsRef.current = null;
      return;
    }
    const ws = new WebSocket(wsUrl("/ws/device?fps=4"));
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;
    setInfo("connecting…");
    ws.onopen = () => setInfo("streaming");
    ws.onclose = () => setInfo("off");
    ws.onerror = () => setInfo("error");
    ws.onmessage = async (e) => {
      if (typeof e.data === "string") {
        try {
          const m = JSON.parse(e.data);
          if (m.type === "no_frame") setInfo(`no frame (${m.reason})`);
        } catch {
          /* ignore */
        }
        return;
      }
      const bmp = await createImageBitmap(new Blob([e.data], { type: "image/jpeg" }));
      const cv = canvasRef.current;
      if (cv) {
        cv.width = bmp.width;
        cv.height = bmp.height;
        lastFrame.current?.close();
        lastFrame.current = bmp;
        redraw();
      } else {
        bmp.close();
      }
    };
    return () => ws.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [on]);

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
        <button onClick={() => setOn((v) => !v)}>{on ? "Disconnect" : "Connect"}</button>
        <span className="muted device-info">
          {pickMode ? `pick ${pickMode}…` : info}
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
        {!on && <div className="battle-hint muted">Connect to pick deploy coordinates.</div>}
      </div>
    </div>
  );
}
