"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { submissionDefinitelyRejected } from "@/lib/investigation-boundary";

type RecordView = {
  id: string;
  request_key: string;
  bundle_id: string;
  created_at: string;
  model: string;
  prompt_version: string;
  grounding_policy_current: boolean;
  state: "pending" | "unknown" | "completed" | "failed";
  input_hash: string;
  input_integrity_valid: boolean;
  input_payload: {
    citation_map: Record<
      string,
      { table: string; id: string; content_hash: string }
    >;
  };
  outcome: {
    provider_call_attempted?: boolean;
    error?: string;
    result?: {
      abstained: boolean;
      abstention_reason: string;
      hypotheses: {
        category?: string;
        explanation: string;
        confidence: string;
        supporting_evidence: string[];
        contradicting_evidence: string | string[] | null;
      }[];
      next_checks: string[];
    };
  } | null;
};
type HistoryPage = {
  items: RecordView[];
  has_more: boolean;
  next_before: string | null;
};
const messages: Record<string, string> = {
  unsupported_hypothesis_category:
    "Groq proposed a finding that the selected evidence does not support. The response was rejected.",
  hypothesis_support_missing:
    "The cited evidence did not support the proposed finding. The response was rejected.",
  unsupported_contradiction:
    "Groq treated unrelated attempts or facts as contradictions. The response was rejected.",
  provider_rate_limited:
    "Groq's available quota was reached. Wait before starting a new request.",
  invalid_investigation_response:
    "Groq returned a response outside the accepted format. No result was accepted.",
  provider_evidence_limit:
    "The selected evidence exceeds this request's size limit. It was not sent to Groq.",
  investigation_disabled: "Hosted investigation is disabled on the API server.",
  investigation_busy:
    "Another investigation is running. Refresh history before retrying.",
  investigation_pending:
    "A recent request has no recorded outcome. Refresh history and wait two minutes before starting a separate request.",
  investigation_cooldown:
    "Wait at least one minute between new investigations.",
  investigation_daily_limit:
    "The local limit of 20 requests per rolling 24 hours has been reached.",
  investigation_connection_unknown:
    "The submission outcome is unconfirmed. Refresh history or retry the same submission; do not assume it failed.",
};
const findingLabels: Record<string, string> = {
  reported_source_failure:
    "The producer reported source unavailability or a connection timeout. The underlying cause remains unverified.",
  reported_execution_failure:
    "The producer reported an execution error. The underlying cause remains unverified.",
  reported_validation_failure:
    "The producer reported a validation failure. The underlying cause remains unverified.",
  reported_quality_failure:
    "A stored quality report includes failed or errored checks. Their underlying cause remains unverified.",
  source_evidence_gap:
    "Stored evidence reports incomplete independent source coverage or a source-access problem. This limits conclusions about that observed episode.",
  lineage_evidence_gap:
    "Stored evidence includes a partial lineage report. This is an evidence limitation, not a proven execution failure cause.",
  conflicting_execution_reports:
    "At capture time, stored execution evidence required reconciliation. Its reliable outcome could not yet be inferred.",
};
export function Investigations({
  incidentId,
  demo,
}: {
  incidentId: string;
  demo: boolean;
}) {
  const [page, setPage] = useState<HistoryPage>({
    items: [],
    has_more: false,
    next_before: null,
  });
  const [loading, setLoading] = useState(false),
    [busy, setBusy] = useState(false);
  const [error, setError] = useState(""),
    [confirmed, setConfirmed] = useState(false);
  const [unconfirmed, setUnconfirmed] = useState("");
  const active = useRef<AbortController | null>(null);
  const historyRequest = useRef<AbortController | null>(null);
  const inFlight = useRef(false);
  const submissionKey = useRef("");
  const storageKey = `pipeguard-investigation:${incidentId}`;
  const load = useCallback(
    async (before?: string) => {
      if (demo) return;
      historyRequest.current?.abort();
      const controller = new AbortController();
      historyRequest.current = controller;
      setLoading(true);
      setError("");
      try {
        const response = await fetch(
          `/api/investigations?id=${incidentId}${before ? `&before=${before}` : ""}`,
          {
            cache: "no-store",
            signal: controller.signal,
          },
        );
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "history_unavailable");
        if (!controller.signal.aborted) {
          setPage((old) => ({
            ...data,
            items: before
              ? [
                  ...old.items,
                  ...data.items.filter(
                    (r: RecordView) => !old.items.some((x) => x.id === r.id),
                  ),
                ]
              : data.items,
          }));
          const key = submissionKey.current;
          if (
            key &&
            data.items.some((r: RecordView) => r.request_key === key)
          ) {
            submissionKey.current = "";
            setUnconfirmed("");
            try {
              sessionStorage.removeItem(storageKey);
            } catch {
              /* The in-memory key is reconciled even when storage is unavailable. */
            }
          }
        }
      } catch (e) {
        if (!controller.signal.aborted)
          setError(e instanceof Error ? e.message : "history_unavailable");
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    },
    [demo, incidentId, storageKey],
  );
  useEffect(() => {
    try {
      submissionKey.current = sessionStorage.getItem(storageKey) || "";
      setUnconfirmed(submissionKey.current);
    } catch {
      /* Optional recovery hint. */
    }
    void load();
    return () => {
      active.current?.abort();
      historyRequest.current?.abort();
    };
  }, [load, storageKey]);
  async function submit(replay = false) {
    if (!confirmed || inFlight.current || demo) return;
    const key = replay ? unconfirmed : crypto.randomUUID();
    if (!key) return;
    inFlight.current = true;
    submissionKey.current = key;
    setUnconfirmed(key);
    try {
      sessionStorage.setItem(storageKey, key);
    } catch {
      /* Request key is also shown below. */
    }
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/investigations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          incident_id: incidentId,
          request_key: key,
          free_plan_confirmed: true,
        }),
      });
      const data = await response.json();
      if (controller.signal.aborted) return;
      if (!response.ok) {
        // A validated rejection did not start a request; network failures remain unconfirmed.
        const rejectedBeforeGeneration = submissionDefinitelyRejected(
          data.error,
        );
        if (rejectedBeforeGeneration) {
          submissionKey.current = "";
          setUnconfirmed("");
          try {
            sessionStorage.removeItem(storageKey);
          } catch {
            /* Optional hint. */
          }
        }
        throw new Error(
          rejectedBeforeGeneration
            ? data.error
            : "investigation_connection_unknown",
        );
      }
      if (!controller.signal.aborted) {
        submissionKey.current = "";
        setUnconfirmed("");
        try {
          sessionStorage.removeItem(storageKey);
        } catch {
          /* Optional hint. */
        }
        await load();
      }
    } catch (e) {
      if (!controller.signal.aborted)
        setError(
          e instanceof Error ? e.message : "investigation_connection_unknown",
        );
    } finally {
      inFlight.current = false;
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  return (
    <section aria-label="AI investigation" className="investigation-panel">
      <h3>AI investigation · advisory</h3>
      <p>
        Possible explanations from stored evidence. AI cannot confirm a root
        cause, change this incident or execute recovery.
      </p>
      {demo ? (
        <p>
          Unavailable in preview. Demonstration records are not submitted to
          Groq.
        </p>
      ) : (
        <>
          <label>
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />{" "}
            Send only the redacted evidence projection to Groq. I confirm this
            organization is on the Free plan.
          </label>
          <div className="action-row">
            <button
              className="primary-button"
              disabled={
                !confirmed ||
                busy ||
                loading ||
                !!unconfirmed ||
                page.items.some((r) => r.state === "pending")
              }
              onClick={() => void submit()}
            >
              {busy ? "Investigating…" : "Investigate incident"}
            </button>
            <button
              className="secondary-button"
              disabled={busy || loading}
              onClick={() => void load()}
            >
              Refresh investigations
            </button>
          </div>
          {unconfirmed && (
            <div role="status">
              <p>
                Unconfirmed submission key:{" "}
                <span className="mono">{unconfirmed}</span>. Refresh history
                first. Retrying this same key never regenerates a recorded
                request.
              </p>
              <button
                disabled={!confirmed || busy || loading}
                onClick={() => void submit(true)}
              >
                Retry same submission
              </button>
            </div>
          )}
          {error && (
            <p role="alert">
              {messages[error] || `Investigation unavailable: ${error}`}
            </p>
          )}
          {loading && <p role="status">Loading saved investigations…</p>}
          {!loading && !busy && !page.items.length && (
            <p>No saved investigations for this incident.</p>
          )}
          {page.items.map((record) => (
            <article key={record.id} className="attempt-card">
              <h4>
                {record.state} · {new Date(record.created_at).toLocaleString()}
              </h4>
              <p>
                {record.model} · Bundle{" "}
                <span className="mono">{record.bundle_id}</span>
              </p>
              {!record.input_integrity_valid ? (
                <p role="alert">
                  Stored input integrity mismatch. Do not rely on this result.
                </p>
              ) : (
                <>
                  {record.state === "pending" && (
                    <p>
                      Request saved before generation. Refresh to check its
                      outcome; no automatic retry is running.
                    </p>
                  )}
                  {record.state === "unknown" && (
                    <p>
                      No terminal outcome was recorded within two minutes. The
                      provider may have processed this request. This is not a
                      confirmed failure.
                    </p>
                  )}
                  {record.outcome?.error && (
                    <>
                      <p>
                        {messages[record.outcome.error] ||
                          "The investigation failed. No result was accepted; inspect the saved failure details."}
                      </p>
                      <details>
                        <summary>Technical failure details</summary>
                        <code>{record.outcome.error}</code>
                      </details>
                    </>
                  )}
                  {record.outcome?.result &&
                    !record.grounding_policy_current && (
                      <details>
                        <summary>
                          Earlier unreviewed response · audit only
                        </summary>
                        <p>
                          This response predates the current grounding rules and
                          is not endorsed by them.
                        </p>
                        <pre>
                          {JSON.stringify(record.outcome.result, null, 2)}
                        </pre>
                      </details>
                    )}
                  {record.outcome?.result &&
                    record.grounding_policy_current && (
                      <>
                        {record.outcome.provider_call_attempted === false && (
                          <p>
                            The local evidence gate abstained without contacting
                            Groq.
                          </p>
                        )}
                        {record.outcome.result.abstained && (
                          <p>
                            <strong>Insufficient evidence:</strong>{" "}
                            {record.outcome.result.abstention_reason}
                          </p>
                        )}
                        <ol>
                          {record.outcome.result.hypotheses.map((h, i) => (
                            <li key={i}>
                              <p>
                                {record.grounding_policy_current && h.category
                                  ? findingLabels[h.category] ||
                                    "Unrecognized finding; requires review."
                                  : "Earlier unverified model response; not checked under the current grounding rules."}
                              </p>
                              <details>
                                <summary>
                                  Read unverified model explanation
                                </summary>
                                <p>{h.explanation}</p>
                              </details>
                              <p>
                                Model confidence: {h.confidence} · Supporting:{" "}
                                {h.supporting_evidence.join(", ")} ·
                                Contradicting:{" "}
                                {(typeof h.contradicting_evidence === "string"
                                  ? h.contradicting_evidence
                                  : h.contradicting_evidence?.join(", ")) ||
                                  "none cited"}
                              </p>
                            </li>
                          ))}
                        </ol>
                        <h4>Suggested human checks</h4>
                        <ul>
                          {record.outcome.result.next_checks.map((check, i) => (
                            <li key={i}>{check.replaceAll("_", " ")}</li>
                          ))}
                        </ul>
                      </>
                    )}
                </>
              )}
              <details>
                <summary>
                  Inspect exact evidence projection and citations
                </summary>
                <p>
                  Input hash: <span className="mono">{record.input_hash}</span>
                </p>
                <pre>{JSON.stringify(record.input_payload, null, 2)}</pre>
              </details>
            </article>
          ))}
          {page.has_more && (
            <button
              disabled={loading || busy}
              onClick={() => void load(page.next_before || undefined)}
            >
              Load older investigations
            </button>
          )}
          <p>
            One request at a time; one minute between new requests; at most 20
            per rolling 24 hours. Account Free-plan status is your confirmation,
            not verified by the API.
          </p>
        </>
      )}
    </section>
  );
}
