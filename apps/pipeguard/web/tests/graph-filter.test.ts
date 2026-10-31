import { test } from "node:test";
import assert from "node:assert/strict";
import { filterGraph } from "../lib/graph-filter.ts";
import { performanceGraph } from "../lib/exploration-fixtures.ts";

test("graph search preserves all data and original dependency indices", () => {
  const graph = performanceGraph();
  const before = JSON.stringify(graph);
  const all = filterGraph(graph, "", "all");
  assert.equal(all.nodes.length, 200);
  assert.equal(all.links.length, 1000);
  const found = filterGraph(graph, " FIXTURE-199 ", "step");
  assert.equal(found.nodes.length, 1);
  assert.equal(found.nodes[0].id, graph.nodes[199].id);
  assert.ok(found.links.length > 0);
  for (const { edge, index } of found.links) {
    assert.equal(edge, graph.edges[index]);
    assert.ok(
      edge.source === found.nodes[0].id || edge.target === found.nodes[0].id,
    );
  }
  assert.equal(JSON.stringify(graph), before);
});

test("type, namespace, ID and empty matches are explicit", () => {
  const graph = performanceGraph(true);
  assert.equal(filterGraph(graph, "", "dataset").nodes.length, 100);
  assert.equal(filterGraph(graph, "", "step").nodes.length, 100);
  assert.equal(
    filterGraph(graph, "synthetic-performance-fixture", "all").nodes.length,
    200,
  );
  assert.equal(filterGraph(graph, "step:fixture-199", "all").nodes.length, 1);
  assert.deepEqual(filterGraph(graph, "absent", "all"), {
    nodes: [],
    links: [],
  });
  assert.deepEqual(filterGraph({ ...graph, nodes: [], edges: [] }, "", "all"), {
    nodes: [],
    links: [],
  });
});
