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

test("large cycles use a compact grid and keep downstream components ordered", () => {
  const ids = Array.from({ length: 199 }, (_, i) => `cycle-${i}`);
  const links: [string, string][] = ids.map((id, i) => [
    id,
    ids[(i + 1) % ids.length],
  ]);
  links.push([ids[0], "downstream"]);
  const input = graph([...ids, "downstream"], links);
  const result = graphLayout(input);
  assert.equal(result.length, 200);
  const cycle = result.filter((node) => node.id !== "downstream");
  const maxX = Math.max(...cycle.map((node) => node.position.x));
  const maxY = Math.max(...cycle.map((node) => node.position.y));
  assert.ok(maxX < 1800);
  assert.ok(maxY < 2100);
  assert.ok(result.find((node) => node.id === "downstream")!.position.x > maxX);
  assert.equal(
    new Set(result.map((node) => JSON.stringify(node.position))).size,
    200,
  );
  assert.deepEqual(
    graphLayout({
      ...input,
      nodes: [...input.nodes].reverse(),
      edges: [...input.edges].reverse(),
    }),
    result,
  );
  assert.equal(input.edges.length, 200);
});

test("multiple cycles, self loops, duplicate links and unknown endpoints remain bounded", () => {
  const input = graph(
    ["a", "b", "c", "d", "e", "isolated"],
    [
      ["a", "b"],
      ["b", "a"],
      ["b", "c"],
      ["c", "d"],
      ["d", "c"],
      ["d", "e"],
      ["e", "e"],
      ["a", "b"],
      ["unknown", "a"],
    ],
  );
  const result = graphLayout(input);
  const pos = new Map(result.map((node) => [node.id, node.position]));
  assert.ok(pos.get("c")!.x > Math.max(pos.get("a")!.x, pos.get("b")!.x));
  assert.ok(pos.get("e")!.x > Math.max(pos.get("c")!.x, pos.get("d")!.x));
  assert.equal(
    new Set(result.map((node) => JSON.stringify(node.position))).size,
    6,
  );
  assert.equal(result.length, input.nodes.length);
  assert.equal(input.edges.length, 9);
});
