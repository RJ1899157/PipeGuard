import type { Graph, QualityObservation } from "./types.ts";
const id = (n: number) =>
  `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
export function qualityFixture(
  jobId: string,
  run: string,
  attempt: number,
  mixed = false,
): QualityObservation[] {
  if (attempt === 1) return [];
  const statuses = mixed
    ? (["pass", "fail", "error", "skipped", "unknown"] as const)
    : Array.from({ length: 14 }, () => "pass" as const);
  const first: QualityObservation = {
    id: id(800),
    job_id: jobId,
    occurred_at: "2026-10-31T09:15:08Z",
    received_at: "2026-10-31T09:15:10Z",
    payload: {
      schema_version: 1,
      event_id: "preview-quality-1",
      integration_id: id(2),
      job_id: jobId,
      external_run_id: run,
      attempt_number: attempt,
      occurred_at: "2026-10-31T09:15:08Z",
      inventory_complete: !mixed,
      checks: statuses.map((status, i) => ({
        rule_id: `orders.check_${i + 1}`,
        rule_version: "a".repeat(64),
        status,
        failures: status === "pass" ? 0 : status === "fail" ? 2 : null,
      })),
    },
  };
  return mixed
    ? [
        first,
        {
          ...first,
          id: id(801),
          received_at: "2026-10-31T09:15:09Z",
          payload: {
            ...first.payload,
            event_id: "preview-quality-2",
            checks: first.payload.checks.map((c) => ({
              ...c,
              status: "pass",
              failures: 0,
            })),
          },
        },
      ]
    : [first];
}
export function performanceGraph(cycle = false): Graph {
  const nodes = Array.from({ length: 200 }, (_, i) => ({
    id: `${Math.floor(i / 10) % 2 ? "step" : "dataset"}:fixture-${i}`,
    kind: Math.floor(i / 10) % 2 ? ("step" as const) : ("dataset" as const),
    name: i < 2 ? `fixture-${i}-`.padEnd(255, "x") : `fixture-${i}`,
    namespace: "synthetic-performance-fixture",
  }));
  if (cycle)
    for (let i = 0; i < nodes.length; i++) {
      nodes[i].kind = i % 2 ? "step" : "dataset";
      nodes[i].id = `${nodes[i].kind}:fixture-${i}`;
    }
  const edges: Graph["edges"] = [];
  const add = (from: number, to: number) =>
    edges.push({ source: nodes[from].id, target: nodes[to].id, evidence: [] });
  if (cycle) {
    for (let i = 0; i < 200; i++) add(i, (i + 1) % 200);
  } else {
    for (let layer = 0; layer < 19; layer++)
      for (let n = 0; n < 10; n++)
        for (let delta = 0; delta < 5; delta++)
          add(layer * 10 + n, (layer + 1) * 10 + ((n + delta) % 10));
    for (let n = 0; n < 10; n++)
      for (let delta = 0; delta < 5; delta++) add(n, 30 + ((n + delta) % 10));
  }
  return {
    nodes,
    edges,
    coverage: "partial",
    missing_metadata: ["synthetic_performance_fixture"],
    truncated: false,
    event_count: 0,
    semantics: "observed_union",
    as_of: "2026-10-31T09:16:00Z",
    known_at: "2026-10-31T09:16:00Z",
  };
}
