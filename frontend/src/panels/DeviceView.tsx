import { useEffect, useRef, useState } from "react";
import { fetchAssetCategories, saveCrop, type AssetCategory } from "../api/client";
import { useDeviceStream } from "../device/DeviceStreamContext";

interface Props {
  // When set, the next click (Coord) / drag (Region) on the frame picks a value.
  pickKind: "Coord" | "Region" | null;
  onPick: (value: number[]) => void;
  onAssetSaved: () => void; // refresh the asset list after a crop save
}

interface Rect {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

// Live device view: binary JPEG frames from /ws/device drawn onto a <canvas>.
// Doubles as the picker (Coord/Region for params) and the asset studio (crop a
// region of the live screen and save it as a template).
export function DeviceView({ pickKind, onPick, onAssetSaved }: Props) {
  const { connected, goToDevice, subscribe } = useDeviceStream();
  const [assetMode, setAssetMode] = useState(false);
  const [dispRect, setDispRect] = useState<Rect | null>(null); // overlay, display px
  const [pending, setPending] = useState<{ region: number[] } | null>(null);
  const [cats, setCats] = useState<AssetCategory[]>([]);
  const [folder, setFolder] = useState("units/troops");
  const [assetName, setAssetName] = useState("");
  const [info, setInfo] = useState("");

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const dragStart = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    fetchAssetCategories().then(setCats).catch(() => setCats([]));
  }, []);

  // Draw frames from the shared device stream (one WS for the whole app).
  useEffect(
    () =>
      subscribe((bmp) => {
        const cv = canvasRef.current;
        if (!cv) return;
        cv.width = bmp.width;
        cv.height = bmp.height;
        cv.getContext("2d")?.drawImage(bmp, 0, 0);
      }),
    [subscribe]
  );

  const picking = pickKind !== null || assetMode;

  // Map a pointer event to original (device) coordinates.
  const toOrig = (e: React.MouseEvent) => {
    const cv = canvasRef.current!;
    const r = cv.getBoundingClientRect();
    const sx = cv.width / r.width;
    const sy = cv.height / r.height;
    return {
      ox: Math.round((e.clientX - r.left) * sx),
      oy: Math.round((e.clientY - r.top) * sy),
      dx: e.clientX - r.left,
      dy: e.clientY - r.top,
    };
  };

  const onDown = (e: React.MouseEvent) => {
    if (!picking || !canvasRef.current?.width) return;
    const { dx, dy } = toOrig(e);
    dragStart.current = { x: dx, y: dy };
    setDispRect({ x1: dx, y1: dy, x2: dx, y2: dy });
  };
  const onMove = (e: React.MouseEvent) => {
    if (!dragStart.current) return;
    const { dx, dy } = toOrig(e);
    setDispRect({ x1: dragStart.current.x, y1: dragStart.current.y, x2: dx, y2: dy });
  };
  const onUp = (e: React.MouseEvent) => {
    if (!dragStart.current) return;
    const start = dragStart.current;
    dragStart.current = null;
    setDispRect(null);
    const { ox, oy } = toOrig(e);
    const cv = canvasRef.current!;
    const r = cv.getBoundingClientRect();
    const sx = cv.width / r.width;
    const sy = cv.height / r.height;
    const sox = Math.round(start.x * sx);
    const soy = Math.round(start.y * sy);
    const region = [Math.min(sox, ox), Math.min(soy, oy), Math.max(sox, ox), Math.max(soy, oy)];

    if (pickKind === "Coord") {
      onPick([ox, oy]);
    } else if (pickKind === "Region") {
      onPick(region);
    } else if (assetMode) {
      if (region[2] - region[0] < 2 || region[3] - region[1] < 2) return;
      setPending({ region });
    }
  };

  const doSave = async () => {
    if (!pending) return;
    try {
      const res = await saveCrop(pending.region, folder, assetName);
      setInfo(`saved ${res.key} (${res.width}×${res.height})`);
      setPending(null);
      setAssetName("");
      setAssetMode(false);
      onAssetSaved();
    } catch (err) {
      setInfo(`save failed: ${(err as Error).message}`);
    }
  };

  return (
    <div className="device-view">
      <div className="device-bar">
        <span>Device</span>
        {connected && (
          <button
            className={assetMode ? "active" : ""}
            onClick={() => setAssetMode((v) => !v)}
            title="Drag a rectangle on the frame to capture a template"
          >
            {assetMode ? "Capturing…" : "Capture asset"}
          </button>
        )}
        <span className="muted device-info">
          {pickKind ? `pick ${pickKind}…` : info}
        </span>
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
            <div className="muted">Chưa kết nối thiết bị.</div>
            <button onClick={goToDevice}>Mở tab Device</button>
          </div>
        )}
        {dispRect && (
          <div
            className="crop-rect"
            style={{
              left: Math.min(dispRect.x1, dispRect.x2),
              top: Math.min(dispRect.y1, dispRect.y2),
              width: Math.abs(dispRect.x2 - dispRect.x1),
              height: Math.abs(dispRect.y2 - dispRect.y1),
            }}
          />
        )}
      </div>

      {pending && (
        <div className="asset-form">
          <div className="muted">region {pending.region.join(", ")}</div>
          <select value={folder} onChange={(e) => setFolder(e.target.value)}>
            {cats.map((c) => (
              <option key={c.folder} value={c.folder}>
                {c.label}
              </option>
            ))}
          </select>
          <input
            placeholder="asset name"
            value={assetName}
            onChange={(e) => setAssetName(e.target.value)}
          />
          <div className="field-row">
            <button className="run" disabled={!assetName} onClick={doSave}>
              Save asset
            </button>
            <button onClick={() => setPending(null)}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}
