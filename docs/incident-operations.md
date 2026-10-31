# Incident monitoring operations

## Local startup

Apply the migration and refresh explicit runtime grants before restarting the API:

```sh
uv run --env-file .env alembic upgrade head
uv run --env-file .env python scripts/configure_api.py
uv run --env-file .env python scripts/run_api.py
```

Prepare the dedicated Airflow viewer account and restart the Airflow launcher so the new role configuration takes effect:

```sh
uv run --env-file .env python scripts/configure_airflow.py
uv run --env-file .env.airflow python scripts/run_airflow.py start
```

With the API available, provision the example's policy and private worker configuration:

```sh
uv run --env-file .env python scripts/configure_monitoring.py
uv run --env-file .env.monitoring python scripts/run_monitor.py
```

Use `--once` for a single cycle. The long-running worker retries failed cycles without printing sensitive exception details. Stop with Ctrl+C. Its configuration contains only the restricted monitoring database connection and dedicated Airflow viewer credential. Do not commit `.env.monitoring`, `.env.airflow`, workload `.env`, local artifacts or password files.

## Inspection

All routes require bearer authentication; producer tokens are restricted to their integration. Use the protected OpenAPI document for request/response details.

| Route | Purpose |
| --- | --- |
| `POST /v1/monitor-policies` | Administrator enrolls a job and declares expectations |
| `GET /v1/monitor-policies` | Scoped policy inspection, limit/offset |
| `POST /v1/quality-reports` | Durable, replay-safe quality receipt |
| `GET /v1/incidents` | Scoped incident list, optional state, limit/offset |
| `GET /v1/incidents/{id}` | Current deterministic condition |
| `GET /v1/incidents/{id}/history` | Append-only observations, lifecycle and acknowledgement, limit/offset |
| `POST /v1/incidents/{id}/acknowledge` | Administrator acknowledgement; does not change state |
| `GET /v1/observations/{id}` | Scoped source/quality evidence |
| `GET /v1/monitoring/coverage` | Administrator sees worker staleness and jobs without policies |

A 202 quality response means durable receipt; evaluation is asynchronous. Workload outbox `.sent` markers acknowledge server receipt only. Replay both execution and quality observations with the sample's `--replay-events` option after API connectivity returns. An execution marked successful may still have open quality, coverage or conflicting-evidence incidents.

Historical example runs predate quality reporting and may correctly produce missing-quality incidents. Do not invent reports or delete those incidents to make the demonstration green. A paused DAG deliberately has no schedule expectation in the provisioned policy. Enable an explicit expected-activity policy when adopting a real schedule; the current immutable-policy API does not yet support replacement.

## Verification

```sh
uv run --env-file .env pytest -q
uv run --env-file .env alembic check
uv run --directory sample-pipelines/orders --env-file .env pytest -q
```

See [detection architecture](architecture/incident-detection.md) for authority and limitations. The final security/performance stage remains required.

## Enroll an event-only job

For a producer with no orchestrator or quality reports, explicitly enroll its execution-event coverage:

```sh
uv run --env-file .env python scripts/enroll_monitor.py --job-id JOB_UUID --timeout-seconds 300
```

Use `--quality-required`, paired `--airflow-dag-id` / `--airflow-task-id`, and `--expected-interval-seconds` only when those expectations exist. Enrollment does not invent an independent source or infer an unscheduled job should run periodically. Coverage reports the monitoring mode and configured expectations. Repeating an identical enrollment is safe; a conflicting immutable policy requires review.
