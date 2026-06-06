import { useCallback, useEffect, useRef, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  addEdge,
  useNodesState,
  useEdgesState,
  type Connection,
  type Node,
  type NodeTypes,
  type ReactFlowInstance,
} from "reactflow";

import {
  listScenarios,
  getScenario,
  saveScenario,
  deleteScenario,
  fetchAssets,
} from "../api/client";
import type { Variant, DeployNode as DeployNodeT } from "./types";
import { composeFromVariants, formatComposition } from "./types";
import { DeployNode, type DeployNodeData } from "./DeployNode";
import { toVariant, fromVariant, layoutNodes } from "./serialize";
import { DeployParamPanel } from "./DeployParamPanel";
import { DeviceCanvas } from "../device/DeviceCanvas";

type PickReq = { id: string; mode: "points" | "line" };

const nodeTypes: NodeTypes = { deploy: DeployNode };

const emptyVariant = (name = "Default"): Variant => ({ name, weight: 1, nodes: [] });

export function ScenarioEditor({
  onStatus,
  active = true,
}: {
  onStatus: (s: string) => void;
  active?: boolean; // mount the ReactFlow canvas only while the tab is visible
}) {
  const [saved, setSaved] = useState<string[]>([]);
  const [name, setName] = useState("untitled");
  const [variants, setVariants] = useState<Variant[]>([emptyVariant()]);
  const [vIdx, setVIdx] = useState(0);
  const [assets, setAssets] = useState<string[]>([]);

  const [nodes, setNodes, onNodesChange] = useNodesState<DeployNodeData>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pick, setPick] = useState<PickReq | null>(null);
  const idSeq = useRef(0);
  const rfRef = useRef<ReactFlowInstance | null>(null);

  const refreshList = useCallback(
    () => listScenarios().then(setSaved).catch(() => setSaved([])),
    []
  );
  useEffect(() => {
    refreshList();
    fetchAssets().then(setAssets).catch(() => setAssets([]));
  }, [refreshList]);

  // Load the selected variant into the canvas.
  const loadVariant = useCallback(
    (variant: Variant) => {
      const { nodes: ns, edges: es } = fromVariant(variant);
      for (const n of ns) {
        const m = /_(\d+)$/.exec(n.id);
        if (m) idSeq.current = Math.max(idSeq.current, Number(m[1]) + 1);
      }
      setNodes(ns);
      setEdges(es);
      setSelectedId(null);
    },
    [setNodes, setEdges]
  );

  // Persist the current canvas back into variants[vIdx] before switching away.
  const captureCanvas = useCallback((): Variant[] => {
    const updated = [...variants];
    if (updated[vIdx]) {
      updated[vIdx] = { ...updated[vIdx], nodes: toVariant(nodes, edges) };
    }
    return updated;
  }, [variants, vIdx, nodes, edges]);

  const doLoad = useCallback(
    async (n: string) => {
      if (!n) return;
      try {
        const doc = await getScenario(n);
        const vs = doc.variants.length ? doc.variants : [emptyVariant()];
        setName(doc.name || n);
        setVariants(vs);
        setVIdx(0);
        loadVariant(vs[0]);
        onStatus(`Loaded scenario "${n}" (${vs.length} variant(s)).`);
      } catch (e) {
        onStatus(`Load failed: ${(e as Error).message}`);
      }
    },
    [loadVariant, onStatus]
  );

  const doNew = useCallback(() => {
    setName("untitled");
    setVariants([emptyVariant()]);
    setVIdx(0);
    setNodes([]);
    setEdges([]);
    setSelectedId(null);
    onStatus("New scenario.");
  }, [setNodes, setEdges, onStatus]);

  const doSave = useCallback(async () => {
    const nm = name.trim();
    if (!nm) {
      onStatus("Enter a scenario name first.");
      return;
    }
    const vs = captureCanvas();
    try {
      await saveScenario(nm, { name: nm, variants: vs });
      setVariants(vs);
      onStatus(`Saved scenario "${nm}".`);
      refreshList();
    } catch (e) {
      onStatus(`Save failed: ${(e as Error).message}`);
    }
  }, [name, captureCanvas, refreshList, onStatus]);

  const doDelete = useCallback(async () => {
    const nm = name.trim();
    if (!nm || !saved.includes(nm)) {
      onStatus("Nothing to delete.");
      return;
    }
    try {
      await deleteScenario(nm);
      onStatus(`Deleted scenario "${nm}".`);
      doNew();
      refreshList();
    } catch (e) {
      onStatus(`Delete failed: ${(e as Error).message}`);
    }
  }, [name, saved, doNew, refreshList, onStatus]);

  // --- variant management ---------------------------------------------------
  const switchVariant = useCallback(
    (idx: number) => {
      const vs = captureCanvas();
      setVariants(vs);
      setVIdx(idx);
      loadVariant(vs[idx]);
    },
    [captureCanvas, loadVariant]
  );

  const addVariant = useCallback(() => {
    const vs = captureCanvas();
    const nv = [...vs, emptyVariant(`Variant ${vs.length + 1}`)];
    setVariants(nv);
    setVIdx(nv.length - 1);
    loadVariant(nv[nv.length - 1]);
  }, [captureCanvas, loadVariant]);

  const removeVariant = useCallback(() => {
    if (variants.length <= 1) {
      onStatus("A scenario needs at least one variant.");
      return;
    }
    const vs = captureCanvas().filter((_, i) => i !== vIdx);
    const ni = Math.max(0, vIdx - 1);
    setVariants(vs);
    setVIdx(ni);
    loadVariant(vs[ni]);
  }, [variants, captureCanvas, vIdx, loadVariant, onStatus]);

  const setVariantField = useCallback(
    (patch: Partial<Variant>) =>
      setVariants((vs) => vs.map((v, i) => (i === vIdx ? { ...v, ...patch } : v))),
    [vIdx]
  );

  // --- canvas ---------------------------------------------------------------
  const onConnect = useCallback(
    (c: Connection) => setEdges((es) => addEdge({ ...c, type: "default" }, es)),
    [setEdges]
  );

  // Tidy the canvas: re-place nodes by dependency level (after-edges) so chains
  // run top-to-bottom and branches fan out left-to-right.
  const autoLayout = useCallback(() => {
    setNodes((ns) => layoutNodes(ns, edges));
  }, [edges, setNodes]);

  const addNode = useCallback(() => {
    const id = `n_${idSeq.current++}`;
    // Drop the new node in the middle of the visible canvas so it's never
    // off-screen (a fixed position lands outside the viewport after panning /
    // auto-layout). Fall back to a fixed spot before the instance is ready.
    const inst = rfRef.current;
    const cv = inst?.screenToFlowPosition
      ? (() => {
          const el = document.querySelector(".scenario-canvas");
          const r = el?.getBoundingClientRect();
          return r
            ? inst.screenToFlowPosition({ x: r.left + r.width / 2, y: r.top + r.height / 2 })
            : { x: 200, y: 200 };
        })()
      : { x: 200, y: 200 };
    const node: Node<DeployNodeData> = {
      id,
      type: "deploy",
      position: cv,
      data: {
        node: {
          id,
          label: "New unit",
          type: "troop",
          after: [],
          template: "",
          taps: 1,
          strategy: "line",
        },
      },
    };
    setNodes((ns) => [...ns, node]);
    setSelectedId(id);
  }, [setNodes]);

  const updateNode = useCallback(
    (id: string, patch: Partial<DeployNodeT>) =>
      setNodes((ns) =>
        ns.map((n) =>
          n.id === id ? { ...n, data: { ...n.data, node: { ...n.data.node, ...patch } } } : n
        )
      ),
    [setNodes]
  );

  const deleteNode = useCallback(
    (id: string) => {
      setNodes((ns) => ns.filter((n) => n.id !== id));
      setEdges((es) => es.filter((e) => e.source !== id && e.target !== id));
      setSelectedId((cur) => (cur === id ? null : cur));
    },
    [setNodes, setEdges]
  );

  const onSelectionChange = useCallback(({ nodes: sel }: { nodes: Node[] }) => {
    setSelectedId(sel.length === 1 ? sel[0].id : null);
  }, []);

  const selectedNode = nodes.find((n) => n.id === selectedId) ?? null;
  const variant = variants[vIdx];
  const variantWeight = variant?.weight ?? 1;

  // Live "will train" preview: current canvas folded back into the variant set.
  const preview = formatComposition(composeFromVariants(captureCanvas()));

  // --- pick deploy coords on the live device (shared DeviceCanvas) ----------
  const pickNode = pick ? nodes.find((n) => n.id === pick.id)?.data.node ?? null : null;
  const onPickPoint = useCallback(
    (x: number, y: number) => {
      if (!pick) return;
      const cur = nodes.find((n) => n.id === pick.id)?.data.node;
      updateNode(pick.id, { points: [...(cur?.points ?? []), [x, y] as [number, number]] });
    },
    [pick, nodes, updateNode]
  );
  const onPickLine = useCallback(
    (x1: number, y1: number, x2: number, y2: number) => {
      if (!pick) return;
      updateNode(pick.id, { x1, y1, x2, y2 });
      setPick(null); // a line is one drag — done
    },
    [pick, updateNode]
  );

  return (
    <div className="scenario-editor">
      <div className="scenario-bar">
        <select
          value={saved.includes(name) ? name : ""}
          onChange={(e) => doLoad(e.target.value)}
          title="Load a scenario"
        >
          <option value="">Load…</option>
          {saved.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <input
          className="graph-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="scenario name"
        />
        <button onClick={doSave}>Save</button>
        <button onClick={doNew}>New</button>
        <button className="danger-inline" onClick={doDelete}>
          Delete
        </button>

        <span className="toolbar-sep" />

        <span className="muted">variant</span>
        <select value={vIdx} onChange={(e) => switchVariant(Number(e.target.value))}>
          {variants.map((v, i) => (
            <option key={i} value={i}>
              {v.name}
            </option>
          ))}
        </select>
        <input
          className="variant-name"
          value={variant?.name ?? ""}
          onChange={(e) => setVariantField({ name: e.target.value })}
          placeholder="variant name"
        />
        <label className="weight">
          weight
          <input
            type="number"
            min={1}
            value={variantWeight}
            onChange={(e) => setVariantField({ weight: Number(e.target.value) || 1 })}
          />
        </label>
        <button onClick={addVariant}>+ Variant</button>
        <button onClick={removeVariant}>− Variant</button>

        <span className="toolbar-sep" />
        <button onClick={addNode}>+ Unit</button>
        <button onClick={autoLayout} title="Tidy node positions by dependency order">
          ⤓ Auto-layout
        </button>
      </div>

      <div className="scenario-preview">
        <span className="muted">will train:</span> {preview}
      </div>

      <div className="scenario-body">
        <div className="scenario-center">
          {pick ? (
            <>
              <div className="asset-grid-bar">
                <span>
                  Pick {pick.mode} for {pickNode?.label ?? pick.id} —{" "}
                  {pick.mode === "points" ? "click to add a point" : "drag to set the line"}
                </span>
                <button onClick={() => setPick(null)}>Done</button>
              </div>
              <div className="asset-capture-stage">
                <DeviceCanvas
                  mode={pick.mode}
                  onPoint={onPickPoint}
                  onLine={onPickLine}
                  overlayPoints={pickNode?.points}
                  overlayLine={
                    pickNode &&
                    pickNode.x1 !== undefined &&
                    pickNode.y1 !== undefined &&
                    pickNode.x2 !== undefined &&
                    pickNode.y2 !== undefined
                      ? [pickNode.x1, pickNode.y1, pickNode.x2, pickNode.y2]
                      : null
                  }
                  label="Battle"
                />
              </div>
            </>
          ) : (
            <div className="scenario-canvas">
              {/* Mount ReactFlow only while visible — mounting it inside a
                  display:none panel leaves it stuck at size 0 and it won't
                  render nodes when shown. Node state lives above, so it
                  survives the remount. */}
              {active && (
                <ReactFlow
                  nodes={nodes}
                  edges={edges}
                  nodeTypes={nodeTypes}
                  onNodesChange={onNodesChange}
                  onEdgesChange={onEdgesChange}
                  onConnect={onConnect}
                  onSelectionChange={onSelectionChange}
                  onInit={(inst) => (rfRef.current = inst)}
                  fitView
                  deleteKeyCode={["Backspace", "Delete"]}
                  proOptions={{ hideAttribution: true }}
                >
                  <Background />
                  <Controls />
                </ReactFlow>
              )}
            </div>
          )}
        </div>
        <div className="scenario-right">
          <DeployParamPanel
            node={selectedNode?.data.node ?? null}
            assets={assets}
            onChange={updateNode}
            onDelete={deleteNode}
            onPickPoints={(id) => setPick({ id, mode: "points" })}
            onPickLine={(id) => setPick({ id, mode: "line" })}
          />
        </div>
      </div>
    </div>
  );
}
