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
import { useDeviceFrames } from "../device/DeviceStreamContext";

// Human-readable explanation for each connection reason the backend reports.
const REASON_TEXT: Record<string, string> = {
  connected: "Connected.",
  already_connected: "Connected.",
  not_connected: "Not connected.",
  disconnected: "Disconnected.",
  adb_unavailable: "adb not found in PATH — install Android platform-tools.",
  device_unreachable: "Device unreachable — check the emulator is running and the serial is correct.",
  device_setup_failed: "Bootstrap failed — try Scan / Launch / a different profile.",
};

const STATE_TEXT: Record<string, string> = {
  device: "ready",
  offline: "offline — Scan again or restart the emulator",
  unauthorized: "unauthorized — unlock the device, accept the RSA prompt",
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

  const connected = !!device?.connected;

  // Live screen via the shared device stream (one WS for the whole app).
  useDeviceFrames((bmp) => {
    const cv = canvasRef.current;
    if (!cv) return;
    cv.width = bmp.width;
    cv.height = bmp.height;
    cv.getContext("2d")?.drawImage(bmp, 0, 0);
  });
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

  const saveProfile = useCallback(
    async (p: string, ep: string) => {
      try {
        await setDeviceProfile(p, ep);
        setProfiles((prev) => (prev ? { ...prev, current: p, endpoint: ep } : prev));
        onMessage(`Profile → ${p}.`);
      } catch (e) {
        onMessage(`Save profile failed: ${(e as Error).message}`);
      }
    },
    [onMessage]
  );

  const doScan = useCallback(async () => {
    setBusy("scan");
    onMessage("Scanning devices…");
    try {
      const ds = await runScan();
      onMessage(ds.length ? `Found ${ds.length} device(s).` : "No devices found.");
    } catch (e) {
      onMessage(`Scan failed: ${(e as Error).message}`);
    } finally {
      setBusy("");
    }
  }, [runScan, onMessage]);

  const doLaunch = useCallback(async () => {
    setBusy("launch");
    onMessage("Launching emulator (wait ~12s)…");
    try {
      await launchEmulator();
      await runScan();
      onMessage("Emulator launch requested.");
    } catch (e) {
      onMessage(`Launch failed: ${(e as Error).message}`);
    } finally {
      setBusy("");
    }
  }, [runScan, onMessage]);

  // Smart connect: scan first; if a usable device exists, connect (the backend
  // auto-picks/validates the serial). If none and the profile has an emulator,
  // hint to Launch.
  const doConnect = useCallback(async () => {
    setBusy("connect");
    onMessage("Connecting…");
    try {
      const ds = await runScan();
      const ready = ds.filter((d) => d.state === "device");
      if (ready.length === 0) {
        onMessage(
          hasEmulator
            ? "No device yet — click Launch emulator then try again."
            : "No adb device found — check the emulator / endpoint."
        );
        return;
      }
      const res = await connectDevice();
      onStatus(res.status);
      onMessage(res.ok ? "Connected." : `Failed: ${REASON_TEXT[res.reason] ?? res.reason}`);
    } catch (e) {
      onMessage(`Connect failed: ${(e as Error).message}`);
    } finally {
      setBusy("");
    }
  }, [runScan, hasEmulator, onMessage, onStatus]);

  const doDisconnect = useCallback(async () => {
    try {
      const res = await disconnectDevice();
      onStatus(res.status);
      onMessage("Disconnected.");
    } catch (e) {
      onMessage(`Disconnect failed: ${(e as Error).message}`);
    }
  }, [onMessage, onStatus]);

  const pickSerial = useCallback(
    async (serial: string) => {
      try {
        const res = await selectSerial(serial);
        onStatus(res.status);
        onMessage(`Selected serial ${serial}.`);
      } catch (e) {
        onMessage(`Select serial failed: ${(e as Error).message}`);
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
              {busy === "launch" ? "Launching…" : "Launch emulator"}
            </button>
          )}
        </div>

        <div className="device-step">
          <div className="device-step-title">
            2 · Device
            <button className="inline-btn" onClick={doScan} disabled={busy === "scan"}>
              {busy === "scan" ? "…" : "↻ Scan"}
            </button>
          </div>
          {devices.length === 0 ? (
            <div className="muted">No device yet. Click Scan.</div>
          ) : (
            <table className="device-table">
              <tbody>
                {devices.map((d) => (
                  <tr
                    key={d.serial}
                    className={d.serial === device?.serial ? "selected" : ""}
                    onClick={() => pickSerial(d.serial)}
                    title="Click to select this serial"
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
          <div className="device-step-title">3 · Connect</div>
          <button className="run device-wide" onClick={doConnect} disabled={busy === "connect"}>
            {busy === "connect" ? "Connecting…" : "▶ Connect"}
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
          <strong>{connected ? "Connected" : "Not connected"}</strong>
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
              Connect a device to see the live screen.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
