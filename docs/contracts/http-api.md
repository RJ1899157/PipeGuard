# Local HTTP API v1

Status: implemented and verified with PostgreSQL using a restricted runtime role.
The reference launcher binds only to `127.0.0.1:8000`. This is a local synthetic-data
checkpoint; deployment beyond loopback requires a separate identity, TLS and security
review. The local dashboard provides monitoring reads, explicit advisory investigation,
and separate review-only and executable recovery controls. Executable recovery is
normally disabled; its approval and start boundaries are described below.

[OpenAPI contract](http-api-v1.openapi.json) · [Execution events](execution-events.md)
· [Setup](../development/setup.md)

## Authentication and authorization

Every `/v1` route and readiness check requires an `Authorization: Bearer` header.
The private administrator token is generated in `.env`. The administrator can
provision integrations/jobs, issue and revoke producer credentials, disable an
integration and read monitoring metadata. Rotating the administrator token requires
updating private configuration and restarting the API. The current operator token
is not a named-user login or a recorded human recovery approval.

Producer credentials are random 256-bit values, returned once at issuance. The
database stores only their SHA-256 hashes. They authorize event submission and
reads/reprocessing for one integration. Cross-integration record lookups return
404; submitting for another integration returns 403. Revoking a credential or
disabling its integration rejects subsequent producer authentication. Requests
already authorized may finish; revocation is not an in-flight cancellation system.
For rotation, issue a replacement, switch the producer, then revoke the old key.
There is no token expiry or interactive login in this local checkpoint.

Save issuance responses privately. Do not put tokens in URLs, screenshots, fixtures
or shared logs. API responses carry `Cache-Control: no-store`; the launcher disables
request access logs and proxy-header trust. Only `/health/live` is public and it
returns no database or version information. `/v1/openapi.json` is administrator-only.
Interactive documentation routes are disabled.

## Operations

| Method and path                          | Access                           | Behaviour                                              |
| ---------------------------------------- | -------------------------------- | ------------------------------------------------------ |
| `GET /health/live`                       | Public                           | Process liveness                                       |
| `GET /health/ready`                      | Administrator                    | Database availability                                  |
| `GET /v1/openapi.json`                   | Administrator                    | OpenAPI schema                                         |
| `POST /v1/integrations`                  | Administrator                    | Create producer integration                            |
| `GET /v1/integrations`                   | Administrator                    | Paginated integration catalog                          |
| `POST /v1/integrations/{id}/disable`     | Administrator                    | Disable integration and future producer authentication |
| `POST /v1/jobs`                          | Administrator                    | Create job under an enabled integration                |
| `GET /v1/jobs`                           | Administrator or scoped producer | Paginated job catalog                                  |
| `POST /v1/integrations/{id}/credentials` | Administrator                    | Issue producer token once                              |
| `POST /v1/credentials/{id}/revoke`       | Administrator                    | Revoke producer token                                  |
| `POST /v1/events`                        | Administrator or scoped producer | Commit observation, then attempt projection            |
| `GET /v1/events/{id}`                    | Administrator or scoped producer | Read observation status/times without raw payload      |
| `POST /v1/events/{id}/process`           | Administrator or scoped producer | Retry stored observation processing                    |
| `GET /v1/runs`                           | Administrator or scoped producer | Paginated runs; optional `job_id` filter               |
| `GET /v1/runs/{id}`                      | Administrator or scoped producer | Current outcome and uncertainty flag                   |
| `GET /v1/runs/{id}/attempts`             | Administrator or scoped producer | Paginated attempt history and bounded error categories |

Create operations return 201. Event submission returns 202 once its receipt is
committed. Its body includes the internal `event_id`, `replayed`, `processing_state`
and optional `warning`. If a database error interrupts projection after receipt,
202 includes `processing_deferred`; the client can query/retry by the returned ID.
The independent monitor retries pending execution receipts during reconciliation. A processed event can carry a
reconciliation warning; it does not imply the pipeline succeeded or evidence agrees.

List responses include `items`, `limit` (1–100), `offset` (0–100000) and `has_more`.
Ordering includes UUID tie-breaks. Offset pagination is not snapshot isolation:
concurrent inserts can move records between pages. API responses use explicit
allowlists; credential hashes, secret references, arbitrary error messages and raw
source payloads are omitted from monitoring reads.

## Errors and boundaries

Errors use `{"error": "code"}`. Common statuses are 400 invalid body framing, 401 authentication required,
403 forbidden, 404 missing/inaccessible, 409 duplicate identity or event-content
conflict, 408 body-read deadline exceeded, 413 oversized body, 422 invalid input, and 503 database or body-reader capacity unavailable.
Validation errors do not echo input, request bodies, token strings or database
exception details. PostgreSQL constraints remain the authority for concurrent
identity conflicts.

The API bounds actual bodies to 64 KiB including chunked delivery, admits at most
32 concurrent body reads per worker, and imposes a 15-second absolute body-read
deadline. A trickle does not renew the deadline. Oversized declared lengths are
rejected without reading the body; malformed or repeated length headers fail closed.
Body-reader overload returns `request_body_busy` (503) and expiry returns
`request_body_timeout` (408). These admission controls are not a general per-user
rate limiter or a total request-processing deadline. The API validates Host
headers for local use, rejects browser Origin headers; the dashboard uses an allowlisted same-origin server broker, and does not enable CORS. Origin/Host validation does not
replace authentication. The server uses database connection, statement and lock
timeouts. Public exposure, rate limiting, browser sessions, multi-user audit identity,
TLS and full production security validation remain later work.

## Database privileges

`pipeguard_owner` runs migrations. `pipeguard_api` has explicit grants on existing
tables: necessary reads/inserts, run/attempt updates, integration enable flags,
credential revocation and event-processing columns. It has no DELETE, TRUNCATE,
schema-creation or table-ownership privileges. It cannot edit received event payloads,
alter tables, disable history protection, create roles or create databases.

Startup checks reject elevated roles, role memberships, schema ownership/creation
and an unexpected migration revision. Runtime grants must be reviewed and reapplied
after schema changes; future tables do not automatically receive broad privileges.
The database role operates across integrations, with producer isolation enforced by
API authorization; this is not database row-level tenant isolation. Integration IDs
alone never authenticate a caller.

## Historical initial-API checkpoint

This records the initial execution API slice, before the extensions below. Current
checks and limitations are recorded in the [next-session checkpoint](../next-session.md).

74 automated tests passed, including the previous persistence/ingestion checks and
HTTP authentication, scope isolation, credential hashing/revocation, disabled
integrations, validation privacy, body/host/origin boundaries, pagination, startup
role checks, blocked destructive SQL and durable receipt after projection failure.
The current Starlette test client emits an HTTPX deprecation warning; tests pass.

A real Uvicorn server using `pipeguard_api` also passed a loopback HTTP flow:
provision an integration and job, issue a producer token, record start/failure/retry
success, confirm preserved failure history, replay an event, and revoke the token.
The synthetic smoke integration was disabled afterward and its history retained.
This does not establish production security, browser usability or performance.

## Incident and quality extension

The API now includes immutable monitor-policy creation, quality-report receipt, scoped incident/history/evidence reads and administrator acknowledgement. Coverage inspection reports global/per-job detector staleness and unmonitored jobs. Acknowledgement does not resolve or approve recovery. Attempts expose `projection_source`; Airflow backfill can add `blocked`, `skipped` and `waiting` outcomes. See [operations](../incident-operations.md), [quality contract](quality-reports.md) and the checked-in OpenAPI document.

## Lineage and evidence extension

The API includes scoped lineage receipt/history/traversal, administrator lineage-delivery expectations and immutable incident evidence captures. The graph is an observed historical union with event and receipt cutoffs, not an implicit current deployment snapshot. See the [lineage contract](lineage-events.md), [architecture](../architecture/lineage-evidence.md) and checked-in OpenAPI document.

## Captured list reads

Integrations, jobs, runs, attempts, monitor policies, incidents, incident history and quality reports accept optional `snapshot=new` to capture bounded typed responses. Reuse the returned `snapshot.token` with the same filters and another offset to read the same captured values and membership. Every request still authenticates. Tokens bind to principal/integration, route and filters. Response metadata includes `captured_at`, `expires_at` and `total_count`. Legacy requests without snapshots retain live offset behavior. Incidents/history/policies return a Page envelope only in snapshot mode; other list routes already use Page.

Snapshots expire after five minutes or process restart, cap at 5,000 rows/8 MiB each and 128 entries/64 MiB aggregate serialized content, and admit two captures concurrently. They do not retain long-lived database transactions. Expiry/unavailable/scope mismatch returns 410, capacity 413 and busy 503. No fallback silently mixes pages. Quality responses include a summary of report count and rule/version conflicts across all reports matching the filters, even outside the displayed page; captured rows and summary share one short repeatable-read transaction.

## Advisory investigation extension

Administrator-only `POST /v1/incidents/{incident_id}/investigations` requires a UUID `request_key`, literal boolean `free_plan_confirmed: true`, and optional scoped `bundle_id`. Replays return the recorded operation without generating again. Admission can return 429 or 503. Authenticated `GET` history is integration-scoped, limited to 20 records per page, with a scoped UUID `before` cursor and `next_before`. It is a live keyset view. Records expose bounded input/provenance, input-integrity and current-policy flags, terminal outcome or explicit pending/unknown state. Neither endpoint changes incident state or authorizes recovery. See [investigation operations](../investigation-operations.md) for exact limits and [verification](../investigation-verification.md) for checked behavior.

## Recovery review

The administrator-only proposal and approve/reject endpoints record review-only decisions, with integration-scoped keyset history. No execution endpoint exists in this review-only namespace; separate executable
recovery routes are described below. See [recovery operations](../recovery-operations.md) for exact inputs, freshness checks, replay semantics and the non-executable policy boundary; the generated OpenAPI contract includes all three routes.


## Separate executable recovery

Executable proposals use a separate immutable ledger and namespace, not the
review-only approvals above. The fixed incident-scoped prefix is
`/v1/incidents/{incident_id}/recovery-actions`:

| Method and suffix | Access | Behavior |
| --- | --- | --- |
| `GET` prefix | Administrator or scoped producer | Keyset history, at most five proposals, eligibility and worker availability |
| `POST` prefix | Administrator | Propose one allowlisted sample-job action using a UUID `request_key` |
| `POST /{action_id}/decisions` | Administrator | Record approve/reject/cancel with exact proposal hash, UUID request key and literal confirmation |
| `POST /{action_id}/dispatch` | Administrator | Separately start an approved action, bound to its exact hash and explicit confirmation |
| `POST /{action_id}/reconcile` | Administrator | Look up the exact reserved external run and append its observation; never start a replacement |

Incident, action and cursor scope is checked before worker access. Mutations use
fixed operations through a supervised worker; arbitrary commands and destinations
are not accepted. Dispatch rechecks execution capabilities, expiry, source state,
monitoring freshness and unchanged evidence. Its durable intent commits before the
external start request. Approval alone cannot start a run, and a review-only
approval cannot supply executable authority.

An uncertain transport/database response is not proof that no run started. Retain
the exact operation body/key for deliberate replay and inspect its saved history.
An existing intent is never dispatched a second time; exact-run reconciliation
retains uncertain or conflicting observations. These controls do not establish
exactly-once external execution. Source credentials stay outside the browser/API
process in the private worker configuration. See [executable operations](../recovery-execution.md)
and the [recorded live acceptance](../recovery-live-verification.md) for the bounded
sample action, disabled defaults and remaining cross-system limits.
