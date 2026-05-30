// REST clients for the FastAPI backend. Same-origin paths; the Vite dev proxy
// forwards /api to :8000 (see vite.config.ts), prod serves SPA from backend.
import type { BlockSpec, GraphDoc } from "../blocks/types";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* keep statusText */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

export async function fetchBlocks(): Promise<BlockSpec[]> {
  const data = await json<{ blocks: BlockSpec[] }>(await fetch("/api/blocks"));
  return data.blocks;
}

export async function listGraphs(): Promise<string[]> {
  const data = await json<{ graphs: string[] }>(await fetch("/api/graphs"));
  return data.graphs;
}

export async function loadGraph(name: string): Promise<GraphDoc> {
  return json<GraphDoc>(await fetch(`/api/graphs/${encodeURIComponent(name)}`));
}

export async function saveGraph(name: string, graph: GraphDoc): Promise<void> {
  await json<{ ok: boolean }>(
    await fetch(`/api/graphs/${encodeURIComponent(name)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(graph),
    })
  );
}

export async function deleteGraph(name: string): Promise<void> {
  await json<{ ok: boolean }>(
    await fetch(`/api/graphs/${encodeURIComponent(name)}`, { method: "DELETE" })
  );
}

// --- assets ----------------------------------------------------------------
export interface AssetCategory {
  label: string;
  folder: string;
}

export async function fetchAssets(): Promise<string[]> {
  const data = await json<{ assets: string[] }>(await fetch("/api/assets"));
  return data.assets;
}

export async function fetchAssetCategories(): Promise<AssetCategory[]> {
  const data = await json<{ categories: AssetCategory[] }>(
    await fetch("/api/assets/categories")
  );
  return data.categories;
}

export const thumbUrl = (key: string) =>
  `/api/assets/thumb/${key.split("/").map(encodeURIComponent).join("/")}`;

export async function saveCrop(
  region: number[],
  folder: string,
  name: string
): Promise<{ key: string; width: number; height: number }> {
  return json(
    await fetch("/api/assets/crop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ region, folder, name }),
    })
  );
}
