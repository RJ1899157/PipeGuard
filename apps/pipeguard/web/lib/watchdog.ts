export type WatchdogState = {
  version: 1;
  checked_at: string;
  status: { api: string; database: string; monitor: string };
  notification: string;
};
/** Return only the public allowlist, even if a local file contains extra fields. */
export function parseWatchdog(value: unknown): WatchdogState | null {
  if (!value || typeof value !== "object") return null;
  const v = value as Record<string, unknown>;
  const s = v.status as Record<string, unknown> | undefined;
  if (
    v.version !== 1 ||
    typeof v.checked_at !== "string" ||
    !Number.isFinite(Date.parse(v.checked_at)) ||
    !s ||
    typeof s !== "object" ||
    typeof s.api !== "string" ||
    !["healthy", "invalid_response", "unreachable"].includes(s.api) ||
    typeof s.database !== "string" ||
    !["healthy", "unreachable"].includes(s.database) ||
    typeof s.monitor !== "string" ||
    !["fresh", "stale", "unmonitored", "unknown"].includes(s.monitor) ||
    typeof v.notification !== "string" ||
    !["none", "disabled", "unavailable", "submitted", "failed"].includes(
      v.notification,
    )
  )
    return null;
  return {
    version: 1,
    checked_at: v.checked_at,
    status: {
      api: s.api,
      database: s.database,
      monitor: s.monitor,
    },
    notification: v.notification,
  };
}
export function watchdogFresh(state: WatchdogState, now = Date.now()): boolean {
  const age = now - Date.parse(state.checked_at);
  return age >= -30000 && age <= 45000;
}
