# Execution event contract v1

Status: implemented as an internal service, local command and authenticated
[HTTP API](http-api.md). Airflow/dbt adapters are not implemented.
Use only locally controlled synthetic metadata at this checkpoint.

[JSON Schema](execution-event-v1.schema.json) · [Domain model](../architecture/domain-model.md)

## Scope and validation

One observation describes the start or terminal outcome of one **job-level attempt**.
`running` means the attempt's start observation, not a periodic heartbeat. Task-level
executions must use their own job/run identities; this contract does not aggregate
multiple task states into one DAG result. Internal attempt keys are fixed to `job`.
Existing runs with other attempt keys fail normalization as `unsupported_attempt_scope`.

| Field | Rule |
| --- | --- |
| `schema_version` | Integer `1`; defaults to 1 if omitted |
| `event_id` | Producer delivery identifier, unique within an integration |
| `integration_id` | UUID of an enabled, pre-provisioned integration |
| `job_id` | UUID of a pre-provisioned job belonging to that integration |
| `external_run_id` | Execution identity scoped to that job |
| `attempt_number` | Integer from 1 through 2147483647; increases for retries |
| `state` | `running`, `succeeded`, `failed`, or `cancelled` |
| `occurred_at` | Timezone-aware timestamp; normalized to UTC |
| `error_code` | Optional, only for failures: `connection_timeout`, `source_unavailable`, `validation_failed`, `execution_error`, or `unknown` |

String event/run identifiers are 1–255 characters using the pattern in the schema.
Additional fields are rejected. Arbitrary logs, free-form error messages and payloads
are excluded. Producers must supply non-sensitive identifiers. This allowlist is not
a general secret detector; it does not make unsafe identifiers safe. Future adapters
must map source errors to this bounded vocabulary and implement separately reviewed
redaction before accepting richer evidence. No payload or validation input is logged.

A reported error category is not a verified root cause. Missing failure information
is represented as `unknown`; original observations retain the distinction between a
missing error code and an explicitly supplied one.

## Receipt and replay

`receive(bind, data)` validates the complete envelope and integration/job association,
then commits an immutable observation before any projection work. Its returned UUID
identifies the stored observation; `replayed` reports exact duplicate delivery.

Canonicalization `execution-json-v1` serializes the validated, default-filled envelope
with UTC timestamps, sorted keys, compact separators and ASCII escaping. SHA-256 is
computed from those UTF-8 bytes. This is a normalized representation, not an archive
of input bytes. Equal representations with the same producer event ID return the
existing UUID. Conflicting content under that ID raises `event_id_content_conflict`
and leaves the original record and projection unchanged. Rejected conflicting
requests are not stored as accepted source events.

## Processing and reconciliation

`process(bind, event_id)` locks the stored observation and logical run, then commits
attempt changes, run projection and processing status together. Concurrent inserts
use PostgreSQL conflict handling; concurrent projection updates serialize per run.
The functions own transactions and require a dedicated connection or engine without
an enclosing caller transaction for the durable receipt guarantee.

- A delayed start cannot regress a terminal attempt to running.
- Run state follows the highest numbered attempt, not delivery order.
- Older failures remain queryable after a later attempt succeeds.
- Different terminal states, different start/finish timestamps for the same attempt,
  contradictory failure categories, or a start after a finish set a sticky
  `reconciliation_required` flag. The affected attempt state becomes `unknown`.
- A run exposes uncertainty from any attempt, even if a newer attempt succeeds.
  Its current outcome and its historical uncertainty are separate fields.
- Earliest observed start/finish timestamps are retained on an uncertain attempt;
  differing reported error categories produce the display category `unknown`.
  Neither value resolves the contradiction. Source
  observations remain authoritative evidence for a future reconciliation workflow.
- Run start is the earliest known attempt start. Run finish is set only when its
  highest attempt has an unambiguous terminal state.
- `processed` means the observation was applied, not that the job succeeded or all
  evidence agrees. A conflicting observation records `reconciliation_required` in
  processing metadata. There is no automatic mechanism to clear uncertainty yet.

Known processing failures store safe fixed codes and remain manually retryable.
Unexpected/database failures roll back projection changes, leaving the committed
receipt pending for retry. Disabled integrations prevent new receipts and can defer
processing; re-enabling allows processing to resume. No background retry worker exists.
The HTTP layer authenticates and scopes callers before invoking this internal service;
knowing an integration UUID is not authentication.

## Local command

With the schema migrated, use an event file containing synthetic metadata and the
UUIDs of an existing integration and job:

```sh
uv run --env-file .env python scripts/ingest_event.py --file /path/to/event.json
```

The command accepts at most 64 KiB, prints the durable receipt UUID first, then the
processing outcome. Add `--receive-only` to persist without processing. To resume:

```sh
uv run --env-file .env python scripts/ingest_event.py --process-event STORED_EVENT_UUID
```

A rejection or processing failure returns a nonzero exit code. `processed` with a
reconciliation warning returns success because the observation was retained/applied;
clients must inspect the warning and current run flags. Use the administrator HTTP endpoints to provision integrations/jobs first; this
command does not invent trusted producers.

## Verification

The PostgreSQL suite checks exact replay, changed-content rejection, UTC normalization,
all six permutations of start/failure/retry-success delivery, preserved failures,
contradictory terminal observations and start timestamps, concurrent delivery,
validation without writes, producer boundaries, disabled integration retry, and
receipt durability after an injected projection failure. CLI checks cover separate
receipt/processing and non-disclosure of invalid input. Schema migrations and
SQLAlchemy metadata comparison remain part of the suite.
