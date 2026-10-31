import type { Graph } from "./types.ts";
export type NodeKindFilter = "all" | "dataset" | "step";

/** Preserve original edge indices so filtered keyboard controls inspect the same evidence. */
export function filterGraph(
  graph: Graph,
  search: string,
  kind: NodeKindFilter,
) {
  const query = search.trim().toLowerCase();
  const nodes = graph.nodes.filter(
    (node) =>
      (kind === "all" || node.kind === kind) &&
      `${node.name}\n${node.namespace}\n${node.id}`
        .toLowerCase()
        .includes(query),
  );
  const visible = new Set(nodes.map((node) => node.id));
  const links = graph.edges.flatMap((edge, index) =>
    visible.has(edge.source) || visible.has(edge.target)
      ? [{ edge, index }]
      : [],
  );
  return { nodes, links };
}
