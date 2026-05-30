import { useCallback, useEffect, useRef, useState } from "react";
import type { GraphDoc } from "../blocks/types";
import { wsUrl } from "../api/ws";
import type { NodeRunState } from "./RunStateContext";

export interface LogLine {
  level: string;
  name: string;
  msg: string;
}

export interface RunnerState {
  connected: boolean;
  running: boolean;
  status: string; // "", "running", "ok", "error", "stopped", "invalid", "busy"
  runState: Map<string, NodeRunState>;
  logs: LogLine[];
  vars: Record<string, unknown>;
}

const MAX_LOGS = 500;

const initial: RunnerState = {
  connected: false,
  running: false,
  status: "",
  runState: new Map(),
  logs: [],
  vars: {},
};

// Owns the /ws/run socket and folds the event stream into render state.
export function useRunner() {
  const [state, setState] = useState<RunnerState>(initial);
  const wsRef = useRef<WebSocket | null>(null);

  const handle = useCallback((ev: any) => {
    setState((s) => {
      switch (ev.type) {
        case "started":
          return { ...s, status: "running", running: true };
        case "node": {
          const runState = new Map(s.runState);
          runState.set(ev.id, ev.state as NodeRunState);
          return { ...s, runState };
        }
        case "log":
          return {
            ...s,
            logs: [...s.logs, { level: ev.level, name: ev.name, msg: ev.msg }].slice(
              -MAX_LOGS
            ),
          };
        case "vars":
          return { ...s, vars: ev.vars ?? {} };
        case "done":
          return {
            ...s,
            running: false,
            status: ev.status ?? "done",
            logs: ev.error
              ? [...s.logs, { level: "ERROR", name: "run", msg: String(ev.error) }].slice(
                  -MAX_LOGS
                )
              : s.logs,
          };
        case "error":
          return {
            ...s,
            logs: [...s.logs, { level: "ERROR", name: "run", msg: String(ev.error) }].slice(
              -MAX_LOGS
            ),
          };
        default:
          return s;
      }
    });
  }, []);

  const start = useCallback(
    (graph: GraphDoc) => {
      wsRef.current?.close();
      setState({ ...initial, connected: true, running: true, status: "connecting" });
      const ws = new WebSocket(wsUrl("/ws/run"));
      wsRef.current = ws;
      ws.onopen = () => ws.send(JSON.stringify({ cmd: "start", graph }));
      ws.onmessage = (e) => handle(JSON.parse(e.data));
      ws.onclose = () =>
        setState((s) => ({ ...s, connected: false, running: false }));
      ws.onerror = () =>
        setState((s) => ({
          ...s,
          status: s.status === "connecting" ? "ws error (backend up?)" : s.status,
        }));
    },
    [handle]
  );

  const stop = useCallback(() => {
    wsRef.current?.send(JSON.stringify({ cmd: "stop" }));
  }, []);

  const clear = useCallback(
    () => setState((s) => ({ ...s, logs: [], runState: new Map(), vars: {} })),
    []
  );

  useEffect(() => () => wsRef.current?.close(), []);

  return { ...state, start, stop, clear };
}
