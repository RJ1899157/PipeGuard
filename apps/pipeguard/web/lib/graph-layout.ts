import type { Graph } from "./types.ts";
/** Layer the component DAG, keeping each cycle in a compact, deterministic grid. */
export function graphLayout(graph: Graph) {
  const ids = [...new Set(graph.nodes.map((n) => n.id))].sort();
  const children = new Map(ids.map((id) => [id, new Set<string>()]));
  for (const edge of graph.edges)
    if (children.has(edge.source) && children.has(edge.target))
      children.get(edge.source)!.add(edge.target);
  const index = new Map<string, number>(),
    low = new Map<string, number>();
  const stack: string[] = [],
    active = new Set<string>(),
    groups: string[][] = [];
  function visit(id: string) {
    index.set(id, index.size);
    low.set(id, index.get(id)!);
    stack.push(id);
    active.add(id);
    for (const child of [...children.get(id)!].sort()) {
      if (!index.has(child)) {
        visit(child);
        low.set(id, Math.min(low.get(id)!, low.get(child)!));
      } else if (active.has(child))
        low.set(id, Math.min(low.get(id)!, index.get(child)!));
    }
    if (low.get(id) === index.get(id)) {
      const group: string[] = [];
      let member: string;
      do {
        member = stack.pop()!;
        active.delete(member);
        group.push(member);
      } while (member !== id);
      groups.push(group.sort());
    }
  }
  for (const id of ids) if (!index.has(id)) visit(id);
  groups.sort((a, b) => a[0].localeCompare(b[0]));
  const groupFor = new Map(
    groups.flatMap((group, i) => group.map((id) => [id, i] as const)),
  );
  const next = groups.map(() => new Set<number>()),
    indegree = groups.map(() => 0);
  for (const [id, targets] of children)
    for (const target of targets) {
      const sourceGroup = groupFor.get(id)!,
        targetGroup = groupFor.get(target)!;
      if (sourceGroup !== targetGroup && !next[sourceGroup].has(targetGroup)) {
        next[sourceGroup].add(targetGroup);
        indegree[targetGroup]++;
      }
    }
  const queue = groups.map((_, i) => i).filter((i) => indegree[i] === 0);
  const levels = groups.map(() => 0);
  for (let i = 0; i < queue.length; i++)
    for (const child of next[queue[i]]) {
      levels[child] = Math.max(levels[child], levels[queue[i]] + 1);
      if (--indegree[child] === 0) queue.push(child);
    }
  const widths = new Map<number, number>();
  for (let i = 0; i < groups.length; i++)
    widths.set(
      levels[i],
      Math.max(
        widths.get(levels[i]) || 1,
        Math.ceil(Math.sqrt(groups[i].length)),
      ),
    );
  const columns = new Map<number, number>();
  let column = 0;
  for (const level of [...widths.keys()].sort((a, b) => a - b)) {
    columns.set(level, column);
    column += widths.get(level)!;
  }
  const rows = new Map<number, number>(),
    positions = new Map<string, { x: number; y: number }>();
  for (let i = 0; i < groups.length; i++) {
    const level = levels[i],
      row = rows.get(level) || 0;
    const width = Math.ceil(Math.sqrt(groups[i].length));
    groups[i].forEach((id, j) =>
      positions.set(id, {
        x: (columns.get(level)! + (j % width)) * 114,
        y: (row + Math.floor(j / width)) * 140,
      }),
    );
    rows.set(level, row + Math.ceil(groups[i].length / width));
  }
  return [...graph.nodes]
    .sort((a, b) => a.id.localeCompare(b.id))
    .map((node) => ({ ...node, position: positions.get(node.id)! }));
}
