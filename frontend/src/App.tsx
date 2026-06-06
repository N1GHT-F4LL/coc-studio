import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  addEdge,
  useNodesState,
  useEdgesState,
  type Connection,
  type Edge,
  type Node,
  type NodeTypes,
  type ReactFlowInstance,
} from "reactflow";
import "reactflow/dist/style.css";

import {
  fetchBlocks,
  listGraphs,
  loadGraph,
  saveGraph,
  fetchAssets,
  listScenarios,
  deviceStatus,
  type DeviceStatus,
} from "./api/client";
import type { BlockSpec } from "./blocks/types";
import { BlockNode, type BlockNodeData } from "./canvas/BlockNode";
import { parseHandle } from "./canvas/handleId";
import { kindColor } from "./canvas/kindColors";
import { validateConnection } from "./canvas/validation";
import { fromGraphDoc, toGraphDoc, layoutGraphNodes } from "./graph/serialize";
import { Palette } from "./panels/Palette";
import { ParamPanel } from "./panels/ParamPanel";
import { RunConsole } from "./panels/RunConsole";
import { TopBar, type AppMode } from "./panels/TopBar";
import { ScenarioEditor } from "./scenario/ScenarioEditor";
import { AssetManager } from "./asset/AssetManager";
import { DevicePanel } from "./panels/DevicePanel";
import { DeviceStreamProvider } from "./device/DeviceStreamContext";
import { RunStateContext } from "./run/RunStateContext";
import { useRunner } from "./run/useRunner";

const nodeTypes: NodeTypes = { block: BlockNode };

export default function App() {
  const [blocks, setBlocks] = useState<BlockSpec[]>([]);
  const [nodes, setNodes, onNodesChange] = useNodesState<BlockNodeData>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [graphName, setGraphName] = useState("untitled");
  const [savedGraphs, setSavedGraphs] = useState<string[]>([]);
  const [status, setStatus] = useState("");
  const [assets, setAssets] = useState<string[]>([]);
  const [scenarios, setScenarios] = useState<string[]>([]);
  const [device, setDevice] = useState<DeviceStatus | null>(null);
  const [mode, setMode] = useState<AppMode>("editor");
  const runner = useRunner();

  const refreshDevice = useCallback(
    () => deviceStatus().then(setDevice).catch(() => setDevice(null)),
    []
  );

  const rfRef = useRef<ReactFlowInstance | null>(null);
  const idSeq = useRef(0);
  // isValidConnection captures edges via ref to avoid stale closures.
  const edgesRef = useRef<Edge[]>([]);
  edgesRef.current = edges;

  const specByType = useMemo(
    () => new Map(blocks.map((b) => [b.type, b])),
    [blocks]
  );

  useEffect(() => {
    fetchBlocks()
      .then(setBlocks)
      .catch((e) => setStatus(`Failed to load blocks: ${e.message}`));
    refreshGraphs();
    fetchAssets().then(setAssets).catch(() => setAssets([]));
    listScenarios().then(setScenarios).catch(() => setScenarios([]));
  }, []);

  // Poll device status for the top-bar light. Device state only changes on
  // explicit Connect/Disconnect, so a slow poll is plenty; pause it while the
  // tab is hidden to avoid pointless background requests.
  useEffect(() => {
    let id: ReturnType<typeof setInterval> | null = null;
    const start = () => {
      if (id !== null) return;
      refreshDevice();
      id = setInterval(refreshDevice, 8000);
    };
    const stop = () => {
      if (id !== null) {
        clearInterval(id);
        id = null;
      }
    };
    const onVisibility = () => (document.hidden ? stop() : start());
    if (!document.hidden) start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [refreshDevice]);

  const refreshAssets = () => fetchAssets().then(setAssets).catch(() => setAssets([]));

  const refreshGraphs = () =>
    listGraphs()
      .then(setSavedGraphs)
      .catch(() => setSavedGraphs([]));

  const newId = (type: string) => `${type}_${idSeq.current++}`;

  const addBlock = useCallback(
    (spec: BlockSpec) => {
      const inst = rfRef.current;
      const origin = inst
        ? inst.screenToFlowPosition({ x: window.innerWidth / 3, y: 140 })
        : { x: 160, y: 140 };
      const id = newId(spec.type);
      // Pre-fill params with the spec defaults so the node works out of the box.
      const params: Record<string, unknown> = {};
      for (const p of spec.inputs) {
        if (p.default !== null && p.default !== undefined) params[p.name] = p.default;
      }
      setNodes((ns) => {
        // Cascade new nodes so they don't stack on top of each other.
        const step = 36;
        const k = ns.length % 12;
        const node: Node<BlockNodeData> = {
          id,
          type: "block",
          position: { x: origin.x + k * step, y: origin.y + k * step },
          data: { spec, label: spec.label, params },
        };
        return ns.concat(node);
      });
    },
    [setNodes]
  );

  const onConnect = useCallback(
    (c: Connection) => {
      if (!validateConnection(c, edgesRef.current)) {
        setStatus("Invalid connection (type mismatch or would create a cycle).");
        return;
      }
      const src = parseHandle(c.sourceHandle);
      const color = src?.flow === "data" ? kindColor(src.kind) : "#444b54";
      setEdges((es) =>
        addEdge(
          {
            ...c,
            style: { stroke: color, strokeWidth: 2 },
            ...(src?.flow === "control" ? { animated: true } : {}),
          },
          es
        )
      );
      setStatus("");
    },
    [setEdges]
  );

  const isValidConnection = useCallback(
    (c: Connection) => validateConnection(c, edgesRef.current),
    []
  );

  const onSelectionChange = useCallback(
    ({ nodes: sel }: { nodes: Node[] }) => setSelectedId(sel[0]?.id ?? null),
    []
  );

  const changeParam = useCallback(
    (nodeId: string, name: string, value: unknown) =>
      setNodes((ns) =>
        ns.map((n) =>
          n.id === nodeId
            ? { ...n, data: { ...n.data, params: { ...n.data.params, [name]: value } } }
            : n
        )
      ),
    [setNodes]
  );

  const changeLabel = useCallback(
    (nodeId: string, label: string) =>
      setNodes((ns) =>
        ns.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, label } } : n))
      ),
    [setNodes]
  );

  const deleteNode = useCallback(
    (nodeId: string) => {
      setNodes((ns) => ns.filter((n) => n.id !== nodeId));
      setEdges((es) => es.filter((e) => e.source !== nodeId && e.target !== nodeId));
      setSelectedId((cur) => (cur === nodeId ? null : cur));
    },
    [setNodes, setEdges]
  );

  const doSave = useCallback(async () => {
    const name = graphName.trim();
    if (!name) {
      setStatus("Enter a graph name first.");
      return;
    }
    try {
      await saveGraph(name, toGraphDoc(name, nodes, edges));
      setStatus(`Saved "${name}".`);
      refreshGraphs();
    } catch (e) {
      setStatus(`Save failed: ${(e as Error).message}`);
    }
  }, [graphName, nodes, edges]);

  const doLoad = useCallback(
    async (name: string) => {
      if (!name) return;
      try {
        const doc = await loadGraph(name);
        const { nodes: ns, edges: es } = fromGraphDoc(doc, specByType);
        // Keep id sequence ahead of loaded ids to avoid collisions.
        for (const n of ns) {
          const m = /_(\d+)$/.exec(n.id);
          if (m) idSeq.current = Math.max(idSeq.current, Number(m[1]) + 1);
        }
        setNodes(ns);
        setEdges(es);
        setGraphName(doc.name || name);
        setSelectedId(null);
        setStatus(`Loaded "${name}" (${ns.length} nodes).`);
      } catch (e) {
        setStatus(`Load failed: ${(e as Error).message}`);
      }
    },
    [specByType, setNodes, setEdges]
  );

  const onRun = useCallback(() => {
    if (nodes.length === 0) {
      setStatus("Nothing to run — add some blocks first.");
      return;
    }
    setStatus("");
    runner.start(toGraphDoc(graphName.trim() || "untitled", nodes, edges));
    // Run connects the device itself; refresh the light shortly after.
    setTimeout(refreshDevice, 2000);
  }, [nodes, edges, graphName, runner, refreshDevice]);

  const onAutoLayout = useCallback(() => {
    setNodes((ns) => layoutGraphNodes(ns, edgesRef.current));
  }, [setNodes]);

  const onNew = useCallback(() => {
    setNodes([]);
    setEdges([]);
    setSelectedId(null);
    setStatus("New graph.");
  }, [setNodes, setEdges]);

  const selectedNode = nodes.find((n) => n.id === selectedId) ?? null;
  // Input ports of the selected node that are driven by a data edge (literal overridden).
  const connectedInputs = useMemo(() => {
    const s = new Set<string>();
    if (!selectedNode) return s;
    for (const e of edges) {
      if (e.target !== selectedNode.id) continue;
      const h = parseHandle(e.targetHandle);
      if (h?.flow === "data") s.add(h.port);
    }
    return s;
  }, [edges, selectedNode]);

  return (
    <div className="app">
      <TopBar
        mode={mode}
        onMode={setMode}
        graphName={graphName}
        savedGraphs={savedGraphs}
        onRename={setGraphName}
        onLoad={doLoad}
        onSave={doSave}
        onNew={onNew}
        onAutoLayout={onAutoLayout}
        running={runner.running}
        status={runner.status}
        onRun={onRun}
        onStop={runner.stop}
        device={device}
        message={status}
      />

      <DeviceStreamProvider
        connected={!!device?.connected}
        onGotoDevice={() => setMode("device")}
      >
      {mode === "scenario" && <ScenarioEditor onStatus={setStatus} />}
      {mode === "asset" && (
        <AssetManager onMessage={setStatus} onAssetsChanged={refreshAssets} />
      )}
      {mode === "device" && (
        <DevicePanel device={device} onStatus={setDevice} onMessage={setStatus} />
      )}

      <div className="body" style={mode !== "editor" ? { display: "none" } : undefined}>
        <Palette blocks={blocks} onAdd={addBlock} />
        <div className="center">
          <div className="canvas">
            <RunStateContext.Provider value={runner.runState}>
              <ReactFlow
                nodes={nodes}
                edges={edges}
                nodeTypes={nodeTypes}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                isValidConnection={isValidConnection}
                onSelectionChange={onSelectionChange}
                onInit={(inst) => (rfRef.current = inst)}
                fitView
                deleteKeyCode={["Backspace", "Delete"]}
                proOptions={{ hideAttribution: true }}
              >
                <Background />
                <Controls />
              </ReactFlow>
            </RunStateContext.Provider>
          </div>
          <div className="dock">
            <div className="dock-tabs">
              <span className="dock-title">Run console</span>
            </div>
            <div className="dock-body">
              <div className="dock-pane">
                <RunConsole
                  running={runner.running}
                  status={runner.status}
                  logs={runner.logs}
                  vars={runner.vars}
                  onClear={runner.clear}
                />
              </div>
            </div>
          </div>
        </div>
        <div className="right">
          <ParamPanel
            node={selectedNode}
            connectedInputs={connectedInputs}
            assets={assets}
            graphs={savedGraphs}
            scenarios={scenarios}
            onChangeParam={changeParam}
            onChangeLabel={changeLabel}
            onDelete={deleteNode}
          />
        </div>
      </div>
      </DeviceStreamProvider>
    </div>
  );
}
