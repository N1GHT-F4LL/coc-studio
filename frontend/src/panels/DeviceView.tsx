import { useEffect, useRef, useState } from "react";
import { wsUrl } from "../api/ws";

// Live device view: binary JPEG frames from /ws/device drawn onto a <canvas>.
// Streaming uses ADB screen capture, so it only runs while toggled on.
export function DeviceView() {
  const [on, setOn] = useState(false);
  const [info, setInfo] = useState("off");
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

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
        cv.getContext("2d")?.drawImage(bmp, 0, 0);
        setInfo(`streaming ${bmp.width}×${bmp.height}`);
      }
      bmp.close();
    };
    return () => ws.close();
  }, [on]);

  return (
    <div className="device-view">
      <div className="device-bar">
        <span>Device</span>
        <button onClick={() => setOn((v) => !v)}>{on ? "Disconnect" : "Connect"}</button>
        <span className="muted device-info">{info}</span>
      </div>
      <canvas ref={canvasRef} className="device-canvas" />
    </div>
  );
}
