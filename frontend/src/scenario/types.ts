// Mirrors the deploy-scenario JSON consumed by BattleScreen._slot_deploy
// (backend/screens/battle_screen.py) and required_composition
// (backend/engine/composition.py).

export type DeployType = "troop" | "super_troop" | "spell" | "siege" | "hero" | "delay";
export type Strategy = "line" | "points" | "delay";

// One deploy slot. Fields depend on type/strategy:
//  - delay:  strategy "delay" + seconds
//  - points: points [[x,y],…]   (tapped in order, wraps if taps > len)
//  - line:   x1,y1,x2,y2        (taps spread along the line; taps=1 = midpoint)
export interface DeployNode {
  id: string;
  label: string;
  type: DeployType;
  after: string[];
  template?: string; // units/<folder>/<name>; omitted for delay
  taps?: number; // troop/spell/siege count = taps
  strategy?: Strategy;
  points?: [number, number][];
  x1?: number;
  y1?: number;
  x2?: number;
  y2?: number;
  seconds?: number; // delay
  // editor-only canvas position (persisted so layout survives round-trips)
  x?: number;
  y?: number;
}

export interface Variant {
  name: string;
  weight: number;
  nodes: DeployNode[];
}

export interface ScenarioDoc {
  name: string;
  variants: Variant[];
}

// Result of GET /api/scenarios/{name}/composition (Composition.to_json()).
export interface Composition {
  troops: Record<string, number>;
  spells: Record<string, number>;
  sieges: Record<string, number>;
  heroes: string[];
}

export const DEPLOY_TYPES: DeployType[] = ["troop", "super_troop", "spell", "siege", "hero", "delay"];

// Mirror of backend required_composition: per template, sum taps within a
// variant, then take the MAX across variants (deploy picks one variant). Used
// for the editor's "will train" preview without a round-trip.
export function composeFromVariants(variants: Variant[]): Composition {
  const counted: Record<"troop" | "spell" | "siege", Record<string, number>> = {
    troop: {},
    spell: {},
    siege: {},
  };
  const heroes = new Set<string>();
  for (const v of variants) {
    const perVariant: Record<"troop" | "spell" | "siege", Record<string, number>> = {
      troop: {},
      spell: {},
      siege: {},
    };
    for (const node of v.nodes) {
      const tpl = node.template;
      if (!tpl) continue;
      if (node.type === "hero") {
        heroes.add(tpl);
      } else if (
        node.type === "troop" ||
        node.type === "super_troop" ||
        node.type === "spell" ||
        node.type === "siege"
      ) {
        // Super troops occupy regular troop slots, so they count as troops.
        const bucket = node.type === "super_troop" ? "troop" : node.type;
        const pv = perVariant[bucket];
        pv[tpl] = (pv[tpl] ?? 0) + (node.taps ?? 0);
      }
    }
    for (const k of ["troop", "spell", "siege"] as const) {
      for (const [tpl, n] of Object.entries(perVariant[k])) {
        counted[k][tpl] = Math.max(counted[k][tpl] ?? 0, n);
      }
    }
  }
  return {
    troops: counted.troop,
    spells: counted.spell,
    sieges: counted.siege,
    heroes: [...heroes].sort(),
  };
}

export function formatComposition(c: Composition): string {
  const fmt = (d: Record<string, number>) =>
    Object.entries(d)
      .map(([t, n]) => `${t.split("/").pop()}×${n}`)
      .join(", ") || "—";
  return `troops[${fmt(c.troops)}] spells[${fmt(c.spells)}] sieges[${fmt(c.sieges)}]`;
}

// Folder under assets/units/ for each deployable type's templates.
export const TYPE_FOLDER: Record<Exclude<DeployType, "delay">, string> = {
  troop: "units/troops",
  super_troop: "units/super_troops",
  spell: "units/spells",
  siege: "units/siege",
  hero: "units/heroes",
};
