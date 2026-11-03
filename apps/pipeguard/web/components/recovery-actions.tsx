"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  actionDefinitelyRejected,
  actionMutation,
  type ActionRequest,
} from "@/lib/recovery-actions-boundary";

type Dispatch = {
  id: string;
  state: string;
  last_known_state: string;
  external_run_id: string;
  events: {
    sequence: number;
    source: string;
    state: string;
    code: string;
    created_at: string;
  }[];
};
type Action = {
  id: string;
  payload_hash: string;
  expires_at: string;
  expired: boolean;
  payload: {
    impact: string;
    parameters: { dag_id: string; body: { dag_run_id: string } };
  };
  decisions: { decision: string; created_at: string; actor: string }[];
  dispatch: Dispatch | null;
};
type Page = {
  items: Action[];
  has_more: boolean;
  next_before: string | null;
  execution_enabled: boolean | null;
  worker_available: boolean;
  eligibility: { can_propose: boolean; reason: string };
};
const reasons: Record<string, string> = {
  recovery_execution_disabled:
    "The operator has disabled executable recovery. Saved history can still be inspected and reconciled.",
  recovery_worker_unknown:
    "The recovery worker is unavailable or its response is unconfirmed. Keep any saved request and check history.",
  recovery_incident_resolved:
    "This incident has recovered; a new recovery run is not appropriate.",
  recovery_condition_unsupported:
    "This incident needs investigation rather than a pipeline rerun.",
  recovery_dag_paused_or_unknown:
    "The sample pipeline is paused or its pause state is unknown. This flow cannot unpause it.",
  recovery_monitor_stale:
    "Monitoring is not fresh enough to authorize recovery.",
  recovery_source_incomplete_or_stale:
    "Independent source coverage is incomplete or too old.",
  recovery_evidence_changed:
    "Evidence changed. Refresh and review a new proposal.",
  recovery_expired: "The proposal expired. Refresh and review a new proposal.",
  recovery_prior_dispatch_unsettled:
    "An earlier dispatch is unresolved. Check its external outcome before another recovery.",
  recovery_failed_run_already_reserved:
    "This failed run already has a reserved action. Another start request is refused.",
  recovery_busy:
    "Another recovery command is in progress. Retain the saved request and check again.",
};
const states: Record<string, string> = {
  unknown: "Outcome unconfirmed",
  conflict: "Conflicting reports",
  queued: "New run queued",
  running: "New run running",
  succeeded: "New run succeeded",
  failed: "New run failed",
  rejected: "Start request rejected",
};

export function RecoveryActions({
  incidentId,
  demo,
}: {
  incidentId: string;
  demo: boolean;
}) {
  const [page, setPage] = useState<Page | null>(null);
  const [loading, setLoading] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [pending, setPending] = useState<ActionRequest | null>(null);
  const [approvalCheck, setApprovalCheck] = useState(""),
    [startCheck, setStartCheck] = useState("");
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [now, setNow] = useState(() => Date.now());
  const [expanded, setExpanded] = useState("");
  const read = useRef<AbortController | null>(null),
    write = useRef<AbortController | null>(null),
    inFlight = useRef(false);
  const storage = `pipeguard-recovery-actions:${incidentId}`;
  const load = useCallback(
    async (trail: (string | null)[] = [null]) => {
      if (demo) return;
      read.current?.abort();
      const controller = new AbortController();
      read.current = controller;
      setLoading(true);
      setError("");
      setApprovalCheck("");
      setStartCheck("");
      try {
        const before = trail.at(-1);
        const response = await fetch(
          `/api/recovery-actions?id=${incidentId}${before ? `&before=${before}` : ""}`,
          { cache: "no-store", signal: controller.signal },
        );
        const data = await response.json();
        if (!response.ok)
          throw new Error(data.error || "recovery_worker_unknown");
        if (!controller.signal.aborted) {
          setPage(data);
          setCursors(trail);
          setNow(Date.now());
        }
      } catch (e) {
        if (!controller.signal.aborted)
          setError(e instanceof Error ? e.message : "recovery_worker_unknown");
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    },
    [demo, incidentId],
  );
  useEffect(() => {
    if (!demo) {
      try {
        const saved = JSON.parse(sessionStorage.getItem(storage) || "null");
        if (saved?.incident_id === incidentId && actionMutation(saved))
          setPending(saved);
      } catch {
        /* In-memory retention remains available if session storage is unavailable. */
      }
      void load();
    }
    return () => {
      read.current?.abort();
      write.current?.abort();
    };
  }, [demo, incidentId, storage, load]);
  useEffect(() => {
    const next = Math.min(
      ...(page?.items || [])
        .map((row) => Date.parse(row.expires_at))
        .filter((time) => time > now),
    );
    if (!Number.isFinite(next)) return;
    const timer = setTimeout(
      () => setNow(Date.now()),
      Math.min(next - now + 50, 2147483647),
    );
    return () => clearTimeout(timer);
  }, [page, now]);
  async function submit(value: ActionRequest) {
    if (demo || inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    setPending(value);
    try {
      sessionStorage.setItem(storage, JSON.stringify(value));
    } catch {
      /* Retain in memory. */
    }
    const controller = new AbortController();
    write.current = controller;
    try {
      const response = await fetch("/api/recovery-actions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(value),
        signal: controller.signal,
      });
      const data = await response.json();
      if (controller.signal.aborted) return;
      if (!response.ok) {
        if (actionDefinitelyRejected(value, data.error)) {
          setPending(null);
          try {
            sessionStorage.removeItem(storage);
          } catch {
            /* Later replay remains idempotent. */
          }
        }
        throw new Error(data.error || "recovery_worker_unknown");
      }
      setPending(null);
      if (value.operation === "propose" && typeof data.id === "string")
        setExpanded(data.id);
      setApprovalCheck("");
      setStartCheck("");
      try {
        sessionStorage.removeItem(storage);
      } catch {
        /* A stored replay cannot repeat a dispatch. */
      }
      await load();
    } catch (e) {
      if (!controller.signal.aborted)
        setError(e instanceof Error ? e.message : "recovery_worker_unknown");
    } finally {
      inFlight.current = false;
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  function request(
    row: Action,
    operation: "decide" | "dispatch" | "reconcile",
    decision?: "approve" | "reject" | "cancel",
  ) {
    const base: ActionRequest = {
      operation,
      incident_id: incidentId,
      action_id: row.id,
      request_key: crypto.randomUUID(),
    };
    void submit(
      operation === "reconcile"
        ? base
        : {
            ...base,
            proposal_hash: row.payload_hash,
            confirmed: true,
            ...(decision ? { decision } : {}),
          },
    );
  }
  const blocked =
    busy || loading || !!pending || !!error || !page?.worker_available;
  return (
    <section
      aria-label="Executable recovery"
      className="investigation-panel execution-panel"
    >
      <h3>
        Executable recovery
        {page
          ? page.execution_enabled === true
            ? " · manual approval required"
            : page.execution_enabled === false
              ? " · disabled"
              : " · unavailable"
          : ""}
      </h3>
      <p>
        This separate flow can start one new sample orders run and change the
        local sample warehouse. Review-only approvals above cannot authorize it.
        Earlier failures remain retained.
      </p>
      {demo ? (
        <p>
          Executable recovery is unavailable in preview. No commands are sent.
        </p>
      ) : (
        <>
          <p>
            {page?.eligibility.can_propose
              ? "Current stored evidence permits a fresh executable proposal. Approval does not start a run."
              : page
                ? reasons[page.eligibility.reason] ||
                  "A required recovery check is not satisfied. Inspect the evidence before proceeding."
                : "Checking executable recovery availability…"}
          </p>
          <div className="action-row">
            <button
              className="button"
              disabled={blocked || !page?.eligibility.can_propose}
              onClick={() =>
                void submit({
                  operation: "propose",
                  incident_id: incidentId,
                  request_key: crypto.randomUUID(),
                })
              }
            >
              Create executable proposal
            </button>
            <button
              className="button"
              disabled={busy || loading}
              onClick={() => void load()}
            >
              Refresh executable recovery
            </button>
          </div>
          {pending && (
            <div role="status">
              <p>
                A saved {pending.operation} request is unconfirmed. Its exact
                body and key are retained. Replaying it cannot send a second
                start request for an existing intent.
              </p>
              {pending.operation === "dispatch" && (
                <p>
                  Retrying may start its first run if the original request never
                  reached the worker. This is not a read-only check. You can
                  refresh history first.
                </p>
              )}
              <button
                className="button"
                disabled={busy || loading}
                onClick={() => void submit(pending)}
              >
                {pending.operation === "dispatch"
                  ? "Retry saved start request (may start run)"
                  : "Retry saved execution request"}
              </button>
            </div>
          )}
          {error && (
            <div role="alert">
              <p>
                {reasons[error] ||
                  "The command could not be confirmed. Refresh history and keep any saved request; do not assume a run failed to start."}
              </p>
              <details>
                <summary>Technical command details</summary>
                <code>{error}</code>
              </details>
            </div>
          )}
          {loading && <p role="status">Loading executable recovery…</p>}
          {page && !page.items.length && (
            <p>No executable recovery proposals recorded for this incident.</p>
          )}
          {page?.items.map((row) => {
            const cancelled = row.decisions.some(
                (d) => d.decision === "cancel",
              ),
              rejected = row.decisions.some((d) => d.decision === "reject"),
              approved = row.decisions.some((d) => d.decision === "approve");
            const expired = row.expired || Date.parse(row.expires_at) <= now;
            const binding = `${row.id}:${row.payload_hash}`;
            return (
              <details
                className="attempt-card"
                key={row.id}
                open={expanded === row.id}
                onToggle={(event) => {
                  const open = event.currentTarget.open;
                  setExpanded((old) =>
                    open ? row.id : old === row.id ? "" : old,
                  );
                }}
              >
                <summary>
                  {row.dispatch
                    ? states[row.dispatch.state] || "Outcome unconfirmed"
                    : cancelled
                      ? "Executable proposal cancelled"
                      : rejected
                        ? "Executable proposal rejected"
                        : approved
                          ? "Execution approved · not started"
                          : "Executable proposal awaiting approval"}
                  {expired ? " · proposal expired" : ""}
                  {" · "}
                  <span>Proposal {row.id.slice(0, 8)}</span>
                </summary>
                <p>{row.payload.impact}</p>
                <p>
                  Target: {row.payload.parameters.dag_id} · Expires:{" "}
                  {new Date(row.expires_at).toLocaleString()}
                </p>
                <details>
                  <summary>Inspect executable proposal and exact hash</summary>
                  <pre>{JSON.stringify(row, null, 2)}</pre>
                </details>
                {!!row.decisions.length && (
                  <ul aria-label="Execution decisions">
                    {row.decisions.map((d) => (
                      <li key={d.decision}>
                        {d.decision === "approve"
                          ? "Execution approved"
                          : d.decision === "cancel"
                            ? "Cancelled before dispatch"
                            : "Execution rejected"}{" "}
                        · {new Date(d.created_at).toLocaleString()}
                      </li>
                    ))}
                  </ul>
                )}
                {!row.dispatch && !cancelled && !rejected && (
                  <>
                    {!approved && !expired && (
                      <>
                        <label>
                          <input
                            type="checkbox"
                            checked={approvalCheck === binding}
                            disabled={blocked}
                            onChange={(e) =>
                              setApprovalCheck(e.target.checked ? binding : "")
                            }
                          />{" "}
                          I reviewed this exact executable proposal and its
                          warehouse impact.
                        </label>
                        <div className="action-row">
                          <button
                            className="button"
                            disabled={
                              blocked ||
                              page.execution_enabled !== true ||
                              approvalCheck !== binding
                            }
                            onClick={() => request(row, "decide", "approve")}
                          >
                            Approve executable proposal
                          </button>
                          <button
                            className="button"
                            disabled={blocked || approvalCheck !== binding}
                            onClick={() => request(row, "decide", "reject")}
                          >
                            Reject executable proposal
                          </button>
                        </div>
                      </>
                    )}
                    {approved && !expired && (
                      <>
                        <label>
                          <input
                            type="checkbox"
                            checked={startCheck === binding}
                            disabled={
                              blocked || page.execution_enabled !== true
                            }
                            onChange={(e) =>
                              setStartCheck(e.target.checked ? binding : "")
                            }
                          />{" "}
                          Start this approved run now. I understand it can
                          change the local sample warehouse.
                        </label>
                        <button
                          className="button"
                          disabled={
                            blocked ||
                            page.execution_enabled !== true ||
                            startCheck !== binding
                          }
                          onClick={() => request(row, "dispatch")}
                        >
                          Start approved sample run
                        </button>
                      </>
                    )}
                    <button
                      className="button"
                      disabled={blocked}
                      onClick={() => request(row, "decide", "cancel")}
                    >
                      Cancel before dispatch
                    </button>
                  </>
                )}
                {row.dispatch && (
                  <>
                    <p>
                      External run: <code>{row.dispatch.external_run_id}</code>
                    </p>
                    {row.dispatch.state === "unknown" && (
                      <p>
                        The latest observation is uncertain. Last known state:{" "}
                        {states[row.dispatch.last_known_state] || "unconfirmed"}
                        . A missing run lookup never permits another start
                        request.
                      </p>
                    )}
                    <button
                      className="button"
                      disabled={
                        blocked ||
                        !page.worker_available ||
                        row.dispatch.events.length >= 100
                      }
                      onClick={() => request(row, "reconcile")}
                    >
                      Check external run outcome
                    </button>
                    {row.dispatch.events.length >= 100 && (
                      <p>
                        This dispatch reached its 100-observation limit. Its
                        retained history remains available.
                      </p>
                    )}
                    <details>
                      <summary>
                        Dispatch history ({row.dispatch.events.length})
                      </summary>
                      {!row.dispatch.events.length ? (
                        <p>
                          Intent was saved, but no external response is
                          recorded. The outcome remains unknown.
                        </p>
                      ) : (
                        <ol>
                          {row.dispatch.events.map((event) => (
                            <li key={event.sequence}>
                              {states[event.state] || "Outcome unconfirmed"} ·{" "}
                              {event.source === "reconcile"
                                ? "independent lookup"
                                : "dispatch response"}{" "}
                              · {new Date(event.created_at).toLocaleString()}
                              <details>
                                <summary>Observation code</summary>
                                <code>{event.code}</code>
                              </details>
                            </li>
                          ))}
                        </ol>
                      )}
                    </details>
                  </>
                )}
              </details>
            );
          })}
          {page && (
            <div className="action-row" aria-label="Executable recovery pages">
              <button
                className="button"
                disabled={busy || loading || cursors.length <= 1}
                onClick={() => void load(cursors.slice(0, -1))}
              >
                Previous executable proposals
              </button>
              <button
                className="button"
                disabled={
                  busy || loading || !page.has_more || !page.next_before
                }
                onClick={() => void load([...cursors, page.next_before])}
              >
                Older executable proposals
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
