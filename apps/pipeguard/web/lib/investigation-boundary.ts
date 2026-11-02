/** Only known pre-generation rejections permit forgetting a submission key. */
export function submissionDefinitelyRejected(error: unknown): boolean {
  return (
    typeof error === "string" &&
    new Set([
      "invalid_investigation_request",
      "invalid_request",
      "authentication_required",
      "administrator_required",
      "incident_not_found",
      "evidence_bundle_not_found",
      "request_key_scope_conflict",
      "local_same_origin_required",
      "dashboard_not_configured",
      "investigation_disabled",
      "investigation_busy",
      "investigation_pending",
      "investigation_cooldown",
      "investigation_daily_limit",
    ]).has(error)
  );
}
