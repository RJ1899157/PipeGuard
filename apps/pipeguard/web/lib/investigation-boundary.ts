const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export function investigationId(value: unknown): value is string {
  return typeof value === "string" && value.length === 36 && uuid.test(value);
}

/** Only this explicit consent and fixed request shape can reach generation. */
export function investigationSubmission(
  value: unknown,
): { id: string; body: string } | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const v = value as Record<string, unknown>;
  if (
    Object.keys(v).sort().join(",") !==
      "free_plan_confirmed,incident_id,request_key" ||
    !investigationId(v.incident_id) ||
    !investigationId(v.request_key) ||
    v.free_plan_confirmed !== true
  )
    return null;
  return {
    id: v.incident_id,
    body: JSON.stringify({
      request_key: v.request_key,
      free_plan_confirmed: true,
    }),
  };
}

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
