/** Executable operations have their own fixed routes and replay namespace. */
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const validId = (v: unknown): v is string =>
  typeof v === "string" && v.length === 36 && uuid.test(v);
export type ActionRequest = {
  operation: "propose" | "decide" | "dispatch" | "reconcile";
  incident_id: string;
  request_key: string;
  action_id?: string;
  proposal_hash?: string;
  decision?: "approve" | "reject" | "cancel";
  confirmed?: true;
};
export function actionMutation(
  value: unknown,
): { path: string; body: string } | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const v = value as Record<string, unknown>;
  if (!validId(v.incident_id) || !validId(v.request_key)) return null;
  const root = `/v1/incidents/${v.incident_id}/recovery-actions`;
  const keys = Object.keys(v).sort().join(",");
  if (v.operation === "propose" && keys === "incident_id,operation,request_key")
    return { path: root, body: JSON.stringify({ request_key: v.request_key }) };
  if (!validId(v.action_id)) return null;
  if (
    v.operation === "reconcile" &&
    keys === "action_id,incident_id,operation,request_key"
  )
    return {
      path: `${root}/${v.action_id}/reconcile`,
      body: JSON.stringify({ request_key: v.request_key }),
    };
  if (
    v.confirmed !== true ||
    typeof v.proposal_hash !== "string" ||
    v.proposal_hash.length !== 64 ||
    !/^[0-9a-f]{64}$/.test(v.proposal_hash)
  )
    return null;
  const body = {
    request_key: v.request_key,
    proposal_hash: v.proposal_hash,
    confirmed: true,
  };
  if (
    v.operation === "dispatch" &&
    keys ===
      "action_id,confirmed,incident_id,operation,proposal_hash,request_key"
  )
    return {
      path: `${root}/${v.action_id}/dispatch`,
      body: JSON.stringify(body),
    };
  if (
    v.operation === "decide" &&
    keys ===
      "action_id,confirmed,decision,incident_id,operation,proposal_hash,request_key" &&
    (v.decision === "approve" ||
      v.decision === "reject" ||
      v.decision === "cancel")
  )
    return {
      path: `${root}/${v.action_id}/decisions`,
      body: JSON.stringify({ ...body, decision: v.decision }),
    };
  return null;
}
export function actionRead(id: string, before: string | null): string | null {
  return validId(id) && (before === null || validId(before))
    ? `/v1/incidents/${id}/recovery-actions?limit=5${before ? `&before=${before}` : ""}`
    : null;
}
/** Errors that may follow committed intent must always retain the exact request. */
export function actionDefinitelyRejected(
  value: ActionRequest,
  code: unknown,
): boolean {
  if (typeof code !== "string") return false;
  if (
    new Set([
      "invalid_recovery_action_request",
      "local_same_origin_required",
      "administrator_required",
      "authentication_required",
      "incident_not_found",
      "recovery_action_not_found",
      "invalid_request",
    ]).has(code)
  )
    return true;
  if (value.operation === "reconcile")
    return code === "recovery_dispatch_not_found";
  return new Set([
    "recovery_execution_disabled",
    "recovery_execution_not_approved",
    "recovery_already_decided",
    "recovery_already_dispatched",
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
    "recovery_source_identity_missing",
    "recovery_failed_run_already_reserved",
    "recovery_prior_dispatch_unsettled",
    "recovery_source_unhealthy",
    "recovery_source_dag_unavailable",
    "recovery_source_inventory_incomplete",
    "recovery_source_run_unsettled",
    "recovery_source_failure_changed",
  ]).has(code);
}
