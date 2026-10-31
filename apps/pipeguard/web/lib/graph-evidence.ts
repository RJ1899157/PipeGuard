import type { Graph, Evidence } from "./types.ts";
export function selectedEdgeIndex(
  graph: Graph | null | undefined,
  selection: { source: string; target: string } | null,
): number | null {
  if (!graph || !selection) return null;
  const index = graph.edges.findIndex(
    (edge) =>
      edge.source === selection.source && edge.target === selection.target,
  );
  return index < 0 ? null : index;
}
export function graphEvidence(
  graph: Graph | null | undefined,
  nodeId: string | undefined,
  edgeIndex: number | null,
): Evidence[] {
  if (!graph) return [];
  const links =
    edgeIndex === null
      ? graph.edges.filter((e) => e.source === nodeId || e.target === nodeId)
      : graph.edges[edgeIndex]
        ? [graph.edges[edgeIndex]]
        : [];
  const refs = new Map<string, Evidence>();
  for (const e of links)
    for (const ref of e.evidence)
      if (!refs.has(ref.event_id)) refs.set(ref.event_id, ref);
  return [...refs.values()];
}
