import { useMemo } from "react";
import type { BlockSpec } from "../blocks/types";

interface Props {
  blocks: BlockSpec[];
  onAdd: (spec: BlockSpec) => void;
}

export function Palette({ blocks, onAdd }: Props) {
  const grouped = useMemo(() => {
    const m = new Map<string, BlockSpec[]>();
    for (const b of blocks) {
      if (!m.has(b.category)) m.set(b.category, []);
      m.get(b.category)!.push(b);
    }
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [blocks]);

  return (
    <aside className="palette">
      <h2>Blocks</h2>
      {blocks.length === 0 && <div className="muted">Loading… (is the backend up?)</div>}
      {grouped.map(([cat, specs]) => (
        <div key={cat} className="palette-group">
          <div className="palette-cat">{cat}</div>
          {specs.map((s) => (
            <button
              key={s.type}
              className="palette-item"
              title={s.type}
              onClick={() => onAdd(s)}
            >
              {s.label}
            </button>
          ))}
        </div>
      ))}
    </aside>
  );
}
