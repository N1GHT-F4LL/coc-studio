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

export async function listScenarios(): Promise<string[]> {
  const data = await json<{ scenarios: string[] }>(await fetch("/api/scenarios"));
  return data.scenarios;
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

// --- scenarios -------------------------------------------------------------
import type { ScenarioDoc, Composition } from "../scenario/types";

export async function getScenario(name: string): Promise<ScenarioDoc> {
  return json<ScenarioDoc>(await fetch(`/api/scenarios/${encodeURIComponent(name)}`));
}

export async function saveScenario(name: string, doc: ScenarioDoc): Promise<void> {
  await json<{ ok: boolean }>(
    await fetch(`/api/scenarios/${encodeURIComponent(name)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(doc),
    })
  );
}

export async function deleteScenario(name: string): Promise<void> {
  await json<{ ok: boolean }>(
    await fetch(`/api/scenarios/${encodeURIComponent(name)}`, { method: "DELETE" })
  );
}

export async function scenarioComposition(name: string): Promise<Composition> {
  return json<Composition>(
    await fetch(`/api/scenarios/${encodeURIComponent(name)}/composition`)
  );
}

// --- device ----------------------------------------------------------------
export interface DeviceStatus {
  connected: boolean;
  available: boolean;
  serial: string | null;
  profile: string | null;
  assets_loaded: boolean;
  reason: string | null;
}

export async function deviceStatus(): Promise<DeviceStatus> {
  return json<DeviceStatus>(await fetch("/api/device/status"));
}

export async function connectDevice(): Promise<{
  ok: boolean;
  reason: string;
  status: DeviceStatus;
}> {
  return json(await fetch("/api/device/connect", { method: "POST" }));
}

export interface DeviceProfiles {
  profiles: { value: string; label: string }[];
  current: string;
  endpoint: string;
}

export async function deviceProfiles(): Promise<DeviceProfiles> {
  return json<DeviceProfiles>(await fetch("/api/device/profiles"));
}

export async function setDeviceProfile(
  profile: string,
  endpoint?: string
): Promise<{ ok: boolean; profile: string; endpoint: string }> {
  return json(
    await fetch("/api/device/profile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile, endpoint }),
    })
  );
}

export interface AdbDevice {
  serial: string;
  state: string; // "device" | "offline" | "unauthorized" | ...
}

export async function scanDevices(): Promise<{ devices: AdbDevice[]; status: DeviceStatus }> {
  return json(await fetch("/api/device/scan"));
}

export async function launchEmulator(): Promise<{ launched: boolean; running: boolean }> {
  return json(await fetch("/api/device/launch", { method: "POST" }));
}

export async function disconnectDevice(): Promise<{ ok: boolean; status: DeviceStatus }> {
  return json(await fetch("/api/device/disconnect", { method: "POST" }));
}

export async function selectSerial(
  serial: string
): Promise<{ ok: boolean; serial: string; status: DeviceStatus }> {
  return json(
    await fetch("/api/device/serial", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ serial }),
    })
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
