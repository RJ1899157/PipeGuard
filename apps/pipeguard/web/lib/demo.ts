import { conflictingRules } from "./analytics.ts";
import { qualityFixture, performanceGraph } from "./exploration-fixtures.ts";
import type {
  Job,
  Run,
  Attempt,
  Graph,
  Coverage,
  Incident,
  History,
} from "./types";
const id = (n: number) =>
  `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
export const demoJob: Job = {
  id: id(1),
  name: "orders-pipeline",
  namespace: "sample-orders",
  integration_id: id(2),
  kind: "airflow",
};
const time = (s: string) => `2026-10-31T${s}Z`;
export const demoRun: Run = {
  id: id(3),
  job_id: demoJob.id,
  external_run_id: "design_preview_retry",
  state: "succeeded",
  reconciliation_required: false,
  started_at: time("09:14:00"),
  finished_at: time("09:15:08"),
};
export const demoAttempts: Attempt[] = [
  {
    id: id(4),
    run_id: demoRun.id,
    attempt_number: 1,
    attempt_key: "1",
    state: "failed",
    projection_source: "producer",
    error_code: "source_unavailable",
    reconciliation_required: false,
    started_at: time("09:14:00"),
    finished_at: time("09:14:03"),
  },
  {
    id: id(5),
    run_id: demoRun.id,
    attempt_number: 2,
    attempt_key: "2",
    state: "succeeded",
    projection_source: "producer",
    error_code: null,
    reconciliation_required: false,
    started_at: time("09:15:00"),
    finished_at: time("09:15:08"),
  },
];
export const demoCoverage: Coverage = {
  detector: "fresh",
  last_completed_at: time("09:15:10"),
  jobs: [
    {
      job_id: demoJob.id,
      mode: "airflow_reconciled",
      lineage_expected: true,
      quality_expected: true,
      activity_interval_seconds: null,
      detector_status: "fresh",
    },
  ],
  unmonitored_job_ids: [],
  notice:
    "The independent local watcher detects service outages; total host loss requires another device.",
};
export const demoIncident: Incident = {
  id: id(6),
  job_id: demoJob.id,
  condition: "execution_failed",
  subject: "design_preview_retry",
  severity: "high",
  state: "resolved",
  created_at: time("09:14:05"),
  last_evaluated_at: time("09:15:10"),
};
export function demoGraph(attempt: number): Graph {
  const names = [
    "orders-input",
    "load_orders",
    "raw.orders",
    "stg_orders",
    "staging.stg_orders",
    "orders",
    "analytics.orders",
    "daily_revenue",
    "analytics.daily_revenue",
  ];
  const nodes = names.map((name, i) => ({
    id: `${i % 2 ? "step" : "dataset"}:${id(i + 20)}`,
    kind: i % 2 ? ("step" as const) : ("dataset" as const),
    name,
    namespace: i % 2 ? "dbt.orders" : "sample_warehouse",
    ...(i % 2
      ? { attempt_number: attempt, external_run_id: demoRun.external_run_id }
      : {}),
  }));
  const edges = nodes.slice(1).map((node, i) => ({
    source: nodes[i].id,
    target: node.id,
    evidence: [
      {
        event_id: id(i + 50 + (attempt === 1 ? 100 : 0)),
        payload_hash: "a".repeat(64),
        basis: "declared_dependency",
        event_type: attempt === 1 ? "OTHER" : "COMPLETE",
        occurred_at: time(attempt === 1 ? "09:14:03" : "09:15:08"),
        received_at: time(attempt === 1 ? "09:14:05" : "09:15:10"),
      },
    ],
  }));
  return {
    nodes: attempt === 1 ? nodes.slice(0, 2) : nodes,
    edges: attempt === 1 ? edges.slice(0, 1) : edges,
    coverage: attempt === 1 ? "partial" : "reported_complete",
    missing_metadata: attempt === 1 ? ["partial_lineage"] : [],
    truncated: false,
    event_count: attempt === 1 ? 1 : 8,
    semantics: "observed_union",
    as_of: time("09:16:00"),
    known_at: time("09:16:00"),
  };
}
export function demoRead(kind: string, query: URLSearchParams): unknown {
  const scenario = query.get("scenario");
  if (scenario === "unavailable") throw new Error("api_unavailable");
  if (scenario === "unauthorized") throw new Error("dashboard_unauthorized");
  if (scenario === "empty") {
    if (["jobs", "runs", "attempts"].includes(kind))
      return { items: [], limit: 50, offset: 0, has_more: false };
    if (["incidents", "history"].includes(kind)) return [];
    if (kind === "coverage")
      return { ...demoCoverage, jobs: [], unmonitored_job_ids: [] };
  }
  const page = (items: unknown[]) => ({
    items,
    limit: 50,
    offset: 0,
    has_more: false,
  });
  if (kind === "jobs") return page([demoJob]);
  if (kind === "runs") return page([demoRun]);
  if (kind === "attempts") return page(demoAttempts);
  if (kind === "coverage")
    return scenario === "stale"
      ? {
          ...demoCoverage,
          detector: "stale",
          jobs: demoCoverage.jobs.map((j) => ({
            ...j,
            detector_status: "stale",
          })),
        }
      : demoCoverage;
  if (kind === "incidents") return [demoIncident];
  if (kind === "history" && scenario === "history50")
    return Array.from(
      { length: 50 },
      (_, i) =>
        ({
          id: id(900 + i),
          action: i % 2 ? "resolved" : "opened",
          evidence_key: `preview-history-${i}`,
          evidence: { notice: "Demonstration pagination boundary" },
          actor: "deterministic_rule",
          occurred_at: time("09:14:05"),
          created_at: time("09:14:05"),
        }) satisfies History,
    ).slice(
      Number(query.get("offset") || 0),
      Number(query.get("offset") || 0) + 50,
    );
  if (kind === "history")
    return [
      {
        id: id(7),
        action: "opened",
        evidence_key: "design-preview",
        evidence: { reported_reason: "source_unavailable" },
        actor: "deterministic_rule",
        occurred_at: time("09:14:03"),
        created_at: time("09:14:05"),
      },
      {
        id: id(8),
        action: "resolved",
        evidence_key: "design-preview-retry",
        evidence: { attempt_number: 2 },
        actor: "deterministic_rule",
        occurred_at: time("09:15:08"),
        created_at: time("09:15:10"),
      },
    ] satisfies History[];
  if (kind === "watchdog")
    return {
      version: 1,
      checked_at: new Date().toISOString(),
      status: {
        api: "healthy",
        database: "healthy",
        monitor: scenario === "stale" ? "stale" : "fresh",
      },
      notification: "disabled",
    };
  if (
    kind === "quality" &&
    query.get("quality_fixture") === "hidden-conflict"
  ) {
    const pair = qualityFixture(
      demoJob.id,
      demoRun.external_run_id,
      Number(query.get("attempt") || 2),
      true,
    );
    if (pair.length === 0)
      return {
        ...page([]),
        summary: {
          report_count: 0,
          conflicting_rule_count: 0,
          has_conflicts: false,
          scope: "filtered_history",
        },
      };
    const all = Array.from({ length: 50 }, (_, i) => ({
      ...pair[1],
      id: id(2000 + i),
    }));
    all.push({ ...pair[0], id: id(2100) });
    const offset = Number(query.get("offset") || 0);
    return {
      items: all.slice(offset, offset + 50),
      offset,
      limit: 50,
      has_more: offset + 50 < all.length,
      summary: {
        report_count: all.length,
        conflicting_rule_count: conflictingRules(all),
        has_conflicts: true,
        scope: "filtered_history",
      },
    };
  }
  if (kind === "quality")
    return page(
      query.get("quality_fixture") === "empty"
        ? []
        : qualityFixture(
            demoJob.id,
            demoRun.external_run_id,
            Number(query.get("attempt") || 2),
            query.get("quality_fixture") === "mixed",
          ),
    );
  if (kind === "lineage")
    return query.get("graph_fixture") === "stress"
      ? performanceGraph()
      : query.get("graph_fixture") === "cycle"
        ? performanceGraph(true)
        : demoGraph(Number(query.get("attempt") || 2));
  if (kind === "lineage-event")
    return {
      id: query.get("id"),
      occurred_at: time(
        Number(query.get("id")?.slice(-12)) >= 150 ? "09:14:03" : "09:15:08",
      ),
      received_at: time(
        Number(query.get("id")?.slice(-12)) >= 150 ? "09:14:05" : "09:15:10",
      ),
      payload_hash: "a".repeat(64),
      payload: { notice: "Demonstration record. No live evidence." },
    };
  return null;
}
