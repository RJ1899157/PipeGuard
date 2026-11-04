"use client";
import { useMemo, useState } from "react";
import { filterGraph, type NodeKindFilter } from "@/lib/graph-filter";
import type { Graph } from "@/lib/types";

export function GraphText({
  graph,
  onNodeSelect,
  onEdgeSelect,
}: {
  graph: Graph;
  onNodeSelect: (id: string) => void;
  onEdgeSelect: (index: number) => void;
}) {
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState<NodeKindFilter>("all");
  const { nodes, links } = useMemo(
    () => filterGraph(graph, search, kind),
    [graph, search, kind],
  );
  const names = useMemo(
    () => new Map(graph.nodes.map((node) => [node.id, node.name])),
    [graph],
  );
  return (
    <details className="text-alternative">
      <summary>
        Text view of lineage · {graph.nodes.length} nodes / {graph.edges.length}{" "}
        links
      </summary>
      <p>
        Search to inspect dense graphs without reading tiny labels. Filtering
        this list does not remove graph data or evidence.
      </p>
      <label className="quality-picker" htmlFor="lineage-node-search">
        Search nodes by name, namespace or ID
        <input
          id="lineage-node-search"
          aria-label="Search nodes by name, namespace or ID"
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </label>
      <label className="quality-picker" htmlFor="lineage-node-type">
        Node type
        <select
          id="lineage-node-type"
          aria-label="Node type"
          value={kind}
          onChange={(event) => setKind(event.target.value as NodeKindFilter)}
        >
          <option value="all">All node types</option>
          <option value="dataset">Datasets</option>
          <option value="step">Step executions</option>
        </select>
      </label>
      <button
        onClick={() => {
          setSearch("");
          setKind("all");
        }}
        disabled={!search && kind === "all"}
      >
        Clear node filters
      </button>
      <p role="status">
        {nodes.length} of {graph.nodes.length} nodes match · {links.length} of{" "}
        {graph.edges.length} links touch matching nodes.
      </p>
      {nodes.length === 0 ? (
        <p>
          No matching nodes. Change or clear the filters to inspect other
          retained records.
        </p>
      ) : (
        <ul>
          {nodes.map((node) => (
            <li key={node.id}>
              <button
                onClick={() => onNodeSelect(node.id)}
                aria-label={`Inspect ${node.kind}: ${node.name}`}
              >
                {node.kind}: {node.name}
              </button>
            </li>
          ))}
        </ul>
      )}
      <h3>Observed links touching matching nodes</h3>
      <ul>
        {links.map(({ edge, index }) => (
          <li key={index}>
            <button
              className="text-button"
              onClick={() => onEdgeSelect(index)}
              aria-label={`Dependency: ${names.get(edge.source)} to ${names.get(edge.target)}`}
            >
              {names.get(edge.source)} → {names.get(edge.target)}
            </button>
          </li>
        ))}
      </ul>
    </details>
  );
}
