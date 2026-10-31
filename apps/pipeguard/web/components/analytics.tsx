"use client";
import { useMemo, useState } from "react";
import dynamic from "next/dynamic";
import {
  qualityCounts,
  conflictingRules,
  timelineRows,
  timelineOffsetStyle,
} from "@/lib/analytics";
import { useRead } from "@/lib/use-read";
import type { Attempt, QualityObservation, Page } from "@/lib/types";
const Chart = dynamic(() => import("./chart"), {
  ssr: false,
  loading: () => <p className="notice">Loading chart…</p>,
});
const time = (s: string) =>
  new Date(s).toISOString().replace("T", " ").replace("Z", " UTC");
export function ExecutionTimeline({
  attempts,
  selected,
  onSelect,
  hasMore,
}: {
  attempts: Attempt[];
  selected: string | undefined;
  onSelect: (id: string) => void;
  hasMore: boolean;
}) {
  const timeline = useMemo(() => timelineRows(attempts), [attempts]);
  const option = useMemo(
    () => ({
      grid: { left: 100, right: 35, top: 15, bottom: 45 },
      tooltip: { trigger: "item", renderMode: "richText" },
      xAxis: {
        type: "value",
        name: "Seconds from chart origin",
        nameLocation: "middle",
        nameGap: 30,
        min: 0,
        axisLabel: { color: "#66728c" },
        splitLine: { lineStyle: { color: "#edf0f6" } },
      },
      yAxis: {
        type: "category",
        inverse: true,
        data: timeline.rows.map((r) => `Attempt ${r.attempt.attempt_number}`),
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series: [
        {
          name: "Offset",
          type: "bar",
          stack: "time",
          silent: true,
          itemStyle: timelineOffsetStyle,
          data: timeline.rows.map((r) => r.offsetSeconds),
          tooltip: { show: false },
        },
        {
          name: "Duration (seconds)",
          type: "bar",
          stack: "time",
          barMaxWidth: 25,
          data: timeline.rows.map((r) => ({
            value: r.durationSeconds,
            itemStyle: {
              color:
                r.attempt.state === "succeeded"
                  ? "#087f56"
                  : r.attempt.state === "failed"
                    ? "#bb3449"
                    : "#94610b",
              borderColor:
                r.attempt.id === selected ? "#6250df" : "transparent",
              borderWidth: r.attempt.id === selected ? 3 : 0,
            },
          })),
        },
      ],
    }),
    [timeline, selected],
  );
  return (
    <section className="panel analytics-panel">
      <div className="section-heading">
        <div>
          <h2>Execution timeline</h2>
          <p>
            Reported start/end times for attempts on this page. Select a bar to
            inspect that attempt.
          </p>
        </div>
      </div>
      {timeline.rows.length ? (
        <>
          <Chart
            option={option}
            height={Math.max(
              180,
              Math.min(500, timeline.rows.length * 30 + 70),
            )}
            label="Attempt durations in seconds. Expanded attempt history provides the keyboard-accessible alternative."
            onSelect={(index) => {
              const row = timeline.rows[index];
              if (row) onSelect(row.attempt.id);
            }}
          />
          <p className="small-note">
            Origin: {time(new Date(timeline.origin!).toISOString())}. Gaps
            between bars represent time between reported attempts, not an
            inferred cause. Zero-duration attempts may have no visible bar.
          </p>
        </>
      ) : (
        <p className="notice">
          No complete, valid timestamp pairs are available to plot. Inspect the
          reported attempt details below.
        </p>
      )}
      {timeline.omitted > 0 && (
        <p className="notice warning">
          {timeline.omitted} attempt(s) lack a valid completed interval and are
          omitted from the chart. No end time has been invented.
        </p>
      )}
      {hasMore && (
        <p className="notice">
          This timeline covers the current attempt page, not the full execution
          history.
        </p>
      )}
    </section>
  );
}
export function QualityResults({
  jobId,
  run,
  attempt,
  demo,
  revision,
}: {
  jobId: string;
  run: string;
  attempt: number;
  demo: boolean;
  revision: number;
}) {
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState("");
  const reports = useRead<Page<QualityObservation>>(
    "quality",
    { id: jobId, run, attempt: String(attempt), offset: String(offset) },
    demo,
    revision,
  );
  const report =
    reports.data?.items.find((r) => r.id === selected) ||
    reports.data?.items[0];
  const conflicts = conflictingRules(reports.data?.items || []);
  const counts = useMemo(() => (report ? qualityCounts(report) : []), [report]);
  const option = useMemo(
    () => ({
      grid: { left: 45, right: 20, top: 20, bottom: 40 },
      tooltip: { trigger: "item", renderMode: "richText" },
      xAxis: { type: "category", data: counts.map((c) => c.status) },
      yAxis: { type: "value", minInterval: 1, min: 0, name: "Checks" },
      series: [
        {
          name: "Reported checks",
          type: "bar",
          barMaxWidth: 40,
          data: counts.map((c) => ({
            value: c.count,
            itemStyle: {
              color: {
                pass: "#087f56",
                fail: "#bb3449",
                error: "#94610b",
                skipped: "#66728c",
                unknown: "#6250df",
              }[c.status],
            },
          })),
        },
      ],
    }),
    [counts],
  );
  return (
    <section className="panel analytics-panel">
      <div className="section-heading">
        <div>
          <h2>Quality results · Attempt {attempt}</h2>
          <p>
            One stored report at a time. Execution success does not establish
            quality.
          </p>
        </div>
      </div>
      {reports.loading ? (
        <p className="notice" role="status">
          Loading stored quality reports…
        </p>
      ) : reports.error ? (
        <p className="notice warning" role="alert">
          Quality reports unavailable. Use Refresh to retry; no passing result
          is inferred.
        </p>
      ) : !report ? (
        <p className="notice">
          No quality reports stored in this scope. Quality is unknown, not
          passing.
        </p>
      ) : (
        <>
          <label className="quality-picker">
            Report (receipt order)
            <select
              value={report.id}
              onChange={(e) => setSelected(e.target.value)}
            >
              {reports.data?.items.map((r) => (
                <option key={r.id} value={r.id}>
                  {time(r.received_at)} · {r.id}
                </option>
              ))}
            </select>
          </label>
          {conflicts > 0 && (
            <p className="notice warning">
              {conflicts} rule/version conflict(s) in the loaded reports for
              this attempt. Choosing a passing report does not erase
              contradictory evidence.
            </p>
          )}
          <p
            className={`notice ${report.payload.inventory_complete ? "" : "warning"}`}
          >
            {report.payload.inventory_complete
              ? "Producer declared this report’s check inventory complete."
              : "Incomplete check inventory: additional unreported checks may exist."}{" "}
            Counts apply only to this selected report.
          </p>
          <Chart
            option={option}
            label="Counts of pass, fail, error, skipped and unknown checks in the selected quality report. The table below contains every reported check."
          />
          <div className="quality-counts">
            {counts.map((c) => (
              <span key={c.status}>
                {c.status}: <strong>{c.count}</strong>
              </span>
            ))}
          </div>
          <div className="quality-provenance">
            <p>
              <strong>Observed:</strong> {time(report.occurred_at)}
            </p>
            <p>
              <strong>Received:</strong> {time(report.received_at)}
            </p>
            <p className="mono">Observation {report.id}</p>
          </div>
          <div className="table-wrap">
            <table>
              <caption className="sr-only">
                Reported checks in the selected quality observation
              </caption>
              <thead>
                <tr>
                  <th>Rule / version</th>
                  <th>Reported status</th>
                  <th>Reported failures</th>
                </tr>
              </thead>
              <tbody>
                {report.payload.checks.map((c) => (
                  <tr key={`${c.rule_id}:${c.rule_version}`}>
                    <td>
                      <strong>{c.rule_id}</strong>
                      <small className="mono">{c.rule_version}</small>
                    </td>
                    <td>{c.status}</td>
                    <td>{c.failures === null ? "Not reported" : c.failures}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {report.payload.checks.length === 0 && (
            <p className="notice">
              This report contains no checks. Empty inventory is not a passing
              result.
            </p>
          )}
        </>
      )}
      <div className="pager">
        <span>Report page {offset / 50 + 1} · up to 50 observations</span>
        <button
          disabled={offset === 0 || reports.loading}
          onClick={() => {
            setOffset((n) => Math.max(0, n - 50));
            setSelected("");
          }}
        >
          Previous reports
        </button>
        <button
          disabled={!reports.data?.has_more || reports.loading}
          onClick={() => {
            setOffset((n) => n + 50);
            setSelected("");
          }}
        >
          Next reports
        </button>
      </div>
    </section>
  );
}
