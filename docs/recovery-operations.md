# Recovery review operations

Stage 11 is **in progress**. Immutable proposals, human review decisions and scoped APIs are implemented. This milestone is **review only**: no dispatch endpoint or worker exists. The policy `recovery_review_v1` and every returned record explicitly carry `can_execute: false`. A future executable policy must require a new proposal and new explicit approval; existing review approvals must not be reused.

## Configuration and eligibility

The private API environment may bind exactly one monitored job:

```dotenv
PIPEGUARD_RECOVERY_JOB_ID=the_existing_sample_job_uuid
```

The selected job must already have an enabled integration and a monitoring policy bound to the fixed `pipeguard_orders` DAG with a task ID. No browser field, job name or model response can choose a target. This binding is private API configuration; it never enables execution or reaches the browser process. The local binding was resolved unambiguously from the existing sample policy.

Before admitting a proposal or a new approval, the deterministic checks require:

- An open execution-failure incident for the job's latest run, with a failed, settled highest attempt and no unsettled job executions.
- Fresh detector and per-job heartbeats, each younger than 90 seconds without future clock skew.
- A complete independent Airflow scan younger than 90 seconds, an explicitly unpaused DAG and an independent failed DAG-run observation matching the selected execution.
- No unprocessed producer receipts; no conflicting run/attempt projections; bounded evidence and history, with no integrity error or truncated snapshot.
- The exact configured target and unchanged semantic evidence fingerprint at approval time.

The current sample DAG remains paused. Historical recovered incidents and metadata-coverage incidents cannot be proposed for rerun. Missing/unknown state blocks review; the application does not unpause schedules, inspect raw logs or change incident state.

## Proposal and decision records

Migration `f102b8e6d391` adds `recovery_proposals` and `recovery_decisions`. Both reject UPDATE, DELETE and TRUNCATE using immutable-history triggers. The runtime role receives SELECT/INSERT only. Database owners can still alter protections; this is not tamper-proof storage.

A proposal stores its incident and immutable evidence-bundle references, exact action parameters, evidence fingerprint, actor, SHA-256 and five-minute expiry. Its deterministic prospective Airflow run ID derives from the proposal UUID. This describes a **new** sample run; it never clears an earlier attempt. Parameters contain no command, SQL, external endpoint or model-generated text. The bounded JSON payload is limited to 16 KiB in PostgreSQL.

Each proposal accepts at most one terminal human decision, approve or reject. Decisions store their own replay key, exact proposal hash, authenticated local-administrator actor and database timestamp. Approval requires literal boolean confirmation, valid hashes, current policy, unexpired evidence and revalidated eligibility. Expiry is checked again after evidence validation, immediately before inserting the decision. Rejection can close an expired or stale proposal without approving it.

Proposal and decision transactions use a shared transaction-scoped advisory lock. Parallel mutations fail with a fixed busy response; database uniqueness constraints also guard replay keys and one decision per proposal. A process stop before commit rolls back the whole review mutation. A lost response after commit is resolved with the same request key; replay returns the recorded operation even after expiry, without renewing it.

## Freshness and concurrency boundary

Each eligibility read uses a repeatable database snapshot. Proposal creation compares semantic evidence before and after capturing its immutable bundle. The fingerprint includes incident history, run/attempt projections, producer receipts and processing state, non-scan observations, lineage references and target/policy configuration. Routine fresh, unchanged complete scans and heartbeat timestamps do not invalidate an otherwise identical proposal; their freshness is checked separately. Changed evidence or a new execution does invalidate approval.

These are point-in-time **review** checks. They do not fence all ingestion writers or make an external action atomic with PostgreSQL. Data can change after a review transaction. The future dispatcher must revalidate immediately before dispatch and reconcile uncertain external outcomes under the [recovery design](recovery-design.md). There is no action queue or background execution in this milestone.

## API contract

All routes require a bearer credential. History is restricted to the incident's integration or administrator; mutations require the administrator.

| Method | Route | Input |
| --- | --- | --- |
| GET | `/v1/incidents/{incident_id}/recovery-proposals` | `limit` 1–20; optional incident-scoped `before` UUID |
| POST | `/v1/incidents/{incident_id}/recovery-proposals` | `request_key` UUID only |
| POST | `/v1/incidents/{incident_id}/recovery-proposals/{proposal_id}/decisions` | `request_key`, exact `proposal_hash`, `decision` (`approve` or `reject`), literal `confirmed: true` |

History is a descending keyset view; it returns current eligibility and retained decisions, not a frozen multi-page snapshot. `expired` is separate from the recorded decision: an expired review approval remains visible as historical approval and still cannot execute. Fixed validation/admission rejections return HTTP errors without creating proposal or decision rows; they are not a separate security-event audit stream.

The local dashboard broker accepts only these fixed review operations, strict same-origin mutations and bounded JSON. Unknown network/database outcomes retain the exact submission body and key in browser session storage, with in-memory retention if storage is unavailable. Known pre-commit rejections allow a fresh deliberately initiated request. Neither path automatically retries or generates another key.

## Verification and remaining work

The backend suite passes 339 checks, including 27 recovery checks and disposable-schema migration roundtrip/metadata checks. They cover scoped access, literal confirmation, hash mismatch, expiry at both checks, stale/changed evidence, paused or unknown source state, pending receipts, replay, cross-incident keys/cursors, immutable tables, lock contention and simulated interruption before proposal/decision commit. These simulations do not reproduce every operating-system termination or power-loss scenario.

Pre-migration and post-migration PipeGuard backups were created and restore-verified in disposable databases. No live database was replaced. Browser verification is recorded separately in the recovery checkpoint.

Remaining Stage 11 work: verify the installed Airflow mutation API and minimum privileges; implement a separately approved execution policy, durable dispatch intent and independent reconciliation; test lost replies, duplicate dispatch and interruption boundaries; then run a deliberately approved synthetic incident-to-recovery scenario. No operational recovery safety claim is made before that work is complete.

References: [PostgreSQL isolation](https://www.postgresql.org/docs/17/transaction-iso.html), [PostgreSQL locks](https://www.postgresql.org/docs/17/explicit-locking.html#ADVISORY-LOCKS), [SQLAlchemy transaction management](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html).
