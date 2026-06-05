import { useEffect, useRef } from "react";
import type { LogLine } from "../run/useRunner";

interface Props {
  running: boolean;
  status: string;
  logs: LogLine[];
  vars: Record<string, unknown>;
  onClear: () => void;
}

const statusColor: Record<string, string> = {
  ok: "#1fa37a",
  error: "#d4356b",
  invalid: "#d4356b",
  stopped: "#e0a32b",
  busy: "#e0a32b",
  running: "#2b7de0",
};

export function RunConsole({ running, status, logs, vars, onClear }: Props) {
  const logRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [logs]);

  const varEntries = Object.entries(vars);

  return (
    <div className="run-console">
      <div className="run-bar">
        <span className="run-title">Run console</span>
        {status && (
          <span className="run-status" style={{ color: statusColor[status] ?? "#8b929c" }}>
            {running ? "● " : ""}
            {status}
          </span>
        )}
        <button onClick={onClear} disabled={running} style={{ marginLeft: "auto" }}>
          Clear
        </button>
      </div>
      <div className="run-body">
        <div className="run-logs" ref={logRef}>
          {logs.length === 0 && <div className="muted">No output yet. Press Run.</div>}
          {logs.map((l, i) => (
            <div key={i} className={`log log-${l.level.toLowerCase()}`}>
              <span className="log-level">{l.level}</span>
              <span className="log-name">{l.name.split(".").pop()}</span>
              <span className="log-msg">{l.msg}</span>
            </div>
          ))}
        </div>
        <div className="run-vars">
          <div className="run-vars-title">vars</div>
          {varEntries.length === 0 && <div className="muted">—</div>}
          {varEntries.map(([k, v]) => (
            <div key={k} className="var-row">
              <span className="var-key">{k}</span>
              <span className="var-val">{JSON.stringify(v)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
