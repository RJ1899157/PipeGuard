# Lineage and incident evidence operations

## Upgrade and enable delivery expectations

Use the existing local environments and running PostgreSQL. No additional service is required.

```sh
uv run --env-file .env alembic upgrade head
uv run --env-file .env python scripts/configure_api.py
uv run --env-file .env python scripts/run_api.py
```

Restart the monitor using its restricted configuration:

```sh
uv run --env-file .env.monitoring python scripts/run_monitor.py
```

Explicitly enroll a workload that emits complete lineage:

```sh
uv run --env-file .env python scripts/enroll_lineage.py --job-id JOB_UUID --grace-seconds 300
```

Repeat enrollment safely verifies the same immutable expectation. A different existing expectation requires review. Do not enroll a job without an actual lineage producer and then fabricate metadata to suppress missing-data incidents. The orders job is enrolled; the synthetic event-only check has no dataset transformations to report.

## Workload and history

The sample automatically journals execution, quality and lineage observations before delivery. Matching dbt manifest/results produce model dependencies and artifact fingerprints. Loader relationships use a logical CSV identity and never disclose the user's input path. Early failure produces an explicit partial-lineage report rather than invented edges.

Replay after an API outage:

```sh
uv run --directory sample-pipelines/orders --env-file .env python run.py --replay-events
```

Outbox acknowledgement means durable receipt. A successful execution does not prove complete lineage. Query one external run and attempt to inspect the graph, or use `as_of`/`known_at` for historical evidence. The unfiltered graph preserves old and partial assertions and may deliberately remain partial even after a newer retry has complete metadata.

Old executions that predate lineage delivery or step-inventory instrumentation retain missing metadata. Do not rewrite them to make historical coverage appear complete. New expectations apply to newly observed run records and do not retroactively claim old evidence existed.

## Incident evidence

Create a snapshot through `POST /v1/incidents/{id}/evidence-bundles` with the appropriate scoped bearer token. Keep the returned ID and payload hash when investigating. Later captures can contain different evidence; the old bundle remains immutable. Missing evidence, integrity problems, out-of-scope references and limits are part of the response.

Snapshots are supporting evidence, not AI verdicts or recovery approvals. This stage introduces neither an AI provider nor autonomous recovery.

## Verification

Run the PostgreSQL and independent sample suites listed in [incident operations](incident-operations.md). See [Stage 7 verification](lineage-verification.md) for the scenario coverage and live demonstration.
