import type { Graph } from "./types.ts";
/** Deterministic layering; cycles remain visible in a separate bounded column. */
export function graphLayout(graph: Graph) {
  const ids = new Set(graph.nodes.map((n) => n.id));
  const indegree = new Map([...ids].map((id) => [id, 0]));
  const children = new Map<string, string[]>();
  for (const e of graph.edges) {
    if (!ids.has(e.source) || !ids.has(e.target)) continue;
    indegree.set(e.target, indegree.get(e.target)! + 1);
    children.set(e.source, [...(children.get(e.source) || []), e.target]);
  }
  const queue = [...ids].filter((id) => indegree.get(id) === 0).sort();
  const levels = new Map(queue.map((id) => [id, 0]));
  for (let index = 0; index < queue.length; index++) {
    const id = queue[index];
    for (const child of children.get(id) || []) {
      levels.set(child, Math.max(levels.get(child) || 0, levels.get(id)! + 1));
      indegree.set(child, indegree.get(child)! - 1);
      if (indegree.get(child) === 0) queue.push(child);
    }
  }
  const resolved = new Set(queue);
  const cycleLevel = Math.max(0, ...levels.values()) + 1;
  const slots = new Map<number, number>();
  return [...graph.nodes]
    .sort((a, b) => a.id.localeCompare(b.id))
    .map((node) => {
      const level = resolved.has(node.id) ? levels.get(node.id)! : cycleLevel;
      const row = slots.get(level) || 0;
      slots.set(level, row + 1);
      return { ...node, position: { x: level * 114, y: row * 140 } };
    });
}
