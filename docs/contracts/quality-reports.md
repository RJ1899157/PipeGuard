# Quality report v1

`POST /v1/quality-reports` accepts an authenticated, integration-scoped, versioned report. The same local body-size, origin and secret-handling boundaries as execution ingestion apply.

Required fields: integer `schema_version=1`, `event_id`, integration/job UUIDs, external run identifier, positive integer attempt number, timezone-aware `occurred_at`, boolean `inventory_complete`, and up to 100 `checks`. Extra fields are rejected. Identifiers follow the execution contract. Each check contains a unique `rule_id`, 64-character lowercase SHA-256 `rule_version`, status (`pass`, `fail`, `error`, `skipped`, `unknown`), and optional nonnegative integer `failures` count. Complete inventories cannot be empty.

The canonical validated report is immutable. Exact replay returns its existing observation UUID. Reusing an identity for different content returns 409 and records a hash-only conflict observation. HTTP 202 acknowledges durable receipt; the asynchronous worker evaluates incidents. `/v1/observations/{id}` exposes scoped provenance and the allowlisted report. No raw SQL, result rows, exception messages or credentials are accepted by the contract.

Rule versions fingerprint implementation/configuration and dbt version; the example also incorporates macro content and parent model checksums. Different versions do not implicitly recover old failures. Reports are per attempt, not a current-state overwrite. A passing later attempt can recover an earlier failure for the same version; contradictory same-attempt outcomes remain uncertain.

Completeness is a producer claim relative to its manifest. The example requires matching invocation IDs, unique result IDs and results for every enabled test in the full-build manifest. Missing, oversized, invalid or mixed artifacts produce incomplete coverage. A changed complete rule set produces a separate coverage condition. This is not independent proof that every desired business rule exists.

Machine-readable schema: [quality report v1](quality-report-v1.schema.json). Runtime API contracts: [OpenAPI](http-api-v1.openapi.json).

## Source references

- [dbt run results](https://docs.getdbt.com/reference/artifacts/run-results-json): result identity, execution status and manifest references.
- [Airflow task states](https://airflow.apache.org/docs/apache-airflow/3.3.2/core-concepts/tasks.html): independent orchestration state semantics.

## Read history

`GET /v1/jobs/{job_id}/quality-reports` returns immutable quality-report observations in receipt order (newest first), with stable UUID tie-breaking. Authentication and job/integration scope are required; inaccessible and nonexistent jobs both return 404. Optional `external_run_id` and `attempt_number` filters select an execution scope. `limit` (1–100) and `offset` (0–100000) return the standard `items`, `limit`, `offset`, `has_more` page envelope.

Each item includes its observation UUID, job UUID, source `occurred_at`, `received_at`, and the validated quality-report payload. Reports are not collapsed into a latest-pass projection: contradictory results, late deliveries and earlier attempts remain independently inspectable. Empty history means no retained report in that scope, not passing quality. No raw SQL, warehouse rows or arbitrary error text is exposed.

## Complete-history read summary

The quality-history API returns `summary.report_count`, `conflicting_rule_count`, `has_conflicts` and `scope=filtered_history`. Rule identities include external run, attempt, rule ID and version. This summary examines every report matching the filters, rather than just the displayed page. A snapshot capture freezes rows and summary together; later reports appear on Refresh. The dashboard labels this scope explicitly. See [HTTP contract](http-api.md#captured-list-reads) for bounded capture/expiry behavior.
