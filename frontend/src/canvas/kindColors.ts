import type { Kind } from "../blocks/types";

// One color per port Kind — drives handle + edge colors so types read at a glance.
export const KIND_COLORS: Record<Kind, string> = {
  Coord: "#e06c2b",   // orange
  Number: "#2b7de0",  // blue
  Template: "#8a2be2", // purple
  Region: "#1fa37a",  // teal
  Bool: "#d4356b",    // pink/red
  Text: "#7a7f87",    // gray
  Trigger: "#444b54", // dark (control flow)
};

export const kindColor = (k: Kind): string => KIND_COLORS[k] ?? "#888";
