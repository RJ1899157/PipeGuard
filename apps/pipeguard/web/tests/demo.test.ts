import { test } from "node:test";
import assert from "node:assert/strict";
import { demoRead, demoGraph, demoAttempts, demoRun } from "../lib/demo.ts";
test("successful retry retains the failed attempt and independent lineage scopes", () => {
  assert.equal(demoRun.state, "succeeded");
  assert.equal(demoAttempts[0].state, "failed");
  assert.equal(demoAttempts[0].error_code, "source_unavailable");
  assert.equal(demoAttempts[1].state, "succeeded");
  const first = demoGraph(1),
    second = demoGraph(2);
  assert.equal(first.coverage, "partial");
  assert.equal(second.coverage, "reported_complete");
  assert.ok(
    first.edges[0].evidence[0].occurred_at <
      second.edges[0].evidence[0].occurred_at,
  );
  assert.notEqual(
    first.edges[0].evidence[0].event_id,
    second.edges[0].evidence[0].event_id,
  );
});
test("preview source record timestamps agree with displayed graph evidence", () => {
  for (const number of [1, 2])
    for (const edge of demoGraph(number).edges)
      for (const ref of edge.evidence) {
        const record = demoRead(
          "lineage-event",
          new URLSearchParams({ id: ref.event_id }),
        ) as { occurred_at: string; received_at: string };
        assert.equal(record.occurred_at, ref.occurred_at);
        assert.equal(record.received_at, ref.received_at);
      }
});
test("preview failure, empty and stale states are explicit", () => {
  assert.throws(
    () => demoRead("jobs", new URLSearchParams({ scenario: "unavailable" })),
    /api_unavailable/,
  );
  assert.throws(
    () => demoRead("jobs", new URLSearchParams({ scenario: "unauthorized" })),
    /dashboard_unauthorized/,
  );
  assert.deepEqual(
    demoRead("jobs", new URLSearchParams({ scenario: "empty" })),
    { items: [], limit: 50, offset: 0, has_more: false },
  );
  const coverage = demoRead(
    "coverage",
    new URLSearchParams({ scenario: "stale" }),
  ) as { detector: string };
  assert.equal(coverage.detector, "stale");
});

test("exact history page boundary produces an empty next page", () => {
  const first = demoRead(
    "history",
    new URLSearchParams({ scenario: "history50", offset: "0" }),
  ) as unknown[];
  const second = demoRead(
    "history",
    new URLSearchParams({ scenario: "history50", offset: "50" }),
  ) as unknown[];
  assert.equal(first.length, 50);
  assert.deepEqual(second, []);
  assert.equal(
    (
      demoRead(
        "history",
        new URLSearchParams({ scenario: "history50", offset: "0" }),
      ) as unknown[]
    ).length,
    50,
  );
});
