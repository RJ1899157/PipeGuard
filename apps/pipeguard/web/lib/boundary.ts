/** Local owner UI: deny DNS rebinding and cross-site browser requests. */
export function localRequestAllowed(headers: Headers): boolean {
  const host = headers.get("host");
  if (host !== "127.0.0.1:3000" && host !== "localhost:3000") return false;
  const origin = headers.get("origin");
  if (origin && origin !== `http://${host}`) return false;
  const site = headers.get("sec-fetch-site");
  return !site || site === "same-origin" || site === "none";
}
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export function readPath(query: URLSearchParams): string | null {
  const kind = query.get("kind");
  const id = query.get("id") || "";
  const offset = Number(query.get("offset") || 0);
  if (!Number.isSafeInteger(offset) || offset < 0 || offset > 100000)
    return null;
  if (
    ["jobs", "runs", "attempts", "incidents", "history"].includes(kind || "")
  ) {
    const page = `limit=50&offset=${offset}`;
    if (kind === "jobs") return `/v1/jobs?${page}`;
    if (kind === "incidents") return `/v1/incidents?${page}`;
    if (!uuid.test(id)) return null;
    if (kind === "runs") return `/v1/runs?job_id=${id}&${page}`;
    if (kind === "attempts") return `/v1/runs/${id}/attempts?${page}`;
    return `/v1/incidents/${id}/history?${page}`;
  }
  if (kind === "coverage") return "/v1/monitoring/coverage";
  if (!uuid.test(id)) return null;
  if (kind === "lineage") {
    const run = query.get("run");
    const attempt = query.get("attempt");
    if (
      !run ||
      run.length > 255 ||
      !attempt ||
      !/^[1-9][0-9]{0,8}$/.test(attempt)
    )
      return null;
    return `/v1/jobs/${id}/lineage?${new URLSearchParams({ external_run_id: run, attempt_number: attempt })}`;
  }
  if (kind === "lineage-event") return `/v1/lineage-events/${id}`;
  return null;
}
