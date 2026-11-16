import { useCallback, useEffect, useState } from "react";
import {
  applyMV,
  deleteAllMV,
  fetchMV,
  listScenarios,
  loadMV,
  mvIconUrl,
  putMVConfig,
  saveMV,
  type MVState,
  type MVVillageConfig,
} from "../api/client";


interface EditorState {
  idx: number;
  scenario: string;
  min_gold: number;
  min_elixir: number;
  min_dark_elixir: number;
}

export function MultiVillage({ onMessage }: { onMessage: (s: string) => void }) {
  const [mv, setMv] = useState<MVState | null>(null);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [scenarios, setScenarios] = useState<string[]>([]);
  const [applying, setApplying] = useState<number | null>(null);
  const [msg, setMsg] = useState<{ text: string; kind: "ok" | "err" } | null>(null);

  // local message bar — errors from the MV API MUST be visible here (the
  // global status line does not render on this tab; the user had to run
  // Burp Suite to see a 400).
  const setMsgBoth = useCallback((text: string, kind: "ok" | "err" = "ok") => {
    setMsg({ text, kind });
    onMessage(text);
  }, [onMessage]);

  const refresh = useCallback(async () => {
    let s: MVState;
    try {
      s = await fetchMV();
    } catch (e) {
      setMv(null);
      setMsg({ text: `Không đọc được cấu hình Multi-Village: ${(e as Error).message} `
                   + '(backend chưa restart?)', kind: 'err' });
      onMessage(`Multi-Village load failed: ${(e as Error).message}`);
      return;
    }
    try {
      setMv(s);
      // keep the editor's village in sync with what the bot really farms
      if (s.current_village_idx !== null && editor !== null
          && editor.idx !== s.current_village_idx
          && s.active_village_idx === s.current_village_idx) {
        onMessage(`Now farming Village_${s.current_village_idx}.`);
      }
    } catch (e) {
      onMessage(`Multi-Village load failed: ${(e as Error).message}`);
    }
  }, [editor, onMessage]);

  useEffect(() => {
    refresh();
    listScenarios().then(setScenarios).catch(() => setScenarios([]));
    const onMv = () => refresh();
    window.addEventListener("mv-active", onMv);
    return () => window.removeEventListener("mv-active", onMv);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pushConfig = async (mut: (cfg: MVState["config"]) => void) => {
    if (!mv) return;
    // Re-read the server's CURRENT config before mutating: the local `mv`
    // snapshot can be stale (e.g. an Apply confirmed a village in another
    // handler) and PUT would overwrite it with the stale copy — wiping
    // confirmed flags / configs.
    let cfg: MVState["config"];
    try {
      const fresh = await fetchMV();
      cfg = JSON.parse(JSON.stringify(fresh.config)) as MVState["config"];
    } catch (e) {
      setMsgBoth(`Save failed: could not re-read the current config (${(e as Error).message}).`, "err");
      return;
    }
    mut(cfg);
    try {
      await putMVConfig(cfg);
      await refresh();
      setMsgBoth("Multi-Village settings saved.", "ok");
    } catch (e) {
      setMsgBoth(`Save failed: ${(e as Error).message}`, "err");
    }
  };

  const handleInterval = (totalMins: number) => {
    const total = Math.max(1, Math.round(totalMins));
    pushConfig((cfg) => {
      cfg.interval_mins = total;
    });
  };

  const handleLoad = async (idx: number) => {
    if (!window.confirm(`Load configuration for Village_${idx}?`)) return;
    try {
      const res = await loadMV(idx);
      const c = res.config;
      setEditor({
        idx,
        scenario: c?.scenario ?? "",
        min_gold: c?.farm?.min_gold ?? 100000,
        min_elixir: c?.farm?.min_elixir ?? 100000,
        min_dark_elixir: c?.farm?.min_dark_elixir ?? 500,
      });
      await refresh();
      setMsgBoth(c
        ? `Loaded Village_${idx}.`
        : `Village_${idx} chưa có config — điền scenario + ngưỡng rồi Save để tạo.`, c ? "ok" : "err");
    } catch (e) {
      setMsgBoth(`Load failed: ${(e as Error).message}`, "err");
    }
  };

  const handleSave = async (idx: number) => {
    if (!editor || editor.idx !== idx) return;
    const cfg: MVVillageConfig = {
      scenario: editor.scenario,
      farm: {
        min_gold: editor.min_gold,
        min_elixir: editor.min_elixir,
        min_dark_elixir: editor.min_dark_elixir,
      },
    };
    try {
      await saveMV(idx, cfg);
      setMsgBoth("Saved successfully!", "ok");
      await refresh();
    } catch (e) {
      setMsgBoth(`Save failed: ${(e as Error).message}`, "err");
    }
  };

  const handleApply = async (idx: number) => {
    if (!editor || editor.idx !== idx) return;
    if (!window.confirm(
      `Apply Village_${idx}: the bot will SWITCH the game to this account now ` +
      `(blind Supercell ID sequence, up to ~3 minutes), then save this config ` +
      `and lock the row. Continue?`)) return;
    setApplying(idx);
    onMessage(`Switching to Village_${idx} — do not touch the emulator...`);
    const cfg: MVVillageConfig = {
      scenario: editor.scenario,
      farm: {
        min_gold: editor.min_gold,
        min_elixir: editor.min_elixir,
        min_dark_elixir: editor.min_dark_elixir,
      },
    };
    try {
      await applyMV(idx, cfg);
      setEditor(null);
      setMsgBoth(`Village_${idx} confirmed and locked.`, "ok");
    } catch (e) {
      setMsgBoth(`Apply failed: ${(e as Error).message}`, "err");
    } finally {
      setApplying(null);
      await refresh();
    }
  };

  const handleDeleteAll = async () => {
    if (!window.confirm(
      "Do you want to delete all saved settings and images for every village?")) return;
    try {
      await deleteAllMV();
      setEditor(null);
      setMsgBoth("All Multi-Village settings deleted.", "ok");
      await refresh();
    } catch (e) {
      setMsgBoth(`Delete All failed: ${(e as Error).message}`, "err");
    }
  };

  if (!mv) return <div className="mv-panel muted">Loading Multi-Village…</div>;

  const cfg = mv.config;
  const enabled = cfg.enabled;

  return (
    <div className="mv-panel">
      <div className="mv-header">
        <h2>Multi-Village</h2>
        <span className="mv-state">
          editor → <b>{mv.active_village_idx === null ? "—" : `Village_${mv.active_village_idx}`}</b>
          {"  ·  bot → "}
          <b>{mv.current_village_idx === null ? "—" : `Village_${mv.current_village_idx}`}</b>
        </span>
        <label className="mv-toggle">
          <input
            type="checkbox"
            checked={enabled}
            onChange={() => pushConfig((c) => { c.enabled = !c.enabled; })}
          />
          <strong>Enable rotation</strong>
        </label>
      </div>

      {msg !== null && (
        <div className={msg.kind === "err" ? "mv-msg err" : "mv-msg ok"}
             role="status">
          {msg.text}
        </div>
      )}

      {!mv.template_ready && (
        <div className="mv-warn">
          Settings-panel template missing — capture assets/multi_village/settings_tab.png
          from a real frame before switching (see scripts/calib_mv_settings_tab.py).
        </div>
      )}
      {!mv.coords_calibrated && (
        <div className="mv-warn">
          SCID page coordinates not calibrated yet — switching is disabled until
          the calibration session (MEmu screenshot hotkey) maps them.
        </div>
      )}

      <div className="mv-controls">
        <label>
          Switch interval:
          <input
            type="number" min={0} max={23} value={Math.floor(cfg.interval_mins / 60)}
            onChange={(e) => handleInterval(Number(e.target.value) * 60 + (cfg.interval_mins % 60))}
          />
          hour(s)
          <input
            type="number" min={0} max={59} value={cfg.interval_mins % 60}
            onChange={(e) => handleInterval(Math.floor(cfg.interval_mins / 60) * 60 + Number(e.target.value))}
          />
          minute(s)
        </label>
        <span className="mv-hint">
          Tick the villages to farm — the rotation cycles through them in list
          order.
        </span>
      </div>

      <div className="mv-section">
        <div className="mv-section-label">Villages</div>
        {!enabled && (
          <div className="mv-hint">
            Rotation is off — the village list is read-only. Tick "Enable
            rotation" above to pick farming targets.
          </div>
        )}
        <div className="mv-villages">
          {cfg.villages.map((v) => {
            const busy = applying === v.idx;
            const rowDisabled = !enabled || applying !== null;
            const st = mv.stats[v.idx] ?? { cycles: 0, switches: 0 };
            return (
              <div key={v.idx}
                   className={"mv-row" + (busy ? " busy" : "") + (!enabled ? " off" : "")}>
                <img className="mv-icon" src={mvIconUrl(v.idx)}
                     alt={v.confirmed ? `home_v${v.idx}` : "no snapshot"}
                     onError={(e) => ((e.target as HTMLImageElement).style.visibility = "hidden")} />
                <div className="mv-row-info">
                  <div className="mv-row-name">
                    <input
                      type="checkbox" checked={v.enabled} disabled={rowDisabled}
                      title={enabled
                        ? "Farm this village (rotation target)"
                        : "Enable rotation first to pick farming targets"}
                      onChange={() => pushConfig((c) => {
                        const vv = c.villages.find((x) => x.idx === v.idx);
                        if (vv) vv.enabled = !vv.enabled;
                      })}
                    />
                    Village_{v.idx} ({v.name})
                  </div>
                  <div className="mv-row-stats">
                    cycles {st.cycles} · switches {st.switches}
                  </div>
                </div>
                <div className="mv-row-actions">
                  <button disabled={rowDisabled} onClick={() => handleLoad(v.idx)}>Load</button>
                  <button
                    disabled={rowDisabled || mv.active_village_idx !== v.idx}
                    title={mv.active_village_idx !== v.idx
                      ? "Load this village's configuration first"
                      : "Save the editor values into this village"}
                    onClick={() => handleSave(v.idx)}
                  >
                    Save
                  </button>
                  <button
                    disabled={rowDisabled || editor === null || editor.idx !== v.idx}
                    title="Switch the game to this account now and verify it (re-runnable)"
                    onClick={() => handleApply(v.idx)}
                  >
                    {busy ? "Switching…" : "Apply"}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {editor !== null && (
        <fieldset className="mv-editor">
          <legend>Editing Village_{editor.idx}</legend>
          <label>
            Scenario
            <select
              value={editor.scenario}
              onChange={(e) => setEditor({ ...editor, scenario: e.target.value })}
            >
              <option value="">(none)</option>
              {scenarios.map((s) => <option key={s}>{s}</option>)}
            </select>
          </label>
          <label>
            Min gold
            <input type="number" value={editor.min_gold}
                   onChange={(e) => setEditor({ ...editor, min_gold: Number(e.target.value) || 0 })} />
          </label>
          <label>
            Min elixir
            <input type="number" value={editor.min_elixir}
                   onChange={(e) => setEditor({ ...editor, min_elixir: Number(e.target.value) || 0 })} />
          </label>
          <label>
            Min dark
            <input type="number" value={editor.min_dark_elixir}
                   onChange={(e) => setEditor({ ...editor, min_dark_elixir: Number(e.target.value) || 0 })} />
          </label>
          <span className="mv-hint">
            Load a village to edit its config; Save writes it; Apply switches
            the game to that account and locks the row.
          </span>
        </fieldset>
      )}

      <div className="mv-footer">
        <button className="mv-danger" onClick={handleDeleteAll}>Delete All</button>
        <span className="mv-hint">
          Wipes every village's saved config, snapshots and stats — the tab starts over.
        </span>
      </div>
    </div>
  );
}
