/** Fixed review endpoints only; no browser-supplied target, command or actor. */
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const validUUID = (value: unknown): value is string =>
  typeof value === "string" && value.length === 36 && uuid.test(value);
export type ReviewRequest = {
  operation: "propose" | "decide";
  incident_id: string;
  request_key: string;
  proposal_id?: string;
  proposal_hash?: string;
  decision?: "approve" | "reject";
  confirmed?: true;
};
export function recoveryMutation(
  value: unknown,
): { path: string; body: string } | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const v = value as Record<string, unknown>;
  if (!validUUID(v.incident_id) || !validUUID(v.request_key)) return null;
  const path = `/v1/incidents/${v.incident_id}/recovery-proposals`;
  const keys = Object.keys(v).sort().join(",");
  if (v.operation === "propose" && keys === "incident_id,operation,request_key")
    return { path, body: JSON.stringify({ request_key: v.request_key }) };
  if (
    v.operation === "decide" &&
    keys ===
      "confirmed,decision,incident_id,operation,proposal_hash,proposal_id,request_key" &&
    validUUID(v.proposal_id) &&
    typeof v.proposal_hash === "string" &&
    v.proposal_hash.length === 64 &&
    /^[0-9a-f]{64}$/.test(v.proposal_hash) &&
    (v.decision === "approve" || v.decision === "reject") &&
    v.confirmed === true
  )
    return {
      path: `${path}/${v.proposal_id}/decisions`,
      body: JSON.stringify({
        request_key: v.request_key,
        proposal_hash: v.proposal_hash,
        decision: v.decision,
        confirmed: true,
      }),
    };
  return null;
}
export function recoveryRead(id: string, before: string | null): string | null {
  return validUUID(id) && (before === null || validUUID(before))
    ? `/v1/incidents/${id}/recovery-proposals?limit=20${before ? `&before=${before}` : ""}`
    : null;
}
/** Only fixed pre-commit rejections allow a fresh explicit request. */
export function recoveryDefinitelyRejected(code: unknown): boolean {
  return (
    typeof code === "string" &&
    new Set([
      "invalid_recovery_request",
      "invalid_request",
      "local_same_origin_required",
      "dashboard_not_configured",
      "authentication_required",
      "administrator_required",
      "incident_not_found",
      "recovery_proposal_not_found",
      "recovery_busy",
      "recovery_key_scope_conflict",
      "recovery_already_decided",
      "recovery_hash_mismatch",
      "recovery_expired",
      "recovery_policy_changed",
      "recovery_evidence_changed",
      "recovery_evidence_incomplete",
      "recovery_incident_resolved",
      "recovery_condition_unsupported",
      "recovery_integration_disabled",
      "recovery_target_not_configured",
      "recovery_monitor_stale",
      "recovery_source_incomplete_or_stale",
      "recovery_dag_paused_or_unknown",
      "recovery_evidence_limit",
      "recovery_not_latest_run",
      "recovery_run_unsettled",
      "recovery_attempt_unavailable",
      "recovery_attempt_unsettled",
      "recovery_independent_failure_missing",
      "recovery_ingestion_unsettled",
    ]).has(code)
  );
}
