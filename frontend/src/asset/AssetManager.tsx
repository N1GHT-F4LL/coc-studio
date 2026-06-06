import { useEffect, useMemo, useState } from "react";
import {
  fetchAssets,
  fetchAssetCategories,
  thumbUrl,
  saveCrop,
  moveAsset,
  deleteAsset,
  assetUsage,
  type AssetCategory,
} from "../api/client";
import { DeviceCanvas } from "../device/DeviceCanvas";

interface Props {
  onMessage: (m: string) => void;
  onAssetsChanged: () => void; // tell App to refresh its asset list (ParamPanel combobox)
}

// Splits a full asset key (folder/name) into [folder, name].
function splitKey(key: string): [string, string] {
  const i = key.lastIndexOf("/");
  return i < 0 ? ["", key] : [key.slice(0, i), key.slice(i + 1)];
}

// Asset manager tab: browse by category, capture from the device, rename /
// recategorise, replace the image, delete. Mirrors the asset studio that used to
// live in the Bot Builder device dock, now a first-class tab with full CRUD.
export function AssetManager({ onMessage, onAssetsChanged }: Props) {
  const [cats, setCats] = useState<AssetCategory[]>([]);
  const [assets, setAssets] = useState<string[]>([]);
  const [cat, setCat] = useState<string>(""); // selected folder ("" = all)
  const [selected, setSelected] = useState<string | null>(null);

  // Edit fields for the selected asset.
  const [editName, setEditName] = useState("");
  const [editFolder, setEditFolder] = useState("");

  // Capture/replace flow: when set, the device canvas is in crop mode and a
  // captured region is pending a name+folder before saving.
  const [mode, setMode] = useState<"idle" | "capture" | "replace">("idle");
  const [pendingRegion, setPendingRegion] = useState<number[] | null>(null);
  const [pendingPreview, setPendingPreview] = useState<string>(""); // data-URL of the crop
  const [newName, setNewName] = useState("");
  const [newFolder, setNewFolder] = useState("");

  const refresh = () =>
    fetchAssets()
      .then(setAssets)
      .catch(() => setAssets([]));

  useEffect(() => {
    fetchAssetCategories()
      .then((cs) => {
        setCats(cs);
        if (cs.length) setNewFolder((f) => f || cs[0].folder);
      })
      .catch(() => setCats([]));
    refresh();
  }, []);

  const shown = useMemo(
    () => (cat ? assets.filter((a) => a.startsWith(cat + "/")) : assets),
    [assets, cat]
  );

  const clearPending = () => {
    setPendingRegion(null);
    setPendingPreview("");
  };

  const select = (key: string) => {
    setSelected(key);
    const [folder, name] = splitKey(key);
    setEditFolder(folder);
    setEditName(name);
    setMode("idle");
    clearPending();
  };

  // Warn (but don't block) when an asset is referenced by graphs/scenarios.
  const confirmWithUsage = async (key: string, verb: string): Promise<boolean> => {
    let extra = "";
    try {
      const u = await assetUsage(key);
      const refs = [...u.graphs.map((g) => `graph ${g}`), ...u.scenarios.map((s) => `scenario ${s}`)];
      if (refs.length) extra = `\n\nCurrently used by:\n• ${refs.join("\n• ")}\n→ this will orphan the reference.`;
    } catch {
      /* usage scan best-effort */
    }
    return window.confirm(`${verb} "${key}"?${extra}`);
  };

  const doRename = async () => {
    if (!selected) return;
    const key = `${editFolder}/${editName}`;
    if (key === selected) {
      onMessage("Name/category unchanged.");
      return;
    }
    if (!(await confirmWithUsage(selected, "Rename / recategorise"))) return;
    try {
      const res = await moveAsset(selected, editFolder, editName);
      onMessage(`Moved → ${res.key}.`);
      await refresh();
      onAssetsChanged();
      setSelected(res.key);
    } catch (e) {
      onMessage(`Rename failed: ${(e as Error).message}`);
    }
  };

  const doDelete = async () => {
    if (!selected) return;
    if (!(await confirmWithUsage(selected, "Delete asset"))) return;
    try {
      await deleteAsset(selected);
      onMessage(`Deleted ${selected}.`);
      setSelected(null);
      await refresh();
      onAssetsChanged();
    } catch (e) {
      onMessage(`Delete failed: ${(e as Error).message}`);
    }
  };

  // Crop captured → keep the region outlined + show a preview, fill the save
  // form. Capture = new asset; replace = same key.
  const onCrop = (region: number[], preview: string) => {
    setPendingRegion(region);
    setPendingPreview(preview);
    if (mode === "replace" && selected) {
      const [folder, name] = splitKey(selected);
      setNewFolder(folder);
      setNewName(name);
    }
  };

  const doSaveCrop = async () => {
    if (!pendingRegion) return;
    try {
      const res = await saveCrop(pendingRegion, newFolder, newName);
      onMessage(`Saved ${res.key} (${res.width}×${res.height}).`);
      clearPending();
      setMode("idle");
      if (mode !== "replace") setNewName("");
      await refresh();
      onAssetsChanged();
      setSelected(res.key);
    } catch (e) {
      onMessage(`Save failed: ${(e as Error).message}`);
    }
  };

  const capturing = mode !== "idle"; // capture/replace takes over the centre area

  return (
    <div className="asset-tab">
      {/* Sidebar: categories */}
      <aside className="asset-sidebar">
        <div className="asset-side-title">Categories</div>
        <button className={cat === "" ? "active" : ""} onClick={() => setCat("")}>
          All ({assets.length})
        </button>
        {cats.map((c) => {
          const n = assets.filter((a) => a.startsWith(c.folder + "/")).length;
          return (
            <button
              key={c.folder}
              className={cat === c.folder ? "active" : ""}
              onClick={() => setCat(c.folder)}
            >
              {c.label} ({n})
            </button>
          );
        })}
      </aside>

      {/* Centre: thumbnail grid, OR the live device crop surface while capturing. */}
      <div className="asset-grid-wrap">
        <div className="asset-grid-bar">
          {capturing ? (
            <>
              <span>{mode === "replace" ? `Replace ${selected}` : "Capture a new asset"} — drag a rectangle on the screen</span>
              <button onClick={() => { setMode("idle"); clearPending(); }}>Cancel</button>
            </>
          ) : (
            <>
              <span>{shown.length} assets</span>
              <button
                className="run"
                onClick={() => { setMode("capture"); clearPending(); setNewName(""); }}
              >
                + Capture from device
              </button>
            </>
          )}
        </div>
        {capturing ? (
          <div className="asset-capture-stage">
            <DeviceCanvas mode="crop" onCrop={onCrop} committedRegion={pendingRegion} label="Crop" />
          </div>
        ) : (
          <div className="asset-grid">
            {shown.map((key) => (
              <button
                key={key}
                className={`asset-cell${selected === key ? " active" : ""}`}
                onClick={() => select(key)}
                title={key}
              >
                <img src={thumbUrl(key)} alt={key} loading="lazy" />
                <span className="asset-cell-name">{splitKey(key)[1]}</span>
              </button>
            ))}
            {shown.length === 0 && <div className="muted">No assets in this category.</div>}
          </div>
        )}
      </div>

      {/* Detail / actions */}
      <aside className="asset-detail">
        {capturing ? (
          <>
            <div className="asset-side-title">
              {mode === "replace" ? "Replace image" : "New asset"}
            </div>
            {pendingRegion ? (
              <div className="asset-form">
                {pendingPreview && (
                  <img className="asset-preview" src={pendingPreview} alt="crop preview" />
                )}
                <div className="muted">region {pendingRegion.join(", ")}</div>
                <label className="field">
                  <span>Category</span>
                  <select value={newFolder} onChange={(e) => setNewFolder(e.target.value)}>
                    {cats.map((c) => (
                      <option key={c.folder} value={c.folder}>{c.label}</option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>Name</span>
                  <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="asset name" />
                </label>
                <div className="field-row">
                  <button className="run" disabled={!newName || !newFolder} onClick={doSaveCrop}>
                    Save asset
                  </button>
                  <button onClick={clearPending}>Redo crop</button>
                </div>
              </div>
            ) : (
              <div className="muted">Drag a rectangle on the device screen to capture a region.</div>
            )}
          </>
        ) : !selected ? (
          <div className="muted">Select an asset to view / edit, or capture a new one.</div>
        ) : (
          <>
            <div className="asset-side-title">{splitKey(selected)[1]}</div>
            <img className="asset-preview" src={thumbUrl(selected)} alt={selected} />
            <div className="param-meta">
              <span className="muted">key</span> {selected}
            </div>
            <label className="field">
              <span>Name</span>
              <input value={editName} onChange={(e) => setEditName(e.target.value)} />
            </label>
            <label className="field">
              <span>Category</span>
              <select value={editFolder} onChange={(e) => setEditFolder(e.target.value)}>
                {cats.map((c) => (
                  <option key={c.folder} value={c.folder}>{c.label}</option>
                ))}
              </select>
            </label>
            <div className="field-row">
              <button onClick={doRename}>Rename / category</button>
              <button onClick={() => { setMode("replace"); clearPending(); }}>Replace image</button>
            </div>
            <button className="danger" onClick={doDelete}>Delete asset</button>
          </>
        )}
      </aside>
    </div>
  );
}
