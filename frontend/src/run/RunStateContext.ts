import { createContext } from "react";

export type NodeRunState = "running" | "done" | "error" | "skipped";

// nodeId -> latest run state. BlockNode reads this to highlight itself.
export const RunStateContext = createContext<Map<string, NodeRunState>>(new Map());
