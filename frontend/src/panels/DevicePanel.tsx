import { useCallback, useEffect, useRef, useState } from "react";
import {
  deviceProfiles,
  setDeviceProfile,
  scanDevices,
  launchEmulator,
  connectDevice,
  disconnectDevice,
  selectSerial,
  type DeviceProfiles,
  type DeviceStatus,
  type AdbDevice,
} from "../api/client";
import { wsUrl } from "../api/ws";

// Human-readable explanation for each connection reason the backend reports.
const REASON_TEXT: Record<string, string> = {
  connected: "Đã kết nối.",
  already_connected: "Đã kết nối.",
  not_connected: "Chưa kết nối.",
  disconnected: "Đã ngắt kết nối.",
  adb_unavailable: "Không tìm thấy adb trong PATH — cài Android platform-tools.",
  device_unreachable: "Không tới được thiết bị — kiểm tra emulator đang chạy và serial đúng.",
  device_setup_failed: "Bootstrap thất bại — thử Scan / Launch / đổi profile.",
};

const STATE_TEXT: Record<string, string> = {
  device: "sẵn sàng",
  offline: "offline — Scan lại hoặc khởi động lại emulator",
  unauthorized: "chưa cấp quyền — mở khoá thiết bị, chấp nhận RSA",
};

interface Props {
  device: DeviceStatus | null;
  onStatus: (s: DeviceStatus) => void;
  onMessage: (m: string) => void;
}

export function DevicePanel({ device, onStatus, onMessage }: Props) {
  const [profiles, setProfiles] = useState<DeviceProfiles | null>(null);
  const [profile, setProfile] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const [devices, setDevices] = useState<AdbDevice[]>([]);
  const [busy, setBusy] = useState<string>("");

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const connected = !!device?.connected;
  const isCustom = profile === "custom_endpoint";
  const hasEmulator = !isCustom && profile !== "usb_or_existing" && profile !== "";

  // --- scan (shared by the Scan button and the smart Connect) --------------
  const runScan = useCallback(async (): Promise<AdbDevice[]> => {
    const res = await scanDevices();
    setDevices(res.devices);
    onStatus(res.status);
    return res.devices;
  }, [onStatus]);

  useEffect(() => {
    deviceProfiles()
      .then((p) => {
        setProfiles(p);
        setProfile(p.current);
        setEndpoint(p.endpoint);
      })
      .catch(() => setProfiles(null));
    // Auto-scan once on entering the tab so the list is ready.
    runScan().catch(() => {});
  }, [runScan]);

  // Live screen preview while connected.
  useEffect(() => {
    if (!connected) {
      wsRef.current?.close();
      wsRef.current = null;
      return;
    }
    const ws = new WebSocket(wsUrl("/ws/device?fps=3"));
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;
    ws.onmessage = async (e) => {
      if (typeof e.data === "string") return;
      const bmp = await createImageBitmap(new Blob([e.data], { type: "image/jpeg" }));
      const cv = canvasRef.current;
      if (cv) {
        cv.width = bmp.width;
        cv.height = bmp.height;
        cv.getContext("2d")?.drawImage(bmp, 0, 0);
      }
      bmp.close();
    };
    return () => ws.close();
  }, [connected]);

  const saveProfile = useCallback(
    async (p: string, ep: string) => {
      try {
        await setDeviceProfile(p, ep);
        setProfiles((prev) => (prev ? { ...prev, current: p, endpoint: ep } : prev));
        onMessage(`Profile → ${p}.`);
      } catch (e) {
        onMessage(`Lưu profile lỗi: ${(e as Error).message}`);
      }
    },
    [onMessage]
  );

  const doScan = useCallback(async () => {
    setBusy("scan");
    onMessage("Đang quét thiết bị…");
    try {
      const ds = await runScan();
      onMessage(ds.length ? `Tìm thấy ${ds.length} thiết bị.` : "Không thấy thiết bị nào.");
    } catch (e) {
      onMessage(`Scan lỗi: ${(e as Error).message}`);
    } finally {
      setBusy("");
    }
  }, [runScan, onMessage]);

  const doLaunch = useCallback(async () => {
    setBusy("launch");
    onMessage("Đang khởi động emulator (đợi ~12s)…");
    try {
      await launchEmulator();
      await runScan();
      onMessage("Đã gọi khởi động emulator.");
    } catch (e) {
      onMessage(`Launch lỗi: ${(e as Error).message}`);
    } finally {
      setBusy("");
    }
  }, [runScan, onMessage]);

  // Smart connect: scan first; if a usable device exists, connect (the backend
  // auto-picks/validates the serial). If none and the profile has an emulator,
  // hint to Launch.
  const doConnect = useCallback(async () => {
    setBusy("connect");
    onMessage("Đang kết nối…");
    try {
      const ds = await runScan();
      const ready = ds.filter((d) => d.state === "device");
      if (ready.length === 0) {
        onMessage(
          hasEmulator
            ? "Chưa thấy thiết bị — bấm Launch emulator rồi thử lại."
            : "Chưa thấy thiết bị adb nào — kiểm tra emulator/endpoint."
        );
        return;
      }
      const res = await connectDevice();
      onStatus(res.status);
      onMessage(res.ok ? "Đã kết nối." : `Thất bại: ${REASON_TEXT[res.reason] ?? res.reason}`);
    } catch (e) {
      onMessage(`Kết nối lỗi: ${(e as Error).message}`);
    } finally {
      setBusy("");
    }
  }, [runScan, hasEmulator, onMessage, onStatus]);

  const doDisconnect = useCallback(async () => {
    try {
      const res = await disconnectDevice();
      onStatus(res.status);
      onMessage("Đã ngắt kết nối.");
    } catch (e) {
      onMessage(`Ngắt lỗi: ${(e as Error).message}`);
    }
  }, [onMessage, onStatus]);

  const pickSerial = useCallback(
    async (serial: string) => {
      try {
        const res = await selectSerial(serial);
        onStatus(res.status);
        onMessage(`Đã chọn serial ${serial}.`);
      } catch (e) {
        onMessage(`Chọn serial lỗi: ${(e as Error).message}`);
      }
    },
    [onMessage, onStatus]
  );

  return (
    <div className="device-tab">
      {/* Sidebar: configure + pick (top-to-bottom = the connect flow) */}
      <aside className="device-sidebar">
        <div className="device-step">
          <div className="device-step-title">1 · Profile</div>
          <select
            value={profile}
            onChange={(e) => {
              const p = e.target.value;
              setProfile(p);
              saveProfile(p, p === "custom_endpoint" ? endpoint : "");
            }}
          >
            {profiles?.profiles.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
          {isCustom && (
            <div className="field-row" style={{ marginTop: 6 }}>
              <input
                value={endpoint}
                placeholder="127.0.0.1:5555"
                onChange={(e) => setEndpoint(e.target.value)}
              />
              <button onClick={() => saveProfile("custom_endpoint", endpoint)}>Save</button>
            </div>
          )}
          {hasEmulator && (
            <button
              className="device-wide"
              onClick={doLaunch}
              disabled={busy === "launch"}
              style={{ marginTop: 6 }}
            >
              {busy === "launch" ? "Đang khởi động…" : "Launch emulator"}
            </button>
          )}
        </div>

        <div className="device-step">
          <div className="device-step-title">
            2 · Thiết bị
            <button className="inline-btn" onClick={doScan} disabled={busy === "scan"}>
              {busy === "scan" ? "…" : "↻ Scan"}
            </button>
          </div>
          {devices.length === 0 ? (
            <div className="muted">Chưa thấy thiết bị. Bấm Scan.</div>
          ) : (
            <table className="device-table">
              <tbody>
                {devices.map((d) => (
                  <tr
                    key={d.serial}
                    className={d.serial === device?.serial ? "selected" : ""}
                    onClick={() => pickSerial(d.serial)}
                    title="Click để chọn serial này"
                  >
                    <td>
                      <span className={`dot ${d.state === "device" ? "on" : "warn"}`} />
                    </td>
                    <td className="serial">{d.serial}</td>
                    <td className="muted">{STATE_TEXT[d.state] ?? d.state}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="device-step">
          <div className="device-step-title">3 · Kết nối</div>
          <button className="run device-wide" onClick={doConnect} disabled={busy === "connect"}>
            {busy === "connect" ? "Đang kết nối…" : "▶ Connect"}
          </button>
          <button
            className="device-wide"
            onClick={doDisconnect}
            disabled={!connected}
            style={{ marginTop: 6 }}
          >
            Disconnect
          </button>
        </div>
      </aside>

      {/* Content: status + live screen */}
      <div className="device-content">
        <div className="device-statusbar">
          <span className={`dot ${connected ? "on" : "off"}`} />
          <strong>{connected ? "Đã kết nối" : "Chưa kết nối"}</strong>
          {device?.serial ? <span className="muted">· {device.serial}</span> : null}
          {device?.profile ? <span className="muted">· {device.profile}</span> : null}
          {device?.reason && REASON_TEXT[device.reason] ? (
            <span className={`device-reason${connected ? "" : " warn"}`}>
              — {REASON_TEXT[device.reason]}
            </span>
          ) : null}
        </div>
        <div className="device-screen">
          {connected ? (
            <canvas ref={canvasRef} className="device-screen-canvas" />
          ) : (
            <div className="muted device-screen-empty">
              Kết nối thiết bị để xem màn hình trực tiếp.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
