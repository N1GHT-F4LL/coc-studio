import type { DeviceStatus } from "../api/client";

export type AppMode = "editor" | "scenario" | "asset" | "device" | "about";

interface Props {
  mode: AppMode;
  onMode: (m: AppMode) => void;
  graphName: string;
  savedGraphs: string[];
  onRename: (name: string) => void;
  onLoad: (name: string) => void;
  onSave: () => void;
  onNew: () => void;
  onAutoLayout: () => void;
  running: boolean;
  status: string; // runner status: "", "running", "ok", "error", "stopped", ...
  onRun: () => void;
  onStop: () => void;
  device: DeviceStatus | null;
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
  onAutoLayout,
  running,
  status,
  onRun,
  onStop,
  device,
}: Props) {
  const bot = botLight(running, status);
  const devOn = !!device?.connected;
  const devTitle = device
    ? `device ${device.connected ? "connected" : "not connected"}` +
      (device.serial ? ` - ${device.serial}` : "") +
      "\nClick to open the Device tab"
    : "Click to open the Device tab";

  return (
    <header className="toolbar">
      <strong>coc-studio</strong>

      <div className="mode-tabs">
        <button
          className={mode === "editor" ? "active" : ""}
          onClick={() => onMode("editor")}
          title="Build the automation flow (block graph)"
        >
          Bot Builder
        </button>
        <button
          className={mode === "scenario" ? "active" : ""}
          onClick={() => onMode("scenario")}
          title="Design the army composition + deploy plan"
        >
          Attack Plan
        </button>
        <button
          className={mode === "asset" ? "active" : ""}
          onClick={() => onMode("asset")}
          title="Manage template assets - capture, rename, replace, delete"
        >
          Assets
        </button>
        <button
          className={mode === "device" ? "active" : ""}
          onClick={() => onMode("device")}
          title="Connect & manage the emulator / device"
        >
          Device
        </button>
        <button
          className={mode === "about" ? "active" : ""}
          onClick={() => onMode("about")}
          title="About coc-studio"
        >
          About
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
          <button onClick={onAutoLayout} title="Tidy node positions by control-flow order">
            ⤓ Auto-layout
          </button>

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
        <span
          className="status-light clickable"
          onClick={() => onMode("device")}
          title={devTitle}
        >
          <span className={`dot ${devOn ? "on" : "off"}`} />
          device
        </span>
        <span className="status-light" title={`bot ${bot.label}`}>
          <span className={`dot ${bot.cls}`} />
          {bot.label}
        </span>
      </div>
    </header>
  );
}
