"use client";
import { useCallback, useMemo, useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import {
  SquaresFourIcon,
  MonitorIcon,
  ArrowClockwiseIcon,
  CheckCircleIcon,
  XCircleIcon,
  WarningCircleIcon,
  InfoIcon,
  DatabaseIcon,
  GearSixIcon,
  ArrowRightIcon,
  FileMagnifyingGlassIcon,
  CaretRightIcon,
  XIcon,
  ClockIcon,
  ListBulletsIcon,
} from "@phosphor-icons/react";
import type {
  Job,
  Run,
  Attempt,
  Page,
  Incident,
  Coverage,
  Graph,
  History,
} from "@/lib/types";
import { graphEvidence, selectedEdgeIndex } from "@/lib/graph-evidence";
import { useRead } from "@/lib/use-read";
import { ExecutionTimeline, QualityResults } from "./analytics";
import { GraphText } from "./graph-text";
import { WatchdogStatus } from "./watchdog-status";
import { Investigations } from "./investigations";
import { Recovery } from "./recovery";
import { RecoveryActions } from "./recovery-actions";
const Lineage = dynamic(() => import("./lineage"), {
  ssr: false,
  loading: () => <div className="empty">Loading lineage diagram…</div>,
});
const label = (s: string) => s.replaceAll("_", " ");
function time(value: string | null | undefined) {
  return value
    ? new Date(value).toLocaleString("en-GB", {
        day: "2-digit",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        timeZone: "UTC",
        hour12: false,
      }) + " UTC"
    : "Not reported";
}
function duration(a: Attempt) {
  if (!a.started_at || !a.finished_at) return "Not reported";
  const ms = Date.parse(a.finished_at) - Date.parse(a.started_at);
  return ms < 0
    ? "Conflicting timestamps"
    : ms < 1000
      ? `${ms.toFixed(0)} ms`
      : ms < 60000
        ? `${(ms / 1000).toFixed(1)}s`
        : `${(ms / 60000).toFixed(1)} min`;
}
function tone(s: string) {
  return ["succeeded", "resolved", "fresh", "reported_complete"].includes(s)
    ? "good"
    : [
          "failed",
          "cancelled",
          "blocked",
          "open",
          "stale",
          "unmonitored",
        ].includes(s)
      ? "bad"
      : "warn";
}
function Status({
  value,
  children,
}: {
  value: string;
  children?: React.ReactNode;
}) {
  const Icon =
    tone(value) === "good"
      ? CheckCircleIcon
      : tone(value) === "bad"
        ? XCircleIcon
        : WarningCircleIcon;
  return (
    <span className={`status ${tone(value)}`}>
      <Icon size={18} weight="fill" aria-hidden />
      {children || label(value)}
    </span>
  );
}
function State({
  loading,
  error,
  empty,
  children,
}: {
  loading?: boolean;
  error?: string | null;
  empty?: boolean;
  children: React.ReactNode;
}) {
  if (loading)
    return (
      <div className="empty" role="status">
        <ClockIcon size={23} />
        Loading stored records…
      </div>
    );
  if (error)
    return (
      <div className="empty error" role="alert">
        <WarningCircleIcon size={25} />
        <strong>
          {error === "dashboard_unauthorized"
            ? "Dashboard access denied"
            : error === "record_not_found"
              ? "Record no longer available"
              : error === "read_snapshot_expired"
                ? "List snapshot expired"
                : error === "read_snapshot_capacity"
                  ? "Selection exceeds snapshot capacity"
                  : "Data unavailable"}
        </strong>
        <span>
          {error === "dashboard_not_configured"
            ? "Start the dashboard with its private local configuration."
            : error === "read_snapshot_expired"
              ? "Use Refresh to capture current records and start again. Pages will not be silently mixed."
              : error === "read_snapshot_capacity"
                ? "Wait for older snapshots to expire, or narrow the execution scope, then use Refresh."
                : "The API could not supply these records. Check the local services, then use Refresh."}
        </span>
      </div>
    );
  if (empty)
    return (
      <div className="empty">
        <InfoIcon size={24} />
        <strong>No records in this scope</strong>
        <span>
          Nothing has been reported for this selection. This does not mean it is
          healthy.
        </span>
      </div>
    );
  return <>{children}</>;
}
function Pager({
  offset,
  more,
  onChange,
}: {
  offset: number;
  more: boolean;
  onChange: (n: number) => void;
}) {
  return (
    <div className="pager">
      <span>Page {offset / 50 + 1} · up to 50 records</span>
      <button
        disabled={offset === 0}
        onClick={() => onChange(Math.max(0, offset - 50))}
      >
        Previous
      </button>
      <button disabled={!more} onClick={() => onChange(offset + 50)}>
        Next page
      </button>
    </div>
  );
}
export default function Dashboard() {
  const [ready, setReady] = useState(false);
  const [demo, setDemo] = useState(false);
  useEffect(() => {
    setDemo(new URLSearchParams(location.search).get("preview") === "1");
    setReady(true);
  }, []);
  const [view, setView] = useState("Pipelines");
  const [revision, setRevision] = useState(0);
  const [jobId, setJob] = useState("");
  const [runId, setRun] = useState("");
  const [attemptId, setAttempt] = useState("");
  const [jobOffset, setJobOffset] = useState(0);
  const [runOffset, setRunOffset] = useState(0);
  const [attemptOffset, setAttemptOffset] = useState(0);
  const [incidentOffset, setIncidentOffset] = useState(0);
  const [selectedLink, setLink] = useState<{
    scope: string;
    source: string;
    target: string;
  } | null>(null);
  const [selectedNode, setNode] = useState<string | null>(null);
  const [selectedIncident, setIncident] = useState("");
  const [historyOffset, setHistoryOffset] = useState(0);
  const [incidentFilter, setIncidentFilter] = useState("all");
  const [showEvidence, setShowEvidence] = useState(false);
  const [eventId, setEvent] = useState("");
  const evidenceRef = useRef<HTMLElement>(null);
  const executionView = view === "Pipelines" || view === "Lineage";
  const jobs = useRead<Page<Job>>(
    "jobs",
    ready ? { offset: String(jobOffset) } : null,
    demo,
    revision,
  );
  const coverage = useRead<Coverage>(
    "coverage",
    ready ? {} : null,
    demo,
    revision,
  );
  const job =
    jobs.data?.items.find((j) => j.id === jobId) ||
    jobs.data?.items.find((j) => j.name === "orders-pipeline") ||
    jobs.data?.items[0];
  const runs = useRead<Page<Run>>(
    "runs",
    executionView && job ? { id: job.id, offset: String(runOffset) } : null,
    demo,
    revision,
  );
  const run =
    runs.data?.items.find((r) => r.id === runId) || runs.data?.items[0];
  const attempts = useRead<Page<Attempt>>(
    "attempts",
    executionView && run ? { id: run.id, offset: String(attemptOffset) } : null,
    demo,
    revision,
  );
  const attempt =
    attempts.data?.items.find((a) => a.id === attemptId) ||
    attempts.data?.items.at(-1);
  const scope =
    attempt && run && job ? `${job.id}:${run.id}:${attempt.id}` : "";
  const graph = useRead<Graph>(
    "lineage",
    executionView && attempt && run && job
      ? {
          id: job.id,
          run: run.external_run_id,
          attempt: String(attempt.attempt_number),
        }
      : null,
    demo,
    revision,
  );
  const incidents = useRead<Incident[]>(
    "incidents",
    ready && view === "Incidents" ? { offset: String(incidentOffset) } : null,
    demo,
    revision,
  );
  const incident = incidents.data?.find((i) => i.id === selectedIncident);
  const activeRecords = view === "Incidents" ? incidents : jobs;
  const history = useRead<History[]>(
    "history",
    view === "Incidents" && incident
      ? { id: incident.id, offset: String(historyOffset) }
      : null,
    demo,
    revision,
  );
  const sourceEvent = useRead<Record<string, unknown>>(
    "lineage-event",
    executionView && eventId ? { id: eventId } : null,
    demo,
    revision,
  );
  useEffect(() => {
    setNode(null);
    setLink(null);
    setShowEvidence(false);
    setEvent("");
  }, [scope, demo]);
  const node =
    selectedNode === ""
      ? undefined
      : graph.data?.nodes.find((n) => n.id === selectedNode) ||
        graph.data?.nodes.find(
          (n) => n.kind === "dataset" && n.name.includes("stg_orders"),
        ) ||
        graph.data?.nodes[0];
  const edgeIndex = selectedEdgeIndex(
    graph.data,
    selectedLink?.scope === scope ? selectedLink : null,
  );
  const link = edgeIndex === null ? undefined : graph.data?.edges[edgeIndex];
  const graphNames = useMemo(
    () => new Map(graph.data?.nodes.map((n) => [n.id, n.name]) || []),
    [graph.data],
  );
  const references = graphEvidence(graph.data, node?.id, edgeIndex);
  const cov = coverage.data?.jobs.find((c) => c.job_id === job?.id);
  const localFresh =
    coverage.at && Date.now() - Date.parse(coverage.at) > 90000;
  const detector =
    coverage.error || localFresh
      ? "unknown"
      : cov?.detector_status || "unknown";
  const [clock, setClock] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setClock((n) => n + 1), 15000);
    return () => clearInterval(id);
  }, []);
  void clock;
  function selectJob(id: string) {
    setJob(id);
    setRun("");
    setAttempt("");
    setRunOffset(0);
    setAttemptOffset(0);
    setNode(null);
    setLink(null);
    setShowEvidence(false);
    setEvent("");
  }
  function inspect() {
    setShowEvidence(true);
    requestAnimationFrame(() => evidenceRef.current?.focus());
  }
  const selectGraphNode = useCallback((id: string) => {
    setNode(id);
    setLink(null);
    setEvent("");
  }, []);
  const clearGraphSelection = useCallback(() => {
    setNode("");
    setLink(null);
    setEvent("");
    setShowEvidence(false);
  }, []);
  const selectGraphEdge = useCallback(
    (index: number) => {
      const edge = graph.data?.edges[index];
      if (!edge) return;
      setLink({ scope, source: edge.source, target: edge.target });
      setNode(edge.source);
      setEvent("");
    },
    [scope, graph.data],
  );
  const filteredIncidents =
    incidents.data?.filter(
      (i) => incidentFilter === "all" || i.state === incidentFilter,
    ) || [];
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to main content
      </a>
      <header className="topbar">
        <a className="brand" href={demo ? "/?preview=1" : "/"}>
          <SquaresFourIcon size={29} weight="duotone" />
          PipeGuard
        </a>
        <span className={`mode ${demo ? "demo" : ""}`}>
          {demo
            ? "Design preview · demonstration data"
            : "Live data · advisory AI"}
        </span>
        <nav aria-label="Main navigation">
          {["Overview", "Pipelines", "Incidents", "Lineage"].map((item) => (
            <button
              key={item}
              aria-current={view === item ? "page" : undefined}
              onClick={() => setView(item)}
            >
              {item}
            </button>
          ))}
        </nav>
        <span className="local">
          <MonitorIcon size={18} />
          Local environment
        </span>
        <a className="mode-link" href={demo ? "/" : "/?preview=1"}>
          {demo ? "Use live data" : "Preview design"}
        </a>
      </header>
      <main id="main" tabIndex={-1} data-demo={demo}>
        <div className="breadcrumbs">
          <button onClick={() => setView("Overview")}>Overview</button>
          <CaretRightIcon size={13} />
          <span>{job?.name || "Select a pipeline"}</span>
          <CaretRightIcon size={13} />
          <strong>
            {view === "Incidents"
              ? "Incident queue"
              : view === "Overview"
                ? "Overview"
                : "Execution detail"}
          </strong>
        </div>
        <div className="title-row">
          <div>
            <h1>
              {view === "Overview"
                ? "Your pipelines"
                : view === "Incidents"
                  ? "Incident queue"
                  : job?.name || "Pipeline details"}
            </h1>
            <p className="subtle">
              {view === "Incidents"
                ? "Deterministic incidents, with their original history preserved."
                : view === "Overview"
                  ? "Execution, monitoring coverage and evidence — kept distinct."
                  : "Inspect lineage and every execution attempt, including earlier failures."}
            </p>
          </div>
          <button
            className="refresh"
            onClick={() => {
              setJobOffset(0);
              setRunOffset(0);
              setAttemptOffset(0);
              setIncidentOffset(0);
              setHistoryOffset(0);
              setIncident("");
              setEvent("");
              setShowEvidence(false);
              setRevision((n) => n + 1);
            }}
          >
            <ArrowClockwiseIcon size={17} />
            Refresh
          </button>
        </div>
        {demo && (
          <div className="preview-note">
            <InfoIcon size={17} />
            Demonstration data · 31 Oct 2026. This view does not describe your
            running pipelines.
          </div>
        )}
        <div className="freshness" aria-live="polite">
          {demo
            ? "Preview records"
            : activeRecords.error
              ? "Records unavailable. Use Refresh to check again."
              : activeRecords.at
                ? `Records fetched ${time(activeRecords.at)}`
                : activeRecords.loading
                  ? "Fetching stored records…"
                  : "No records fetched yet."}
          {!demo && (
            <span>
              Refresh is manual. Monitoring freshness is evaluated separately.
            </span>
          )}
        </div>
        {!demo &&
          (view === "Overview"
            ? jobs.page
            : view === "Incidents"
              ? incidents.page
              : runs.page
          )?.snapshot && (
            <p className="notice small-note">
              Each list has its own stable snapshot. This list was captured at{" "}
              {
                (view === "Overview"
                  ? jobs.page
                  : view === "Incidents"
                    ? incidents.page
                    : runs.page)!.snapshot.captured_at
              }
              . Refresh includes later changes and starts again from the first
              page.
            </p>
          )}
        {view === "Overview" ? (
          <section className="panel">
            <div className="section-heading">
              <div>
                <h2>Monitored pipelines</h2>
                <p>Coverage describes instrumentation, not business health.</p>
              </div>
              <span className="pill">
                {jobs.data?.items.length || 0} on this page
              </span>
            </div>
            <State
              loading={jobs.loading || !ready}
              error={jobs.error}
              empty={jobs.data?.items.length === 0}
            >
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Pipeline</th>
                      <th>Kind</th>
                      <th>Monitoring mode</th>
                      <th>Detector</th>
                      <th>Expected evidence</th>
                      <th>
                        <span className="sr-only">Open pipeline</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {jobs.data?.items.map((j) => {
                      const c = coverage.data?.jobs.find(
                        (x) => x.job_id === j.id,
                      );
                      return (
                        <tr key={j.id}>
                          <td>
                            <strong>{j.name}</strong>
                            <small>{j.namespace}</small>
                          </td>
                          <td>{j.kind}</td>
                          <td>{c ? label(c.mode) : "Unavailable"}</td>
                          <td>
                            <Status
                              value={
                                coverage.error || localFresh
                                  ? "unknown"
                                  : c?.detector_status || "unknown"
                              }
                            />
                          </td>
                          <td>
                            {c
                              ? `${c.quality_expected ? "Quality expected" : "Quality not enrolled"} · ${c.lineage_expected ? "Lineage expected" : "Lineage not enrolled"}`
                              : "Unknown"}
                          </td>
                          <td>
                            <button
                              onClick={() => {
                                selectJob(j.id);
                                setView("Pipelines");
                              }}
                            >
                              Inspect <ArrowRightIcon size={15} />
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <Pager
                offset={jobOffset}
                more={Boolean(jobs.data?.has_more)}
                onChange={(n) => {
                  setJobOffset(n);
                  selectJob("");
                }}
              />
            </State>
            <WatchdogStatus demo={demo} revision={revision} />
            <div className="notice">
              <InfoIcon size={18} />
              {coverage.error
                ? "Monitoring coverage unavailable."
                : coverage.data?.notice || "Loading coverage…"}
            </div>
          </section>
        ) : view === "Incidents" ? (
          <div className="incident-grid">
            <section className="panel">
              <div className="section-heading">
                <h2>Open and resolved</h2>
                <label className="compact-label" htmlFor="incident-state">
                  State
                  <select
                    id="incident-state"
                    aria-label="State"
                    value={incidentFilter}
                    onChange={(e) => {
                      setIncidentFilter(e.target.value);
                      setIncident("");
                      setHistoryOffset(0);
                    }}
                  >
                    <option value="all">All on this page</option>
                    <option value="open">Open</option>
                    <option value="resolved">Resolved</option>
                  </select>
                </label>
              </div>
              <State
                loading={incidents.loading}
                error={incidents.error}
                empty={filteredIncidents.length === 0}
              >
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Condition</th>
                        <th>State</th>
                        <th>Severity</th>
                        <th>Reported</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredIncidents.map((i) => (
                        <tr
                          key={i.id}
                          className={incident?.id === i.id ? "active-row" : ""}
                        >
                          <td>
                            <button
                              className="text-button"
                              onClick={() => {
                                setIncident(i.id);
                                setHistoryOffset(0);
                              }}
                            >
                              {label(i.condition)}
                            </button>
                            <small>
                              {jobs.data?.items.find((j) => j.id === i.job_id)
                                ?.name || i.job_id}
                            </small>
                          </td>
                          <td>
                            <Status value={i.state} />
                          </td>
                          <td>{i.severity}</td>
                          <td>{time(i.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </State>
              <Pager
                offset={incidentOffset}
                more={
                  incidents.page?.has_more ??
                  (incidents.data?.length || 0) === 50
                }
                onChange={(n) => {
                  setIncidentOffset(n);
                  setIncident("");
                }}
              />
            </section>
            <aside className="panel inspector">
              <h2>Incident history</h2>
              {!incident ? (
                <div className="empty">
                  <ListBulletsIcon size={28} />
                  Select an incident to inspect its recorded transitions.
                </div>
              ) : (
                <>
                  <h3>{label(incident.condition)}</h3>
                  <Status value={incident.state} />
                  <dl>
                    <dt>Subject</dt>
                    <dd>{incident.subject}</dd>
                    <dt>Incident ID</dt>
                    <dd className="mono">{incident.id}</dd>
                  </dl>
                  <State
                    loading={history.loading}
                    error={history.error}
                    empty={history.data?.length === 0}
                  >
                    {history.data?.map((h) => (
                      <details key={h.id}>
                        <summary>
                          {label(h.action)} <small>{time(h.occurred_at)}</small>
                        </summary>
                        <p>
                          Recorded {time(h.created_at)} · {h.actor}
                        </p>
                        <pre>{JSON.stringify(h.evidence, null, 2)}</pre>
                      </details>
                    ))}
                  </State>
                  {((history.data?.length || 0) === 50 ||
                    historyOffset > 0) && (
                    <Pager
                      offset={historyOffset}
                      more={
                        history.page?.has_more ??
                        (history.data?.length || 0) === 50
                      }
                      onChange={setHistoryOffset}
                    />
                  )}
                  <Recovery
                    key={`recovery:${demo}:${incident.id}`}
                    incidentId={incident.id}
                    demo={demo}
                  />
                  <RecoveryActions
                    key={`execution:${demo}:${incident.id}`}
                    incidentId={incident.id}
                    demo={demo}
                  />
                  <Investigations
                    key={`${demo}:${incident.id}`}
                    incidentId={incident.id}
                    demo={demo}
                  />
                </>
              )}
            </aside>
          </div>
        ) : (
          <>
            <State
              loading={jobs.loading || !ready}
              error={jobs.error}
              empty={jobs.data?.items.length === 0}
            >
              <div className="scope-controls">
                <label htmlFor="pipeline-picker">
                  Pipeline
                  <select
                    id="pipeline-picker"
                    aria-label="Pipeline"
                    value={job?.id || ""}
                    onChange={(e) => selectJob(e.target.value)}
                  >
                    {jobs.data?.items.map((j) => (
                      <option key={j.id} value={j.id}>
                        {j.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="run-picker" htmlFor="execution-picker">
                  Execution
                  <select
                    id="execution-picker"
                    aria-label="Execution"
                    value={run?.id || ""}
                    onChange={(e) => {
                      setRun(e.target.value);
                      setAttempt("");
                      setAttemptOffset(0);
                    }}
                    disabled={!runs.data?.items.length}
                  >
                    {!runs.data?.items.length && (
                      <option>No executions reported</option>
                    )}
                    {runs.data?.items.map((r) => (
                      <option key={r.id} value={r.id}>
                        {time(r.started_at)} · {r.state} · {r.external_run_id}
                      </option>
                    ))}
                  </select>
                </label>
                <label htmlFor="graph-scope">
                  Graph scope
                  <select
                    id="graph-scope"
                    aria-label="Graph scope"
                    value={attempt?.id || ""}
                    onChange={(e) => {
                      setAttempt(e.target.value);
                      setNode(null);
                      setLink(null);
                      setEvent("");
                    }}
                    disabled={!attempts.data?.items.length}
                  >
                    {!attempts.data?.items.length && (
                      <option>No attempts reported</option>
                    )}
                    {attempts.data?.items.map((a) => (
                      <option key={a.id} value={a.id}>
                        Attempt {a.attempt_number} · {a.state}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              {(jobs.data?.has_more || jobOffset > 0) && (
                <Pager
                  offset={jobOffset}
                  more={Boolean(jobs.data?.has_more)}
                  onChange={(n) => {
                    setJobOffset(n);
                    selectJob("");
                  }}
                />
              )}
              <State
                loading={runs.loading}
                error={runs.error}
                empty={runs.data?.items.length === 0}
              >
                {(runs.data?.has_more || runOffset > 0) && (
                  <Pager
                    offset={runOffset}
                    more={Boolean(runs.data?.has_more)}
                    onChange={(n) => {
                      setRunOffset(n);
                      setRun("");
                      setAttempt("");
                      setAttemptOffset(0);
                    }}
                  />
                )}
                <div className="status-strip">
                  <div>
                    <Status value={run?.state || "unknown"}>
                      Run {run?.state || "unknown"}
                    </Status>
                    <small>
                      {attempts.data?.items.some((a) => a.state === "failed")
                        ? "Earlier failed attempts retained"
                        : "Execution outcome only"}
                    </small>
                  </div>
                  <div>
                    <Status value={detector}>Monitor {label(detector)}</Status>
                    <small>
                      {cov ? label(cov.mode) : "Coverage unavailable"}
                      {!demo && localFresh ? " · refresh needed" : ""}
                    </small>
                  </div>
                  <div>
                    <Status value="unknown">
                      Quality{" "}
                      {cov
                        ? cov.quality_expected
                          ? "expected"
                          : "not enrolled"
                        : "unknown"}
                    </Status>
                    <small>Execution success does not establish quality</small>
                  </div>
                </div>
                {run?.reconciliation_required && (
                  <div className="notice warning">
                    <WarningCircleIcon size={19} />
                    Conflicting execution evidence requires reconciliation. The
                    projected state is not a confirmed outcome.
                  </div>
                )}
                <div className="detail-grid">
                  <div className="primary-column">
                    <section className="panel graph-panel">
                      <div className="section-heading">
                        <div>
                          <h2>
                            Pipeline lineage{" "}
                            <span>
                              (Attempt {attempt?.attempt_number || "—"})
                            </span>
                          </h2>
                          <p>
                            Observed dependencies within this execution attempt.
                          </p>
                        </div>
                        {graph.data && <Status value={graph.data.coverage} />}
                      </div>
                      <State
                        loading={attempts.loading || graph.loading}
                        error={attempts.error || graph.error}
                        empty={!attempt || graph.data?.nodes.length === 0}
                      >
                        {graph.data && (
                          <>
                            <Lineage
                              graph={graph.data}
                              selected={node?.id || null}
                              onSelect={selectGraphNode}
                              selectedEdge={edgeIndex}
                              onEdgeSelect={selectGraphEdge}
                              onClear={clearGraphSelection}
                            />
                            <div
                              className={`notice ${graph.data.coverage === "partial" ? "warning" : ""}`}
                            >
                              <InfoIcon size={18} />
                              <span>
                                {graph.data.coverage === "partial"
                                  ? `Incomplete evidence: ${graph.data.missing_metadata.map(label).join(", ")}.`
                                  : "Reported complete against the producer-declared inventory; not proof of all business dependencies."}
                                {graph.data.truncated
                                  ? " Query limits reached; this graph is truncated."
                                  : ""}
                              </span>
                            </div>
                            <GraphText
                              graph={graph.data}
                              onNodeSelect={selectGraphNode}
                              onEdgeSelect={selectGraphEdge}
                            />
                          </>
                        )}
                      </State>
                    </section>
                    {attempts.data && (
                      <ExecutionTimeline
                        attempts={attempts.data.items}
                        selected={attempt?.id}
                        hasMore={attempts.data.has_more}
                        onSelect={setAttempt}
                      />
                    )}
                    <section className="panel attempts-panel">
                      <div className="section-heading">
                        <div>
                          <h2>Execution attempts</h2>
                          <p>
                            Each attempt keeps its own outcome and reported
                            failure reason.
                          </p>
                        </div>
                        <span className="pill">
                          {attempts.data?.items.length || 0} on this page
                        </span>
                      </div>
                      <State
                        loading={attempts.loading}
                        error={attempts.error}
                        empty={attempts.data?.items.length === 0}
                      >
                        <ol className="attempts">
                          {attempts.data?.items.map((a) => (
                            <li
                              key={a.id}
                              className={`attempt ${tone(a.state)} ${a.id === attempt?.id ? "current" : ""}`}
                            >
                              <div className="attempt-heading">
                                <Status value={a.state}>
                                  Attempt {a.attempt_number} {a.state}
                                </Status>
                                <div className="attempt-time">
                                  {time(a.started_at)} – {time(a.finished_at)}
                                  <small>Duration {duration(a)}</small>
                                </div>
                              </div>
                              <div className="attempt-details">
                                <dl>
                                  <dt>
                                    {a.error_code
                                      ? "Reported reason"
                                      : "Outcome"}
                                  </dt>
                                  <dd>
                                    {a.error_code
                                      ? label(a.error_code)
                                      : label(a.state)}
                                  </dd>
                                  <dt>Projection source</dt>
                                  <dd>
                                    {a.projection_source === "producer"
                                      ? "Producer event"
                                      : a.projection_source === "airflow"
                                        ? "Airflow reconciliation"
                                        : a.projection_source}
                                  </dd>
                                  <dt>Evidence</dt>
                                  <dd>
                                    {a.reconciliation_required
                                      ? "Conflicting evidence · reconciliation required"
                                      : "Earlier records remain stored"}
                                  </dd>
                                </dl>
                                <button
                                  className="text-button"
                                  onClick={() => {
                                    setAttempt(a.id);
                                    setNode(null);
                                    setLink(null);
                                    setEvent("");
                                  }}
                                >
                                  Inspect attempt {a.attempt_number}
                                  <ArrowRightIcon size={14} />
                                </button>
                              </div>
                            </li>
                          ))}
                        </ol>
                      </State>
                      {(attempts.data?.has_more || attemptOffset > 0) && (
                        <Pager
                          offset={attemptOffset}
                          more={Boolean(attempts.data?.has_more)}
                          onChange={(n) => {
                            setAttemptOffset(n);
                            setAttempt("");
                          }}
                        />
                      )}
                      <div className="attempt-footer">
                        <span>
                          Evidence scope{" "}
                          <strong>
                            Attempt {attempt?.attempt_number || "—"}
                          </strong>
                        </span>
                        <button
                          className="primary"
                          onClick={inspect}
                          disabled={!attempt}
                        >
                          <FileMagnifyingGlassIcon size={19} />
                          Inspect evidence
                        </button>
                      </div>
                    </section>
                    {job && run && attempt && (
                      <QualityResults
                        key={`${scope}:${revision}`}
                        jobId={job.id}
                        run={run.external_run_id}
                        attempt={attempt.attempt_number}
                        demo={demo}
                        revision={revision}
                      />
                    )}
                  </div>
                  <aside
                    className="panel inspector"
                    ref={evidenceRef}
                    tabIndex={-1}
                  >
                    <div className="section-heading">
                      <h2>
                        {showEvidence
                          ? "Stored evidence"
                          : link
                            ? "Dependency detail"
                            : "Dataset / step detail"}
                      </h2>
                      {showEvidence && (
                        <button
                          className="icon-button"
                          aria-label="Close evidence detail"
                          onClick={() => setShowEvidence(false)}
                        >
                          <XIcon size={19} />
                        </button>
                      )}
                    </div>
                    <State
                      loading={graph.loading}
                      error={graph.error}
                      empty={graph.data?.nodes.length === 0}
                    >
                      {Boolean(graph.data?.nodes.length) && !node && (
                        <p className="empty">
                          Select a dataset, step or dependency to inspect its
                          evidence.
                        </p>
                      )}
                      {node && (
                        <>
                          {link && (
                            <p className="notice">
                              Selected dependency: {graphNames.get(link.source)}{" "}
                              → {graphNames.get(link.target)}. Source node
                              below.
                            </p>
                          )}
                          <div className="node-title">
                            {node.kind === "dataset" ? (
                              <DatabaseIcon size={32} />
                            ) : (
                              <GearSixIcon size={32} />
                            )}
                            <div>
                              <h3>{node.name}</h3>
                              <p>
                                {node.kind === "dataset"
                                  ? "Dataset"
                                  : "Step execution"}
                              </p>
                            </div>
                          </div>
                          <dl>
                            <dt>Namespace</dt>
                            <dd>{node.namespace}</dd>
                            <dt>Graph scope</dt>
                            <dd>
                              Attempt {attempt?.attempt_number} ·{" "}
                              {run?.external_run_id}
                            </dd>
                            <dt>Lineage coverage</dt>
                            <dd>
                              <Status
                                value={graph.data?.coverage || "unknown"}
                              />
                            </dd>
                            <dt>Semantics</dt>
                            <dd>Observed union within selected attempt</dd>
                          </dl>
                          <p className="small-note">
                            Dataset membership does not prove row correctness or
                            current availability.
                          </p>
                          <h3>Evidence sources</h3>
                          <p className="subtle">
                            Lineage event references for this{" "}
                            {link ? "dependency" : "node"}. Source time and
                            receipt time are separate.
                          </p>
                          {references.length === 0 ? (
                            <p className="notice">
                              No retained edge references for this{" "}
                              {link ? "dependency" : "node"}. Missing evidence
                              remains unknown.
                            </p>
                          ) : (
                            references
                              .slice(0, showEvidence ? 100 : 3)
                              .map((ref) => (
                                <div
                                  className="evidence-source"
                                  key={ref.event_id}
                                >
                                  <strong>{label(ref.basis)}</strong>
                                  <span className="pill">{ref.event_type}</span>
                                  <dl>
                                    <dt>Observed</dt>
                                    <dd>{time(ref.occurred_at)}</dd>
                                    <dt>Received</dt>
                                    <dd>{time(ref.received_at)}</dd>
                                  </dl>
                                  {showEvidence && (
                                    <>
                                      <button
                                        className="text-button mono"
                                        onClick={() => setEvent(ref.event_id)}
                                        aria-label={`Open lineage record ${ref.event_id}`}
                                      >
                                        {ref.event_id}
                                      </button>
                                      <details>
                                        <summary>Payload SHA-256</summary>
                                        <code>{ref.payload_hash}</code>
                                      </details>
                                    </>
                                  )}
                                </div>
                              ))
                          )}
                          {showEvidence && references.length > 100 && (
                            <p className="notice">
                              Showing the first 100 of {references.length}{" "}
                              retained references. Narrow the execution scope
                              for further inspection.
                            </p>
                          )}
                          {references.length > 3 && !showEvidence && (
                            <p className="subtle">
                              {references.length - 3} additional references ·
                              inspect evidence to see all
                            </p>
                          )}
                          {!showEvidence && (
                            <button className="primary full" onClick={inspect}>
                              <FileMagnifyingGlassIcon size={19} />
                              Inspect evidence
                            </button>
                          )}
                          {eventId && (
                            <State
                              loading={sourceEvent.loading}
                              error={sourceEvent.error}
                            >
                              <details open className="source-record">
                                <summary>Original lineage record</summary>
                                <pre>
                                  {JSON.stringify(sourceEvent.data, null, 2)}
                                </pre>
                              </details>
                            </State>
                          )}
                          <p className="small-note">
                            Failure reasons are source reports, not
                            independently verified root causes. Execution
                            attempts remain visible beside this lineage
                            evidence.
                          </p>
                        </>
                      )}
                    </State>
                  </aside>
                </div>
              </State>
            </State>
          </>
        )}
        <footer className="page-footer">
          <span>
            PipeGuard <span className="separator">/</span> Local-first
            observability
          </span>
          <span>Evidence retained. Recovery requires human approval.</span>
        </footer>
      </main>
    </>
  );
}
