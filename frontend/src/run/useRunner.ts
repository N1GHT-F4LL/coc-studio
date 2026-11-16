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
  paused: boolean;
  status: string; // "", "running", "ok", "error", "stopped", "invalid", "busy"
  runState: Map<string, NodeRunState>;
  logs: LogLine[];
  vars: Record<string, unknown>;
}

const MAX_LOGS = 500;

const initial: RunnerState = {
  connected: false,
  running: false,
  paused: false,
  status: "",
  runState: new Map(),
  logs: [],
  vars: {},
};

interface Opts {
  // Invoked when we (re)attach to an already-running run that carries its graph,
  // so the editor can load it and show live node highlights.
  onAttachGraph?: (graph: GraphDoc) => void;
}

// Owns the /ws/run socket and folds the event stream into render state. The
// socket is opened on mount (not just on Run) so a reload reattaches to a run
// still in progress server-side: the server replies with a "snapshot" event
// that rebuilds logs/vars/status/node-state and (if running) the graph.
export function useRunner(opts: Opts = {}) {
  const [state, setState] = useState<RunnerState>(initial);
  const wsRef = useRef<WebSocket | null>(null);
  const closedRef = useRef(false); // true once intentionally torn down (unmount)
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attachRef = useRef(opts.onAttachGraph);
  attachRef.current = opts.onAttachGraph;

  const handle = useCallback((ev: any) => {
    if (ev.type === "snapshot") {
      const runState = new Map<string, NodeRunState>();
      for (const [id, st] of Object.entries(ev.nodes ?? {})) {
        runState.set(id, st as NodeRunState);
      }
      setState((s) => ({
        ...s,
        running: !!ev.running,
        paused: !!ev.paused || ev.status === "paused",
        status: ev.status ?? "",
        runState,
        vars: ev.vars ?? {},
        logs: (ev.logs ?? [])
          .map((l: any) => ({ level: l.level, name: l.name, msg: l.msg }))
          .slice(-MAX_LOGS),
      }));
      // Reattach: load the running graph so node highlights line up.
      if (ev.running && ev.graph && attachRef.current) {
        attachRef.current(ev.graph as GraphDoc);
      }
      return;
    }

    setState((s) => {
      switch (ev.type) {
        case "started":
          return { ...s, status: "running", running: true, paused: false };
        case "paused":
          return { ...s, status: "paused", paused: true };
        case "resumed":
          return { ...s, status: "running", paused: false };
        case "node": {
          const runState = new Map(s.runState);
          runState.set(ev.id, ev.state as NodeRunState);
          return { ...s, runState };
        }
        case "log":
          return {
            ...s,
            // name defaults for hub-published events ([STOP]) that skip the
            // logging handler — a missing name must never reach the renderer.
            logs: [...s.logs, { level: ev.level ?? "INFO", name: ev.name ?? "run", msg: ev.msg }]
              .slice(-MAX_LOGS),
          };
        case "mv_active":
          // the rotation switched the game account — the Multi-Village tab
          // listens for this to re-point its editor at the real village
          window.dispatchEvent(new CustomEvent("mv-active", { detail: ev.idx }));
          return s;
        case "vars":
          return { ...s, vars: ev.vars ?? {} };
        case "done":
          return {
            ...s,
            running: false,
            paused: false,
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

  // Open (or reuse) the shared socket; auto-reconnect so a dropped/restarted
  // backend re-attaches and replays a fresh snapshot.
  const connect = useCallback((): WebSocket => {
    const cur = wsRef.current;
    if (cur && (cur.readyState === WebSocket.OPEN || cur.readyState === WebSocket.CONNECTING)) {
      return cur;
    }
    const ws = new WebSocket(wsUrl("/ws/run"));
    wsRef.current = ws;
    ws.onopen = () => setState((s) => ({ ...s, connected: true }));
    ws.onmessage = (e) => handle(JSON.parse(e.data));
    ws.onclose = () => {
      wsRef.current = null;
      setState((s) => ({ ...s, connected: false }));
      if (!closedRef.current && retryRef.current === null) {
        retryRef.current = setTimeout(() => {
          retryRef.current = null;
          connect();
        }, 1500);
      }
    };
    ws.onerror = () => {
      /* onclose fires next; reconnect handled there */
    };
    return ws;
  }, [handle]);

  useEffect(() => {
    closedRef.current = false;
    connect();
    return () => {
      closedRef.current = true;
      if (retryRef.current !== null) {
        clearTimeout(retryRef.current);
        retryRef.current = null;
      }
      wsRef.current?.close();
    };
  }, [connect]);

  const start = useCallback(
    (graph: GraphDoc) => {
      // Fresh run: clear the previous run's logs/state but keep the connection.
      setState((s) => ({ ...initial, connected: s.connected, running: true, status: "connecting" }));
      const payload = JSON.stringify({ cmd: "start", graph });
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(payload);
      } else {
        const w = connect();
        w.addEventListener("open", () => w.send(payload), { once: true });
      }
    },
    [connect]
  );

  const stop = useCallback(() => {
    wsRef.current?.send(JSON.stringify({ cmd: "stop" }));
  }, []);

  const pause = useCallback(() => {
    wsRef.current?.send(JSON.stringify({ cmd: "pause" }));
  }, []);

  const resume = useCallback(() => {
    wsRef.current?.send(JSON.stringify({ cmd: "resume" }));
  }, []);

  const clear = useCallback(
    () => setState((s) => ({ ...s, logs: [], runState: new Map(), vars: {} })),
    []
  );

  return { ...state, start, stop, pause, resume, clear };
}
