"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  recoveryDefinitelyRejected,
  recoveryMutation,
  type ReviewRequest,
} from "@/lib/recovery-boundary";
import { proposalExpired, useExpiry } from "@/lib/use-expiry";

type Proposal = {
  id: string;
  request_key: string;
  payload_hash: string;
  integrity_valid: boolean;
  state: string;
  expires_at: string;
  expired: boolean;
  payload: {
    impact: string;
    mode: string;
    parameters: { dag_id: string; dag_run_id: string };
  };
  decision: {
    request_key: string;
    decision: string;
    created_at: string;
  } | null;
};
type Page = {
  items: Proposal[];
  has_more: boolean;
  next_before: string | null;
  eligibility: { can_propose: boolean; reason: string };
};
const labels: Record<string, string> = {
  recovery_incident_resolved:
    "This incident has already recovered. A recovery proposal is not appropriate.",
  recovery_condition_unsupported:
    "This incident needs investigation rather than an execution retry.",
  recovery_target_not_configured:
    "The server has no approved sample-job recovery binding for this incident.",
  recovery_dag_paused_or_unknown:
    "The sample DAG is paused or its pause state is unknown. Recovery will not change its schedule.",
  recovery_monitor_stale:
    "Monitoring is not fresh enough to review a recovery proposal.",
  recovery_source_incomplete_or_stale:
    "Independent source evidence is incomplete or too old.",
  recovery_evidence_changed:
    "Evidence changed. Refresh and create a new proposal for review.",
  recovery_expired: "This proposal expired. Create a new proposal for review.",
  recovery_not_latest_run:
    "A newer execution exists. This historical failure cannot be proposed for retry.",
  recovery_run_unsettled:
    "An execution is active, uncertain or contradictory. Reconcile it before recovery review.",
  recovery_attempt_unsettled:
    "The execution attempts need reconciliation before recovery review.",
  recovery_evidence_limit:
    "The available history exceeds this bounded recovery review. No evidence was silently dropped.",
  recovery_already_decided:
    "This proposal already has a recorded decision. Refresh its history.",
};
export function Recovery({
  incidentId,
  demo,
}: {
  incidentId: string;
  demo: boolean;
}) {
  const [page, setPage] = useState<Page | null>(null),
    [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false),
    [error, setError] = useState("");
  const [reviewed, setReviewed] = useState(""),
    [pending, setPending] = useState<ReviewRequest | null>(null);
  const active = useRef<AbortController | null>(null),
    mutation = useRef<AbortController | null>(null);
  const inFlight = useRef(false);
  const storage = `pipeguard-recovery-review:${incidentId}`;
  const now = useExpiry(page?.items);
  const blocked = busy || loading || !!pending || !!error;
  const load = useCallback(
    async (before?: string) => {
      if (demo) return;
      active.current?.abort();
      const controller = new AbortController();
      active.current = controller;
      setLoading(true);
      setError("");
      setReviewed("");
      try {
        const response = await fetch(
          `/api/recovery?id=${incidentId}${before ? `&before=${before}` : ""}`,
          {
            cache: "no-store",
            signal: controller.signal,
          },
        );
        const data = await response.json();
        if (!response.ok)
          throw new Error(data.error || "recovery_history_unavailable");
        if (!controller.signal.aborted)
          setPage((old) => ({
            ...data,
            items: before
              ? [
                  ...(old?.items || []),
                  ...data.items.filter(
                    (r: Proposal) => !old?.items.some((x) => x.id === r.id),
                  ),
                ]
              : data.items,
          }));
      } catch (e) {
        if (!controller.signal.aborted)
          setError(
            e instanceof Error ? e.message : "recovery_history_unavailable",
          );
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
        if (saved?.incident_id === incidentId && recoveryMutation(saved))
          setPending(saved);
      } catch {
        /* The server ledger remains authoritative when browser storage is unavailable. */
      }
      void load();
    }
    return () => {
      active.current?.abort();
      mutation.current?.abort();
    };
  }, [demo, incidentId, storage, load]);
  async function submit(value: ReviewRequest) {
    if (inFlight.current || demo) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    setPending(value);
    try {
      sessionStorage.setItem(storage, JSON.stringify(value));
    } catch {
      /* Keep the same key in memory. */
    }
    const controller = new AbortController();
    mutation.current = controller;
    try {
      const response = await fetch("/api/recovery", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(value),
        signal: controller.signal,
      });
      const data = await response.json();
      // Network/database uncertainty retains the exact body/key. A fixed
      // pre-commit rejection permits a separate, explicitly initiated request.
      if (!response.ok) {
        if (
          !controller.signal.aborted &&
          recoveryDefinitelyRejected(data.error)
        ) {
          setPending(null);
          try {
            sessionStorage.removeItem(storage);
          } catch {
            /* Replay is safe if storage cannot be cleared. */
          }
        }
        throw new Error(data.error || "recovery_connection_unknown");
      }
      if (controller.signal.aborted) return;
      setPending(null);
      setReviewed("");
      try {
        sessionStorage.removeItem(storage);
      } catch {
        /* A later replay is idempotent. */
      }
      await load();
    } catch (e) {
      if (!controller.signal.aborted)
        setError(
          e instanceof Error ? e.message : "recovery_connection_unknown",
        );
    } finally {
      inFlight.current = false;
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  return (
    <section aria-label="Recovery review" className="investigation-panel">
      <h3>Recovery review · execution disabled</h3>
      <p>
        A proposal describes one new sample orders run. Review approvals cannot
        start a run now or authorize execution later.
      </p>
      {demo ? (
        <p>Recovery review is unavailable in preview.</p>
      ) : (
        <>
          <p>
            {page?.eligibility.can_propose
              ? "Current stored evidence permits a review-only proposal."
              : page
                ? labels[page.eligibility.reason] ||
                  "Recovery review is blocked by an unmet safety check."
                : "Checking recovery review availability…"}
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
              Create review-only proposal
            </button>
            <button
              className="button"
              disabled={busy || loading}
              onClick={() => void load()}
            >
              Refresh recovery review
            </button>
          </div>
          {pending && (
            <div role="status">
              <p>
                A saved review request still needs confirmation. Its exact key
                and proposal hash are retained.
              </p>
              <button
                className="button"
                disabled={busy || loading}
                onClick={() => void submit(pending)}
              >
                Retry saved review request
              </button>
            </div>
          )}
          {error && (
            <div role="alert">
              <p>
                {labels[error] ||
                  (recoveryDefinitelyRejected(error)
                    ? "The review was rejected. Refresh its current evidence before trying again."
                    : "The review request could not be confirmed. Refresh history and retain the saved request.")}
              </p>
              <details>
                <summary>Technical review details</summary>
                <code>{error}</code>
              </details>
            </div>
          )}
          {loading && <p role="status">Loading recovery review…</p>}
          {page && !page.items.length && (
            <p>No recovery proposals recorded for this incident.</p>
          )}
          {page?.items.map((row) => (
            <article className="attempt-card" key={row.id}>
              <h4>
                {row.state.replaceAll("_", " ")}
                {row.state !== "expired" && proposalExpired(row, now)
                  ? " · expired"
                  : ""}
              </h4>
              {!row.integrity_valid ? (
                <p>Proposal integrity failed. Approval is unavailable.</p>
              ) : (
                <>
                  <p>{row.payload.impact}</p>
                  <p>
                    Target: {row.payload.parameters.dag_id} · Expires:{" "}
                    {new Date(row.expires_at).toLocaleString()}
                  </p>
                  <details>
                    <summary>Inspect exact proposal and hash</summary>
                    <pre>{JSON.stringify(row, null, 2)}</pre>
                  </details>
                  {!row.decision && !proposalExpired(row, now) && (
                    <>
                      <label>
                        <input
                          type="checkbox"
                          checked={reviewed === row.id}
                          disabled={blocked}
                          onChange={(e) =>
                            setReviewed(e.target.checked ? row.id : "")
                          }
                        />{" "}
                        I reviewed this exact proposal and its impact. This is a
                        review-only decision.
                      </label>
                      <div className="action-row">
                        {(["approve", "reject"] as const).map((decision) => (
                          <button
                            className="button"
                            key={decision}
                            disabled={reviewed !== row.id || blocked}
                            onClick={() =>
                              void submit({
                                operation: "decide",
                                incident_id: incidentId,
                                request_key: crypto.randomUUID(),
                                proposal_id: row.id,
                                proposal_hash: row.payload_hash,
                                decision,
                                confirmed: true,
                              })
                            }
                          >
                            {decision === "approve"
                              ? "Approve review only"
                              : "Reject proposal"}
                          </button>
                        ))}
                      </div>
                    </>
                  )}
                </>
              )}
            </article>
          ))}
          {page?.has_more && (
            <button
              className="button"
              disabled={busy || loading}
              onClick={() => void load(page.next_before || undefined)}
            >
              Load older recovery proposals
            </button>
          )}
        </>
      )}
    </section>
  );
}
