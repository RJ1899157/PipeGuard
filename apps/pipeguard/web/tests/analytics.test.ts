import { test } from "node:test";
import assert from "node:assert/strict";
import {
  qualityCounts,
  conflictingRules,
  timelineRows,
  timelineOffsetStyle,
} from "../lib/analytics.ts";
import {
  qualityFixture,
  performanceGraph,
} from "../lib/exploration-fixtures.ts";
import { graphLayout } from "../lib/graph-layout.ts";
import type { Attempt } from "../lib/types.ts";
const report = qualityFixture("job", "run", 2, true);
test("timeline offsets remain invisible when ARIA enables decal patterns", () => {
  assert.equal(timelineOffsetStyle.opacity, 0);
  assert.equal(timelineOffsetStyle.color, "transparent");
  assert.deepEqual(timelineOffsetStyle.decal, {
    symbol: "none",
    color: "transparent",
    backgroundColor: "transparent",
  });
});
const attempt = (start: string | null, end: string | null): Attempt => ({
  id: "attempt",
  run_id: "run",
  attempt_number: 1,
  attempt_key: "1",
  state: "failed",
  projection_source: "producer",
  error_code: "source_unavailable",
  reconciliation_required: false,
  started_at: start,
  finished_at: end,
});
test("quality counts retain all five outcomes without inventing failures", () => {
  assert.deepEqual(
    qualityCounts(report[0]).map((c) => c.count),
    [1, 1, 1, 1, 1],
  );
  assert.equal(report[0].payload.checks[2].failures, null);
  assert.equal(report[0].payload.inventory_complete, false);
  assert.equal(
    qualityCounts({
      ...report[0],
      payload: { ...report[0].payload, checks: [] },
    }).reduce((n, c) => n + c.count, 0),
    0,
  );
});
test("contradictory report statuses are scoped to attempt and rule version", () => {
  assert.equal(conflictingRules(report), 4);
  assert.equal(conflictingRules([report[0]]), 0);
  assert.equal(
    conflictingRules([
      report[0],
      { ...report[1], payload: { ...report[1].payload, attempt_number: 3 } },
    ]),
    0,
  );
  assert.equal(
    conflictingRules([
      report[0],
      {
        ...report[1],
        payload: {
          ...report[1].payload,
          checks: report[1].payload.checks.map((c) => ({
            ...c,
            rule_version: "b".repeat(64),
          })),
        },
      },
    ]),
    0,
  );
});
test("timeline preserves gaps and exact zero without fabricating unfinished intervals", () => {
  const result = timelineRows([
    attempt("2026-10-31T09:00:00Z", "2026-10-31T09:00:03Z"),
    attempt("2026-10-31T09:01:00Z", "2026-10-31T09:01:08Z"),
    attempt("2026-10-31T09:02:00Z", null),
    attempt(null, null),
    attempt("invalid", "invalid"),
    attempt("2026-10-31T09:00:03Z", "2026-10-31T09:00:00Z"),
    attempt("2026-10-31T09:02:00Z", "2026-10-31T09:02:00Z"),
  ]);
  assert.equal(result.omitted, 4);
  assert.deepEqual(
    result.rows.map((r) => r.offsetSeconds),
    [0, 60, 120],
  );
  assert.deepEqual(
    result.rows.map((r) => r.durationSeconds),
    [3, 8, 0],
  );
  assert.equal(timelineRows([]).origin, null);
});
test("representative bounded fixtures retain all nodes, bipartite edges and cycles", () => {
  for (const cycle of [false, true]) {
    const graph = performanceGraph(cycle);
    assert.equal(graph.nodes.length, 200);
    assert.equal(graph.edges.length, cycle ? 200 : 1000);
    const nodes = new Map(graph.nodes.map((n) => [n.id, n]));
    for (const edge of graph.edges)
      assert.notEqual(
        nodes.get(edge.source)!.kind,
        nodes.get(edge.target)!.kind,
      );
    assert.equal(graphLayout(graph).length, 200);
    assert.equal(graph.coverage, "partial");
  }
});

test("dependency evidence stays on the selected link instead of neighboring links", async () => {
  const { graphEvidence } = await import("../lib/graph-evidence.ts");
  const graph = performanceGraph();
  const ref = (id: string) => ({
    event_id: id,
    payload_hash: "a".repeat(64),
    basis: "declared",
    event_type: "COMPLETE",
    occurred_at: "2026-10-31T09:15:08Z",
    received_at: "2026-10-31T09:15:10Z",
  });
  graph.edges[0].evidence = [ref("first")];
  graph.edges[1].evidence = [ref("second")];
  assert.deepEqual(
    graphEvidence(graph, graph.edges[0].source, 0).map((r) => r.event_id),
    ["first"],
  );
  assert.deepEqual(
    graphEvidence(graph, graph.edges[0].source, null).map((r) => r.event_id),
    ["first", "second"],
  );
  assert.deepEqual(graphEvidence(graph, graph.edges[0].source, 9999), []);
});

test("selected dependency identity survives link insertion and reorder", async () => {
  const { selectedEdgeIndex, graphEvidence } =
    await import("../lib/graph-evidence.ts");
  const graph = performanceGraph();
  const selected = {
    source: graph.edges[3].source,
    target: graph.edges[3].target,
  };
  const evidence = {
    event_id: "selected-evidence",
    payload_hash: "a".repeat(64),
    basis: "declared",
    event_type: "COMPLETE",
    occurred_at: "2026-10-31T09:15:08Z",
    received_at: "2026-10-31T09:15:10Z",
  };
  graph.edges[3].evidence = [evidence];
  graph.edges.reverse();
  graph.edges.unshift({
    source: "late-source",
    target: "late-target",
    evidence: [],
  });
  const index = selectedEdgeIndex(graph, selected);
  assert.notEqual(index, null);
  assert.notEqual(index, 3);
  assert.deepEqual(graphEvidence(graph, selected.source, index), [evidence]);
  assert.equal(
    selectedEdgeIndex(graph, { source: "missing", target: "missing" }),
    null,
  );
  assert.equal(selectedEdgeIndex(null, selected), null);
  assert.equal(selectedEdgeIndex(graph, null), null);
});
