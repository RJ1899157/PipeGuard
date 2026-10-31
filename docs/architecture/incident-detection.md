# Deterministic incident detection

## Scope and authority

The detector evaluates execution evidence, independent Airflow task history, quality reports and monitoring coverage. It does not run recovery actions or use AI to change state. An execution retry can succeed while its earlier failure remains available in incident history. Quality and monitoring incidents have independent recovery requirements.

A monitor policy explicitly enrolls a job. A job without a policy is listed as unmonitored by the coverage endpoint. Policies are immutable in this initial version; changing thresholds or source identity requires a future versioned policy replacement operation rather than an undocumented edit. An optional expected-activity interval detects a job that never starts; it is not a cron/calendar interpreter. The paused example has no expected-activity interval.

## Evidence and transactions

- Producer receipts, allowlisted Airflow snapshots, quality reports and incident history retain stable identifiers and provenance. Observation `occurred_at` and database `created_at` distinguish source time from receipt time.
- PostgreSQL triggers prevent updates, deletion and truncation of observation, policy and incident history rows, including ordinary operations by the owner. A database administrator can still bypass protections; these tables are not a cryptographic audit ledger.
- A per-job transaction advisory lock serializes quality delivery and incident evaluation without granting the runtime role permission to modify job identity.
- Incident identity is `(job, condition, subject)`. Repeated evaluation and delivery do not inflate occurrence history. Reopening uses the same incident with new history; late historical failures are recorded even when the incident can immediately resolve from a later successful retry.
- Acknowledgement records `local_admin_token`, because possession of the local administrator token is not proof of a named person's identity. It neither resolves incidents nor approves recovery.
- Event-key content collisions produce a durable conflict observation before returning HTTP 409. Rejected arbitrary/malformed or unauthenticated HTTP bodies are not stored as incident evidence.

## Recovery rules

Execution failure resolves only from an unambiguous successful highest-numbered attempt. Earlier failures and source conflicts remain evidence. Contradictory terminal states and producer projection inconsistencies require investigation and remain open. A missing terminal event resolves from explicit terminal evidence, including failure; an execution failure incident remains independently open.

Quality reports contain rule identifiers, content fingerprints, outcomes and optional bounded failure counts. SQL, row data and exception messages are excluded. Warning/fail, error, skipped and unknown outcomes are not passes. A newer passing attempt can recover the same rule version; changing the version does not clear the previous failure. Conflicting outcomes for the same rule/version/attempt create an uncertainty incident. A complete report must account for the enabled test inventory in the dbt manifest; missing artifacts or incomplete results remain incomplete. Execution success never proves data quality.

The first adapter supports the example's full `dbt build`, not arbitrary selected dbt invocations. A producer's complete-inventory declaration is evidence from that producer, not an independently attested guarantee that all intended business rules exist.

## Independent source reconciliation

The observer uses an Airflow **viewer** account and public API only. It has no Airflow database or warehouse credentials. All configured DAG runs and task try histories are enumerated, including executions that emitted no workload events. Missing execution boundaries are backfilled into run/attempt projections with `projection_source=airflow`; late producer terminal events restore producer boundaries without comparing scheduler and workload timestamps. Conflicting outcomes require reconciliation. Native task states are normalized; skipped is retained without automatically treating legitimate branching as failure. Waiting/queued/running tasks are subject to the explicit timeout policy. Unknown states remain visible.

Health checks include Airflow metadata, scheduler and DAG processor. Missing task history, missing timestamps, unsupported task mapping, invalid responses, authentication failure, response-size limits, unstable/incomplete pagination, disappeared known runs and the 10,000-run scan cap mark source coverage incomplete. Partial valid observations remain evidence, but partial scans do not count as complete coverage. Historical snapshots never replace producer timestamps or source content.

## Operating limits

The poller sleeps 15 seconds between cycles. This is eventual detection, not instantaneous capture. Successful job evaluations write individual heartbeats; a completed cycle writes a global database heartbeat. One failed job does not prevent unrelated job evaluation. The API computes heartbeat staleness after 90 seconds even if the poller is stopped; each configured Airflow source separately becomes stale after 90 seconds without a complete scan. Database errors prevent advancing the completion heartbeat. Receipt recovery processes at most 100 pending receipts per cycle; permanently failed receipts remain inspectable and create a backlog condition.

Host power loss, complete database/API outage and a monitoring process that cannot run cannot notify through that same unavailable host. An independently hosted watchdog and durable off-host backup/alert delivery are required for those guarantees. Source history purged before the first observation, events never emitted before a process dies, malicious false success reports and unconfigured dependencies cannot be reconstructed with certainty. Coverage gaps must be reported rather than represented as confirmed healthy.

Current evaluation reads retained evidence for each watched job. This is suitable for the local example; bounded incremental processing, archival and measured load targets remain part of the performance stage. No production-scale or exhaustive-failure guarantee is made.

Additional coverage rules flag missing attempt numbers, quality reports without execution evidence, changed complete check inventories, DAG-level failure and disabled monitoring. See the [failure matrix](../failure-coverage.md).
