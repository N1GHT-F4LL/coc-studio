import { useState } from "react";
import type { DeviceStatus } from "../api/client";
import { getSettings, putSettings } from "../api/client";

export type AppMode = "editor" | "scenario" | "asset" | "device" | "about";

// Compact display: 100000 -> 100K
const fmtK = (v: number) => (v >= 1000 ? `${Math.round(v / 1000)}K` : `${v}`);

// Inline loot-threshold editor (Find Match's gold/elixir/dark minimums, stored
// in settings.json's "farm" group and read fresh on every run).
function LootEditor() {
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState({ gold: "", elixir: "", dark: "" });
  const [label, setLabel] = useState("Loot");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const refresh = async () => {
    try {
      const s = await getSettings();
      const f = s.farm ?? {};
      setValues({
        gold: String(f.min_gold ?? 0),
        elixir: String(f.min_elixir ?? 0),
        dark: String(f.min_dark_elixir ?? 0),
      });
      setLabel(
        `Loot ${fmtK(Number(f.min_gold) || 0)}/${fmtK(Number(f.min_elixir) || 0)}/${fmtK(
          Number(f.min_dark_elixir) || 0
        )}`
      );
    } catch {
      setLabel("Loot (?)");
    }
  };

  const save = async () => {
    setBusy(true);
    setErr("");
    try {
      const s = await getSettings();
      s.farm = {
        ...(s.farm ?? {}),
        min_gold: Number(values.gold) || 0,
        min_elixir: Number(values.elixir) || 0,
        min_dark_elixir: Number(values.dark) || 0,
      };
      await putSettings(s);
      await refresh();
      setOpen(false);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className="loot-wrap">
      <button
        onClick={() => {
          const next = !open;
          setOpen(next);
          if (next) refresh();
        }}
        title="Loot thresholds used by Find Match (saved to settings)"
      >
        {label}
      </button>
      {open && (
        <div className="loot-pop">
          <div className="loot-row">
            <span>Gold</span>
            <input
              type="number"
              value={values.gold}
              onChange={(e) => setValues({ ...values, gold: e.target.value })}
            />
          </div>
          <div className="loot-row">
            <span>Elixir</span>
            <input
              type="number"
              value={values.elixir}
              onChange={(e) => setValues({ ...values, elixir: e.target.value })}
            />
          </div>
          <div className="loot-row">
            <span>Dark</span>
            <input
              type="number"
              value={values.dark}
              onChange={(e) => setValues({ ...values, dark: e.target.value })}
            />
          </div>
          {err && <div className="loot-err">{err}</div>}
          <button onClick={save} disabled={busy}>
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      )}
    </span>
  );
}

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
  onPause: () => void;
  onResume: () => void;
  device: DeviceStatus | null;
}

// Maps the runner status to a bot-light dot class + label.
function botLight(running: boolean, status: string): { cls: string; label: string } {
  if (status === "paused") return { cls: "warn", label: "paused" };
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
  onPause,
  onResume,
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
          <button
            onClick={status === "paused" ? onResume : onPause}
            disabled={!running}
            title={status === "paused" ? "Resume the run" : "Pause the run"}
          >
            {status === "paused" ? "Resume" : "Pause"}
          </button>
          <button className="stop" onClick={onStop} disabled={!running} title="Stop the run">
            ■ Stop
          </button>

          <LootEditor />
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
