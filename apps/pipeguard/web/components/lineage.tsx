"use client";
import { useMemo, useEffect, useRef, useState, useCallback } from "react";
import {
  ReactFlow,
  Controls,
  Handle,
  Position,
  MarkerType,
  type NodeProps,
  type ReactFlowInstance,
  type NodeChange,
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
      <strong>{node.name}</strong>
      <span>{node.kind === "dataset" ? "Dataset" : "Step execution"}</span>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
const nodeTypes = { lineage: LineageNode };
export default function Lineage({
  graph,
  selected,
  onSelect,
}: {
  graph: Graph;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
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
  const nodes = useMemo(
    () =>
      graphLayout(graph).map((n) => ({
        id: n.id,
        type: "lineage",
        position: n.position,
        data: { ...n },
        selected: n.id === selected,
        ariaLabel: `${n.kind}: ${n.name}`,
      })),
    [graph, selected],
  );
  const edges = useMemo(
    () =>
      graph.edges.map((e, i) => ({
        id: `edge-${i}`,
        source: e.source,
        target: e.target,
        markerEnd: { type: MarkerType.ArrowClosed, color: "#8790a5" },
        style: { stroke: "#8790a5" },
        ariaLabel: `${graph.nodes.find((n) => n.id === e.source)?.name} to ${graph.nodes.find((n) => n.id === e.target)?.name}`,
      })),
    [graph],
  );
  return (
    <div
      ref={container}
      className="graph-canvas"
      aria-label="Interactive lineage diagram"
    >
      <ReactFlow
        key={`${graph.as_of}:${graph.nodes.map((n) => n.id).join(",")}`}
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onInit={setInstance}
        onNodesChange={selectionChanged}
        fitView
        fitViewOptions={{ padding: 0.12 }}
        minZoom={0.25}
        maxZoom={2}
        nodesDraggable={false}
        nodesConnectable={false}
        edgesReconnectable={false}
        deleteKeyCode={null}
        onNodeClick={(_, n) => onSelect(n.id)}
        onEdgeClick={(_, e) => onSelect(e.source)}
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
