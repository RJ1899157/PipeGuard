"use client";
import { useMemo, useEffect, useRef, useState, useCallback, memo } from "react";
import {
  ReactFlow,
  Controls,
  Handle,
  Position,
  MarkerType,
  type NodeProps,
  type ReactFlowInstance,
  type NodeChange,
  type EdgeChange,
} from "@xyflow/react";
import { DatabaseIcon, GearSixIcon } from "@phosphor-icons/react";
import type { Graph, GraphNode } from "@/lib/types";
import { graphLayout } from "@/lib/graph-layout";
function LineageNode({ data, selected }: NodeProps) {
  const node = data as unknown as GraphNode;
  const Icon = node.kind === "dataset" ? DatabaseIcon : GearSixIcon;
  return (
    <div className={`lineage-node ${node.kind} ${selected ? "selected" : ""}`}>
      <Handle type="target" position={Position.Left} />
      <Icon size={25} aria-hidden />
      <strong title={node.name}>{node.name}</strong>
      <span>{node.kind === "dataset" ? "Dataset" : "Step execution"}</span>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
const nodeTypes = { lineage: LineageNode };
function Lineage({
  graph,
  selected,
  onSelect,
  selectedEdge,
  onEdgeSelect,
  onClear,
}: {
  graph: Graph;
  selected: string | null;
  onSelect: (id: string) => void;
  selectedEdge: number | null;
  onEdgeSelect: (index: number) => void;
  onClear: () => void;
}) {
  const started = useMemo(() => performance.now(), [graph]);
  const container = useRef<HTMLDivElement>(null);
  const [instance, setInstance] = useState<ReactFlowInstance | null>(null);
  useEffect(() => {
    if (!instance || !container.current) return;
    const observer = new ResizeObserver(() => {
      void instance.fitView({ padding: 0.12 });
    });
    observer.observe(container.current);
    return () => observer.disconnect();
  }, [instance]);
  const selectionChanged = useCallback(
    (changes: NodeChange[]) => {
      const change = changes.find(
        (change) => change.type === "select" && change.selected,
      );
      if (change?.type === "select") onSelect(change.id);
    },
    [onSelect],
  );
  const positioned = useMemo(() => graphLayout(graph), [graph]);
  const nodes = useMemo(
    () =>
      positioned.map((n) => ({
        id: n.id,
        type: "lineage",
        position: n.position,
        data: { ...n },
        selected: n.id === selected,
        ariaLabel: `${n.kind}: ${n.name}`,
      })),
    [positioned, selected],
  );
  const names = useMemo(
    () => new Map(graph.nodes.map((n) => [n.id, n.name])),
    [graph],
  );
  useEffect(() => {
    if (!instance || !container.current) return;
    const element = container.current;
    delete element.dataset.readyMs;
    let frame = 0,
      tries = 0;
    const check = () => {
      const nodes = [
        ...element.querySelectorAll<HTMLElement>(".react-flow__node"),
      ];
      if (
        nodes.length === graph.nodes.length &&
        nodes.every((n) => {
          const bounds = n.getBoundingClientRect();
          return (
            bounds.width > 0 &&
            bounds.height > 0 &&
            getComputedStyle(n).visibility !== "hidden"
          );
        })
      ) {
        frame = requestAnimationFrame(() => {
          element.dataset.readyMs = (performance.now() - started).toFixed(1);
          element.dataset.nodeCount = String(nodes.length);
        });
      } else if (tries++ < 180) frame = requestAnimationFrame(check);
    };
    frame = requestAnimationFrame(check);
    return () => cancelAnimationFrame(frame);
  }, [instance, graph, started]);
  const edges = useMemo(
    () =>
      graph.edges.map((e, i) => ({
        id: `edge-${i}`,
        source: e.source,
        target: e.target,
        markerEnd: { type: MarkerType.ArrowClosed, color: "#8790a5" },
        selected: i === selectedEdge,
        style: {
          stroke: i === selectedEdge ? "#6250df" : "#8790a5",
          strokeWidth: i === selectedEdge ? 2.5 : 1,
        },
        ariaLabel: `${names.get(e.source)} to ${names.get(e.target)}`,
      })),
    [graph, names, selectedEdge],
  );
  return (
    <div
      ref={container}
      className="graph-canvas"
      aria-label="Interactive lineage diagram"
      onKeyDownCapture={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          onClear();
        }
      }}
    >
      <ReactFlow
        key={`${graph.as_of}:${graph.nodes.map((n) => n.id).join(",")}`}
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onInit={setInstance}
        onPaneClick={onClear}
        onNodesChange={selectionChanged}
        onEdgesChange={(changes: EdgeChange[]) => {
          const change = changes.find((c) => c.type === "select" && c.selected);
          if (change?.type === "select") {
            const index = Number(change.id.replace("edge-", ""));
            if (
              Number.isSafeInteger(index) &&
              index >= 0 &&
              index < graph.edges.length
            )
              onEdgeSelect(index);
          }
        }}
        fitView
        fitViewOptions={{ padding: 0.12 }}
        minZoom={0.04}
        maxZoom={2}
        nodesDraggable={false}
        nodesConnectable={false}
        edgesReconnectable={false}
        deleteKeyCode={null}
        onNodeClick={(_, n) => onSelect(n.id)}
        onEdgeClick={(_, e) => onEdgeSelect(Number(e.id.replace("edge-", "")))}
        nodesFocusable
        edgesFocusable
        ariaLabelConfig={{
          "controls.fitView.ariaLabel": "Fit lineage to view",
        }}
      >
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}

export default memo(Lineage);
