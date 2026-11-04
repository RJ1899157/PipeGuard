# PipeGuard domain model

Status: execution ingestion, deterministic incidents, quality observations, lineage and immutable evidence are implemented on PostgreSQL 17. The conceptual table below includes some future entities; the implementation sections identify the current schema, including durable investigation and separate review-only/executable recovery records.

[Architecture overview](overview.md) · [Documentation index](../README.md) · [Delivery roadmap](../roadmap.md)

## Contents

- [Purpose and boundaries](#purpose-and-boundaries)
- [Running example](#running-example)
- [Core entities](#core-entities)
- [Investigation and recovery extension](#investigation-and-recovery-extension)
- [Database rules and reasons](#database-rules-and-reasons)
- [Alternatives considered](#alternatives-considered)
- [Planned database checkpoint](#planned-database-checkpoint)
- [Official references](#official-references)

## Purpose and boundaries

PipeGuard stores monitoring metadata, evidence, and incident workflows. Business rows remain in the sample pipeline warehouse. Start with three independent databases when containers are needed: `pipeguard` for this application, `airflow` for the orchestrator, and `sample_warehouse` for monitored data. They may share a local PostgreSQL server but must have separate database roles and credentials. This is a local development boundary, not physical failure isolation.

PipeGuard ingests documented API responses, producer events, and transformation artifacts. It does not query Airflow internal tables or depend on their schema. A durable ingestion endpoint can accept events even while the investigator is unavailable.

## Running example

An orders pipeline loads a local file into `raw.orders`, transforms it into `analytics.orders`, and computes `analytics.daily_revenue`. A duplicate `order_id` fails a quality rule. PipeGuard records the failed check, opens one incident, gathers the relevant execution and lineage evidence, and asks the investigator for hypotheses. An operator may subsequently approve a bounded rerun. The pipeline owns the order records; PipeGuard owns the observations and incident history.

## Core entities

IDs are application-generated UUIDs unless an external identifier is explicitly named. Internal IDs remain stable even if an upstream display name changes. External identifiers are scoped to an integration/environment, not globally assumed unique.

| Entity                  | Meaning and principal fields                                                                                                                      | Identity and relationships                                                                                            |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Integration             | One configured producer or adapter in an environment: name, kind, environment, secret reference, enabled                                          | Unique integration name per environment; credentials stay outside metadata payloads                                   |
| Dataset                 | A logical data asset: namespace, name, kind                                                                                                       | Unique `(namespace, name)`; examples include a file and a warehouse table                                             |
| Job                     | A reusable computation: integration, namespace, name, kind                                                                                        | Unique `(integration_id, namespace, name)`; a DAG, task, or dbt model can each be a job                               |
| Run                     | One execution of a job: external run ID, optional parent run, state projection, data interval, started/finished times                             | Unique `(job_id, external_run_id)`; producer scope is inherited through the job; parent references another run        |
| Attempt                 | One execution attempt within a run: external task-instance key, attempt number, state, times, redacted reported error code/message                | Unique `(run_id, attempt_key, attempt_number)`; retries add attempts                                                  |
| Ingested event          | A received observation: integration, deduplication key, schema version, occurred/received times, redacted payload, payload hash, processing state | Unique `(integration_id, deduplication_key)`; append-only source record; normalization may link it to a run/attempt   |
| Dataset schema snapshot | A recorded schema at an observation time: dataset, schema hash, canonical column description, source event                                        | Referenced by event/evidence; identical schemas can be deduplicated by dataset and hash                               |
| Run dataset observation | A run consumed or produced a dataset: run, dataset, input/output direction, source event, optional schema snapshot                                | Carries provenance; preserves historic relationships rather than overwriting a current graph                          |
| Quality rule version    | A versioned rule definition: dataset, rule key, version, type, configuration                                                                      | Unique `(dataset_id, rule_key, version)`; results keep their original rule version                                    |
| Quality result          | One evaluation: rule version, evaluation key, optional run, evaluated time, pass/fail/error/unknown, metrics, source event                        | Unique `(rule_version_id, evaluation_key)`; a check execution error is distinct from a failed data assertion          |
| Incident                | An operational issue: dataset/job/run scope, policy version, fingerprint, severity, open/resolved state, acknowledgement fields, timestamps       | One active incident per fingerprint; recurrence reopens the same deterministic condition incident and appends history |
| Incident occurrence     | A repeated triggering observation: incident, trigger event or quality result, evaluation key, observed time                                       | Unique detector evaluation key per incident; repeated delivery does not inflate occurrence counts                     |
| Incident transition     | An auditable incident change: incident, previous/new state, actor type/ID, reason, source evaluation, time                                        | Append-only; deterministic recovery observations or recorded human decisions may change state                         |
| Evidence artifact       | A captured observation: kind, capture time, source locator/event, redacted content or artifact locator, content hash, redaction version           | Immutable snapshot; hash demonstrates consistency, not source truth or tamper-proof storage                           |
| Incident evidence link  | An incident uses an evidence artifact                                                                                                             | Unique `(incident_id, evidence_id)`; one artifact may support several incidents                                       |

The initial schema implemented integrations, datasets, jobs, runs, attempts and ingested events. Subsequent migrations add quality observations, deterministic incidents, lineage and immutable evidence bundles as described below. Investigation and bounded human-authorized recovery are implemented through separate immutable audit records.

## Investigation and recovery extension

An investigation stores incident ID, input evidence IDs/hashes, model/provider version, prompt version, start/finish times, status, and output. Each hypothesis stores a claim, rank, limitations, and explicit support/contradiction links to evidence. Evidence identifiers must belong to the supplied investigation bundle. Citation presence alone does not prove that evidence supports a claim; evaluate that separately.

A recovery proposal stores a typed allowlisted action, target, parameters, expected impact, evidence revision, and expiry. Approval records an authenticated human actor, exact proposal revision, decision, and time. An execution refers to that approval and stores an idempotency key, status, and outcome. Reject an expired or changed proposal, missing authorization, and duplicate execution. Approval does not authorize arbitrary shell commands. AI output cannot create an approval or directly invoke execution.

The implemented investigation ledger uses `investigation_requests` and `investigation_outcomes`, linked to immutable evidence bundles. Review-only records use `recovery_proposals` and `recovery_decisions`; they cannot authorize execution. Executable records use separate `recovery_actions`, `recovery_action_decisions`, `recovery_dispatches` and `recovery_dispatch_events`. A dispatch intent is committed before its external request. Approval binds the exact hash, and replay/reconciliation retain the original intent and observations. See the [execution contract](../recovery-execution.md) and [live acceptance](../recovery-live-verification.md).

## Database rules and reasons

1. Use foreign keys for actual relationships, `NOT NULL` for required values, and unique constraints for external identities and delivery keys. Application validation improves errors; database constraints protect against concurrent writers too.
2. Store instants as `timestamptz`, accepting timezone-aware inputs and returning ISO 8601 offsets. PostgreSQL retains an instant, not the original timezone label; store a scheduling timezone separately if needed. Preserve source `occurred_at` and collector `received_at`. Flag clock anomalies instead of treating receipt order as event order.
3. Use typed columns for identity, state, severity, foreign keys, timestamps, and common filters. Use JSONB for versioned adapter-specific facets and metrics. Validate JSON structure at the ingestion boundary. JSONB does not preserve the original byte representation: hash the explicitly canonicalized/redacted representation and retain hash/version metadata. Do not call JSONB a raw-byte archive.
4. Keep event history append-only, with mutable processing metadata kept separately or clearly distinguished. Build current run/incident views as projections from accepted observations. This is an event history plus relational projections, not a commitment to a full event-sourcing framework.
5. A duplicate transport event has no repeated business effect. Prefer a producer event ID; where none exists, define an adapter-specific canonical envelope and deterministic hash. Do not use the run ID alone because a run produces many events. Distinct producer IDs from different adapters require normalization rules before cross-producer deduplication is safe.
6. Terminal events received before start events are valid deliveries. Keep both. Update projections using source semantics and available sequence/attempt identity; do not regress a terminal attempt to running because a delayed start arrives. Contradictory terminal observations require explicit reconciliation and visible uncertainty.
7. Incident fingerprint inputs include environment/integration scope, stable entity identity, policy version, and relevant condition. A unique deterministic fingerprint and serialized job evaluation prevent duplicate condition incidents; recurrence appends reopen history. Resolve only through a defined policy or audited human transition. AI hypotheses never resolve an incident.
8. Ingestion and normalization may occur in separate transactions. Atomically persist receipt and durable processing state first; then normalize domain records and mark the event processed in one transaction. Failures remain retryable. If external side effects are later needed, add an outbox; a DB transaction alone cannot make an HTTP call atomic.
9. Preserve incident/evidence history when integrations are disabled. Prefer restricted deletion for referenced metadata. Retention and redaction policies need explicit design before real sensitive data is accepted.
10. Start with indexes for known access paths: runs by `(job_id, started_at)`, event processing status/time, attempts by run, occurrences by incident/time, lineage observations by dataset and run, and active incident filters. PostgreSQL does not automatically index all referencing foreign-key columns. Add indexes based on actual queries and measurements; every index also costs writes and storage.

## Alternatives considered

| Choice                                           | Why it fits PipeGuard                                                                               | Alternative and tradeoff                                                                                                               |
| ------------------------------------------------ | --------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| PostgreSQL                                       | Relationships, constraints, transactions, and JSONB fit operational metadata and approval workflows | SQLite simplifies local setup but does not exercise the selected PostgreSQL behavior or concurrent service access                      |
| Relational lineage observations                  | Enough to traverse the initial dataset/job graph while retaining source events                      | A graph database may help complex traversals later but adds a service and duplicated operational data                                  |
| Events plus state projections                    | Efficient dashboard reads while retaining history for debugging and replay                          | Current-state-only tables lose prior failures; full event sourcing introduces more replay/versioning work than the initial scope needs |
| Typed columns plus JSONB                         | Stable query paths with room for adapter-specific metadata                                          | All-JSON documents weaken visible relationships and constraints; fully normalizing every external facet creates excessive schema churn |
| UUID internal identity plus external unique keys | Keeps application relationships independent of producer identifiers                                 | External IDs as primary keys tightly couple the app to one producer's naming and lifecycle                                             |

## Planned database checkpoint

Database implementation requires PostgreSQL, SQLAlchemy 2, Alembic, and a PostgreSQL driver, with Python dependencies resolved in `.venv` and recorded in the lockfile. Docker Desktop is started when database services are needed.

Verify against PostgreSQL 17: migration into an empty DB; duplicate external-ID rejection; unknown-parent rejection; rollback without partial state; duplicate-event replay; terminal-before-start delivery; retry preservation; and independently scoped producer IDs. Validate migrations on a disposable database. Choose and document forward-only versus reversible migration policy before writing destructive operations. Later checkpoints cover concurrent incident creation and approval replay protection.

## Official references

- PostgreSQL constraints: https://www.postgresql.org/docs/17/ddl-constraints.html
- PostgreSQL JSON types: https://www.postgresql.org/docs/17/datatype-json.html
- PostgreSQL date/time types: https://www.postgresql.org/docs/17/datatype-datetime.html
- OpenLineage dataset, job, and run object model: https://openlineage.io/docs/spec/object-model/

## Initial schema implementation

Revision `825e5c183adc` implements integrations, datasets, jobs, runs, attempts,
and ingested events. Run identities are scoped to jobs because different jobs
can share an upstream run identifier. A dataset namespace must identify its
source/environment to avoid accidental cross-environment merging.

PostgreSQL constraints enforce external identities, foreign keys, valid states,
positive attempt/schema numbers, JSON object payloads, and SHA-256 hex format.
Event triggers reject updates to source fields, row deletion, and truncation;
processing state/error/time may change. Owners and administrators can alter or
drop these protections: this is not tamper-proof storage. The version 1 ingestion boundary computes normalized payload hashes, requires aware timestamps,
and accepts only bounded execution fields. Rich-text redaction and parent-cycle validation
remain prerequisites for future contracts that accept those fields. The HTTP boundary authenticates callers, bounds requests and scopes producer access.

The internal [execution ingestion service](../contracts/execution-events.md) preserves
retry history, rejects conflicting event-ID reuse, handles identical replays and
projects observations independently of delivery order. Runs and attempts include
`reconciliation_required` flags for contradictory observations; successful later
attempts do not erase historical uncertainty. The HTTP API now exposes authenticated ingestion with integration-scoped producer access.

The first migration is reversible only for disposable data with an explicit
`allow_data_loss` override. Normal development uses forward migrations; production
rollback and retention policies require separate review. Tests create unique
schemas, migrate them, verify rollback/re-upgrade, and remove only those schemas.

Producer credentials store token hashes and revocation state, scoped to integrations.
The [local HTTP API](../contracts/http-api.md) now wraps execution ingestion and reads.

The PipeGuard and sample warehouse databases are now provisioned with separate roles.
Airflow now has its own metadata database and role, separate from monitoring and the warehouse. The non-superuser owner account is for migrations and checks. The API uses a
separate restricted runtime role without schema ownership.

## Incident and monitoring additions

`monitor_policies` declare immutable per-job expectations. `observations` retain allowlisted quality, orchestration and coverage evidence. `incidents` hold deterministic current condition state; `incident_history` retains occurrence/lifecycle/acknowledgement provenance. `monitor_heartbeats` record successful global and per-job evaluations. Attempt projections identify whether workload or Airflow supplied the boundary through `projection_source`. See [detection architecture](incident-detection.md).

## Lineage and evidence additions

`lineage_runs` binds logical step UUIDs to monitored execution attempts. `lineage_events` retains canonical source claims; `dataset_mentions` indexes their input/output assertions. `lineage_expectations` declares required delivery for newly observed runs. `evidence_bundles` retains immutable scoped incident snapshots. Dataset identities and these records are append-only. See [lineage and evidence architecture](lineage-evidence.md) for the distinction between declared dependencies, reported outcomes and verified business truth.

## Advisory investigation audit

`investigation_requests` stores an immutable bundle reference, idempotency key, bounded exact outbound projection, citation map, input hash and provider/prompt metadata. Current records also preserve the system prompt, response schema and inference settings without credential headers. `investigation_outcomes` appends one terminal result or failure per request. Missing terminal writes remain pending/unknown and are never automatically replayed. These records cannot change deterministic incident state or authorize recovery. See [operations](../investigation-operations.md).
