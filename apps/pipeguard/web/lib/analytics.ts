import type { Attempt, QualityObservation, QualityStatus } from "./types.ts";
/** A layout spacer must stay invisible even when ARIA adds series patterns. */
export const timelineOffsetStyle = {
  color: "transparent",
  opacity: 0,
  decal: {
    symbol: "none",
    color: "transparent",
    backgroundColor: "transparent",
  },
};
export const qualityStatuses: QualityStatus[] = [
  "pass",
  "fail",
  "error",
  "skipped",
  "unknown",
];
export function qualityCounts(report: QualityObservation) {
  return qualityStatuses.map((status) => ({
    status,
    count: report.payload.checks.filter((c) => c.status === status).length,
  }));
}
export function conflictingRules(reports: QualityObservation[]) {
  const map = new Map<string, Set<string>>();
  for (const r of reports)
    for (const c of r.payload.checks) {
      const key = JSON.stringify([
        r.job_id,
        r.payload.external_run_id,
        r.payload.attempt_number,
        c.rule_id,
        c.rule_version,
      ]);
      if (!map.has(key)) map.set(key, new Set());
      map.get(key)!.add(c.status);
    }
  return [...map.values()].filter((statuses) => statuses.size > 1).length;
}
export function timelineRows(attempts: Attempt[]) {
  const valid = attempts.flatMap((a) => {
    if (!a.started_at || !a.finished_at) return [];
    const start = Date.parse(a.started_at),
      end = Date.parse(a.finished_at);
    return Number.isFinite(start) && Number.isFinite(end) && end >= start
      ? [{ attempt: a, start, end }]
      : [];
  });
  const origin = valid.length ? Math.min(...valid.map((r) => r.start)) : null;
  return {
    origin,
    rows: valid.map((r) => ({
      ...r,
      offsetSeconds: (r.start - origin!) / 1000,
      durationSeconds: (r.end - r.start) / 1000,
    })),
    omitted: attempts.length - valid.length,
  };
}
