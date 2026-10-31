import { test } from "node:test";
import assert from "node:assert/strict";
import { graphLayout } from "../lib/graph-layout.ts";
import type { Graph } from "../lib/types.ts";
function graph(ids: string[], links: [string, string][]): Graph {
  return {
    nodes: ids.map((id) => ({
      id,
      kind: "dataset",
      namespace: "test",
      name: id,
    })),
    edges: links.map(([source, target]) => ({ source, target, evidence: [] })),
    coverage: "partial",
    missing_metadata: [],
    truncated: false,
    event_count: 0,
    semantics: "observed_union",
    as_of: "",
    known_at: "",
  };
}
test("branching graph retains all edges and positions parent before child", () => {
  const g = graph(
    ["a", "b", "c", "d"],
    [
      ["a", "b"],
      ["a", "c"],
      ["b", "d"],
      ["c", "d"],
    ],
  );
  const layout = graphLayout(g);
  const pos = new Map(layout.map((n) => [n.id, n.position]));
  assert.equal(layout.length, 4);
  for (const e of g.edges)
    assert.ok(pos.get(e.source)!.x < pos.get(e.target)!.x);
  assert.notDeepEqual(pos.get("b"), pos.get("c"));
});
test("cycle, disconnected node and empty graphs terminate without losing nodes", () => {
  const g = graph(
    ["a", "b", "isolated"],
    [
      ["a", "b"],
      ["b", "a"],
    ],
  );
  assert.equal(graphLayout(g).length, 3);
  assert.deepEqual(graphLayout(graph([], [])), []);
  assert.deepEqual(graphLayout(g), graphLayout(g));
});
test("200 node bounded graph has finite distinct positions", () => {
  const ids = Array.from({ length: 200 }, (_, i) => String(i));
  const layout = graphLayout(
    graph(
      ids,
      ids.slice(1).map((id, i) => [ids[i], id]),
    ),
  );
  assert.equal(layout.length, 200);
  assert.equal(
    new Set(layout.map((n) => JSON.stringify(n.position))).size,
    200,
  );
  assert.ok(
    layout.every(
      (n) => Number.isFinite(n.position.x) && Number.isFinite(n.position.y),
    ),
  );
});
