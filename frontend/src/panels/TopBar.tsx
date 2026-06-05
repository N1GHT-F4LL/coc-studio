import type { DeviceStatus, DeviceProfiles } from "../api/client";

export type AppMode = "editor" | "scenario";

interface Props {
  mode: AppMode;
  onMode: (m: AppMode) => void;
  graphName: string;
  savedGraphs: string[];
  onRename: (name: string) => void;
  onLoad: (name: string) => void;
  onSave: () => void;
  onNew: () => void;
  running: boolean;
  status: string; // runner status: "", "running", "ok", "error", "stopped", ...
  onRun: () => void;
  onStop: () => void;
  device: DeviceStatus | null;
  onConnectDevice: () => void;
  profiles: DeviceProfiles | null;
  onSetProfile: (profile: string) => void;
  message: string; // free-text status line
}

// Maps the runner status to a bot-light dot class + label.
function botLight(running: boolean, status: string): { cls: string; label: string } {
  if (running) return { cls: "run", label: status === "connecting" ? "connecting" : "running" };
  switch (status) {
    case "ok":
      return { cls: "on", label: "ok" };
    case "error":
    case "invalid":
      return { cls: "err", label: status };
    case "stopped":
    case "busy":
      return { cls: "warn", label: status };
    default:
      return { cls: "off", label: "idle" };
  }
}

export function TopBar({
  mode,
  onMode,
  graphName,
  savedGraphs,
  onRename,
  onLoad,
  onSave,
  onNew,
  running,
  status,
  onRun,
  onStop,
  device,
  onConnectDevice,
  profiles,
  onSetProfile,
  message,
}: Props) {
  const bot = botLight(running, status);
  const devOn = !!device?.connected;
  const devTitle = device
    ? `device ${device.connected ? "connected" : "not connected"}` +
      (device.serial ? ` — ${device.serial}` : "") +
      (device.reason ? ` (${device.reason})` : "") +
      "\nClick to connect"
    : "Click to connect device";

  return (
    <header className="toolbar">
      <strong>coc-studio</strong>

      <div className="mode-tabs">
        <button
          className={mode === "editor" ? "active" : ""}
          onClick={() => onMode("editor")}
        >
          Editor
        </button>
        <button
          className={mode === "scenario" ? "active" : ""}
          onClick={() => onMode("scenario")}
        >
          Scenario
        </button>
      </div>

      <span className="toolbar-sep" />

      {mode === "editor" && (
        <>
          <select
            value={savedGraphs.includes(graphName) ? graphName : ""}
            onChange={(e) => onLoad(e.target.value)}
            title="Load a saved graph"
          >
            <option value="">Load…</option>
            {savedGraphs.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </select>
          <input
            className="graph-name"
            value={graphName}
            onChange={(e) => onRename(e.target.value)}
            placeholder="graph name"
          />
          <button onClick={onSave}>Save</button>
          <button onClick={onNew}>New</button>

          <span className="toolbar-sep" />

          <button className="run" onClick={onRun} disabled={running} title="Run the current graph">
            ▶ Run
          </button>
          <button className="stop" onClick={onStop} disabled={!running} title="Stop the run">
            ■ Stop
          </button>
        </>
      )}

      <div className="lights">
        {profiles && (
          <select
            className="profile-select"
            value={profiles.current}
            onChange={(e) => onSetProfile(e.target.value)}
            title="Emulator / device profile (applies on next connect)"
          >
            {profiles.profiles.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        )}
        <span
          className="status-light clickable"
          onClick={onConnectDevice}
          title={devTitle}
        >
          <span className={`dot ${devOn ? "on" : "off"}`} />
          device
        </span>
        <span className="status-light" title={`bot ${bot.label}`}>
          <span className={`dot ${bot.cls}`} />
          {bot.label}
        </span>
        {message && <span className="status">{message}</span>}
      </div>
    </header>
  );
}
