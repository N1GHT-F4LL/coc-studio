// Handle ids encode everything validation needs, so isValidConnection doesn't
// have to look nodes up:
//   control:  "ctl|in"  /  "ctl|out"  /  "ctl|out|<branch>"  (branch = if then/else)
//   data:     "data|in|<port>|<Kind>"  /  "data|out|<port>|<Kind>"
import type { Kind } from "../blocks/types";

export const CTL_IN = "ctl|in";
export const CTL_OUT = "ctl|out";

export const ctlOutBranch = (branch: string) => `ctl|out|${branch}`;

export const dataHandleId = (dir: "in" | "out", port: string, kind: Kind) =>
  `data|${dir}|${port}|${kind}`;

export type ParsedHandle =
  | { flow: "control"; dir: "in" | "out"; branch: string | null }
  | { flow: "data"; dir: "in" | "out"; port: string; kind: Kind };

export function parseHandle(id: string | null | undefined): ParsedHandle | null {
  if (!id) return null;
  const parts = id.split("|");
  if (parts[0] === "ctl")
    return { flow: "control", dir: parts[1] as "in" | "out", branch: parts[2] ?? null };
  if (parts[0] === "data")
    return {
      flow: "data",
      dir: parts[1] as "in" | "out",
      port: parts[2],
      kind: parts[3] as Kind,
    };
  return null;
}
