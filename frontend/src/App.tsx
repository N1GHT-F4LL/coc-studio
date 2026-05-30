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

import { fetchBlocks, listGraphs, loadGraph, saveGraph, fetchAssets } from "./api/client";
import type { BlockSpec } from "./blocks/types";
import { BlockNode, type BlockNodeData } from "./canvas/BlockNode";
import { parseHandle } from "./canvas/handleId";
import { kindColor } from "./canvas/kindColors";
import { validateConnection } from "./canvas/validation";
import { fromGraphDoc, toGraphDoc } from "./graph/serialize";
import { Palette } from "./panels/Palette";
import { ParamPanel } from "./panels/ParamPanel";
import { RunConsole } from "./panels/RunConsole";
import { DeviceView } from "./panels/DeviceView";
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
  const [pickReq, setPickReq] = useState<{ port: string; kind: "Coord" | "Region" } | null>(null);
  const runner = useRunner();

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
  }, []);

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
      setNodes((ns) => {
        // Cascade new nodes so they don't stack on top of each other.
        const step = 36;
        const k = ns.length % 12;
        const node: Node<BlockNodeData> = {
          id,
          type: "block",
          position: { x: origin.x + k * step, y: origin.y + k * step },
          data: { spec, label: spec.label, params: {} },
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
  }, [nodes, edges, graphName, runner]);

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
      <header className="toolbar">
        <strong>coc-studio</strong>
        <input
          className="graph-name"
          value={graphName}
          onChange={(e) => setGraphName(e.target.value)}
          placeholder="graph name"
        />
        <button onClick={doSave}>Save</button>
        <select
          value=""
          onChange={(e) => doLoad(e.target.value)}
          title="Load a saved graph"
        >
          <option value="">Load…</option>
          {savedGraphs.map((g) => (
            <option key={g} value={g}>
              {g}
            </option>
          ))}
        </select>
        <button
          onClick={() => {
            setNodes([]);
            setEdges([]);
            setSelectedId(null);
            setStatus("New graph.");
          }}
        >
          New
        </button>
        <span className="status">{status}</span>
      </header>

      <div className="body">
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
          <RunConsole
            running={runner.running}
            status={runner.status}
            logs={runner.logs}
            vars={runner.vars}
            onStart={onRun}
            onStop={runner.stop}
            onClear={runner.clear}
          />
        </div>
        <div className="right">
          <ParamPanel
            node={selectedNode}
            connectedInputs={connectedInputs}
            assets={assets}
            onChangeParam={changeParam}
            onChangeLabel={changeLabel}
            onDelete={deleteNode}
            onPick={(port, kind) => {
              if (!selectedNode) return;
              setPickReq({ port, kind });
              setStatus(`Pick ${kind} on the device view…`);
            }}
          />
          <DeviceView
            pickKind={pickReq?.kind ?? null}
            onPick={(value) => {
              if (pickReq && selectedNode) changeParam(selectedNode.id, pickReq.port, value);
              setPickReq(null);
              setStatus("");
            }}
            onAssetSaved={refreshAssets}
          />
        </div>
      </div>
    </div>
  );
}
