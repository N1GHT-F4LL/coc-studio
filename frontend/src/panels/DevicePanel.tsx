import { useCallback, useEffect, useState } from "react";
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

const stateText: Record<string, string> = {
  device: "sẵn sàng",
  offline: "offline — thử Scan lại hoặc khởi động lại emulator",
  unauthorized: "chưa cấp quyền — mở khoá thiết bị và chấp nhận RSA prompt",
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
  const [busy, setBusy] = useState<string>(""); // "scan" | "connect" | "launch" | ""

  useEffect(() => {
    deviceProfiles()
      .then((p) => {
        setProfiles(p);
        setProfile(p.current);
        setEndpoint(p.endpoint);
      })
      .catch(() => setProfiles(null));
  }, []);

  const saveProfile = useCallback(
    async (p: string, ep: string) => {
      try {
        await setDeviceProfile(p, ep);
        setProfiles((prev) => (prev ? { ...prev, current: p, endpoint: ep } : prev));
        onMessage(`Profile → ${p} (áp dụng ở lần Connect kế).`);
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
      const res = await scanDevices();
      setDevices(res.devices);
      onStatus(res.status);
      onMessage(
        res.devices.length
          ? `Tìm thấy ${res.devices.length} thiết bị.`
          : "Không thấy thiết bị nào — bấm Launch emulator hoặc kiểm tra profile/endpoint."
      );
    } catch (e) {
      onMessage(`Scan lỗi: ${(e as Error).message}`);
    } finally {
      setBusy("");
    }
  }, [onMessage, onStatus]);

  const doLaunch = useCallback(async () => {
    setBusy("launch");
    onMessage("Đang khởi động emulator (đợi ~12s)…");
    try {
      const res = await launchEmulator();
      onMessage(res.launched ? "Đã gọi khởi động emulator. Bấm Scan để kiểm tra." : "Profile này không có emulator để khởi động.");
    } catch (e) {
      onMessage(`Launch lỗi: ${(e as Error).message}`);
    } finally {
      setBusy("");
    }
  }, [onMessage]);

  const doConnect = useCallback(async () => {
    setBusy("connect");
    onMessage("Đang kết nối…");
    try {
      const res = await connectDevice();
      onStatus(res.status);
      onMessage(res.ok ? "Đã kết nối." : `Kết nối thất bại: ${REASON_TEXT[res.reason] ?? res.reason}`);
    } catch (e) {
      onMessage(`Kết nối lỗi: ${(e as Error).message}`);
    } finally {
      setBusy("");
    }
  }, [onMessage, onStatus]);

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

  const connected = !!device?.connected;
  const isCustom = profile === "custom_endpoint";

  return (
    <div className="device-panel-page">
      <div className="device-col">
        <section className="device-section">
          <h3>Trạng thái</h3>
          <div className="device-status-big">
            <span className={`dot ${connected ? "on" : "off"}`} />
            <span>{connected ? "Đã kết nối" : "Chưa kết nối"}</span>
            {device?.serial ? <span className="muted">· {device.serial}</span> : null}
            {device?.profile ? <span className="muted">· {device.profile}</span> : null}
          </div>
          {device?.reason && REASON_TEXT[device.reason] ? (
            <div className={`device-reason${connected ? "" : " warn"}`}>
              {REASON_TEXT[device.reason]}
            </div>
          ) : null}
          <div className="device-actions">
            <button className="run" onClick={doConnect} disabled={busy === "connect"}>
              {busy === "connect" ? "Đang kết nối…" : "▶ Connect"}
            </button>
            <button onClick={doDisconnect} disabled={!connected}>
              Disconnect
            </button>
          </div>
        </section>

        <section className="device-section">
          <h3>Profile</h3>
          <label className="field">
            <span>Emulator / thiết bị</span>
            <select
              value={profile}
              onChange={(e) => {
                setProfile(e.target.value);
                saveProfile(e.target.value, e.target.value === "custom_endpoint" ? endpoint : "");
              }}
            >
              {profiles?.profiles.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
          {isCustom && (
            <label className="field">
              <span>ADB endpoint (ip:port)</span>
              <div className="field-row">
                <input
                  value={endpoint}
                  placeholder="127.0.0.1:5555"
                  onChange={(e) => setEndpoint(e.target.value)}
                />
                <button onClick={() => saveProfile("custom_endpoint", endpoint)}>Save</button>
              </div>
            </label>
          )}
          <button onClick={doLaunch} disabled={busy === "launch" || isCustom || profile === "usb_or_existing"}>
            {busy === "launch" ? "Đang khởi động…" : "Launch emulator"}
          </button>
        </section>
      </div>

      <div className="device-col">
        <section className="device-section">
          <h3>
            Thiết bị
            <button className="inline-btn" onClick={doScan} disabled={busy === "scan"}>
              {busy === "scan" ? "Đang quét…" : "↻ Scan"}
            </button>
          </h3>
          {devices.length === 0 ? (
            <div className="muted">Chưa quét. Bấm Scan để liệt kê adb devices.</div>
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
                    <td className="muted">{stateText[d.state] ?? d.state}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </div>
  );
}
