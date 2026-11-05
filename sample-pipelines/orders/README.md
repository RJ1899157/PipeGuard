# Synthetic orders pipeline

Independent monitored workload: a bounded CSV snapshot is loaded into PostgreSQL,
then transformed and checked by dbt Core. It imports no monitoring application code
and uses its own database, credentials, Python environment and lockfile. A scoped
producer adapter now reports execution observations to PipeGuard; the
[Airflow DAG](../../infra/airflow/README.md) schedules it and supplies native retry identities.

## Layout and outputs

| Surface                   | Responsibility                                                 |
| ------------------------- | -------------------------------------------------------------- |
| `data/orders.csv`         | Deterministic synthetic source; no real customer data          |
| `src/orders_pipeline/`    | Strict source validation, transactional replacement and runner |
| `dbt/models/sources.yml`  | Source definition and source quality assertions                |
| `staging.stg_orders`      | Standardized rows, UTC order date and calculated order total   |
| `analytics.orders`        | Order-level table, including cancelled orders                  |
| `analytics.daily_revenue` | Completed-order counts and revenue grouped by UTC date         |
| `target/<invocation>/`    | Ignored per-run dbt logs, manifest, run results and summary    |

The supplied fixture contains five orders. Expected `daily_revenue` output:

| UTC date   | Completed orders | Revenue |
| ---------- | ---------------: | ------: |
| 2026-10-01 |                2 |  139.98 |
| 2026-10-02 |                2 |   41.00 |

The cancelled order is excluded from revenue. Totals use PostgreSQL numeric values,
not floating-point arithmetic. Revenue is expressed in fixture monetary units;
this sample does not perform currency conversion or multi-currency aggregation.

## Setup and execution

Start the existing local PostgreSQL service. From the repository root:

```sh
uv run --env-file .env python scripts/configure_sample_warehouse.py
uv sync --project sample-pipelines/orders --locked --python 3.12.16
uv run --directory sample-pipelines/orders --locked --env-file .env python run.py
```

Provisioning uses the private root administrator configuration, creates the separate
`sample_warehouse` database and non-superuser `sample_orders` role, then writes only
workload configuration to this directory's private `.env`. The sample process
receives no monitoring administrator/API token from that file. Repeated provisioning
retains the workload password. Do not replace an existing configuration with the
placeholders in `.env.example`.

The sample uses `sample-pipelines/orders/.venv`, separate from the monitoring app's
root `.venv`. Selected versions are dbt Core 1.12.6 and dbt-postgres 1.10.2 on Python
3.12.16; `uv.lock` records the full resolution. Do not install the unrelated default
`dbt` package or switch to dbt v2 without reviewing compatibility.

To use another local, synthetic CSV:

```sh
uv run --directory sample-pipelines/orders --locked --env-file .env python run.py --input /path/to/orders.csv
```

The command prints a safe summary with invocation ID, loaded-row count, dbt outcome
and relative artifact directory. It returns nonzero on invalid input, load/build
failure, contention timeout or a dbt test failure. Logs stay in ignored local
artifacts. Anonymous dbt usage reporting is disabled, and the password uses dbt's
`DBT_ENV_SECRET_` convention. No cloud credentials are required.

## Validation and failure behaviour

The source must be UTF-8 with the exact checked-in CSV headers, at most 5 MiB and
10,000 rows, and at least one order. IDs, customer references, quantities, prices,
aware timestamps and status values are validated before changing any database rows.
Errors contain safe codes/line numbers without echoing source values. Empty snapshots
are rejected to avoid unintentionally erasing the current raw dataset.

Raw replacement uses one transaction: a failed insert restores the prior snapshot.
Repeated successful runs replace rows and rebuild models rather than appending
copies. A database-scoped advisory lock spans raw loading and the dbt subprocess;
a competing run fails safely on the configured lock timeout instead of interleaving. A stable owner-private lock shared across checkouts is inherited by dbt, preserving local exclusion if its parent is SIGKILLed. Host/database identity is normalized; other hosts/accounts and direct writers require separate fencing.

Source row shape validation and business-quality validation are distinct. Repeated
order IDs can be valid CSV rows but fail dbt's uniqueness checks. dbt also checks
nulls, accepted statuses, nonnegative totals and revenue reconciliation. A failing
upstream test prevents dependent models from building. dbt model builds are separate
transactions, so the entire raw/staging/mart workflow is **not** one atomic refresh:
a failed build may leave old marts alongside a newer raw snapshot. Consumers must
inspect run results before treating a refresh as current. Restoring the source and
rerunning repairs this fixture without deleting failure artifacts.

The runner bounds the dbt subprocess to 120 seconds and connection/lock waits.
Artifact cleanup/retention is manual at this stage. Bounded model provenance and data-quality
observations are integrated with PipeGuard through the durable outbox.

## Verification

```sh
uv run --directory sample-pipelines/orders --locked --env-file .env pytest -q
```

The integration suite covers exact fixture values, malformed fields/headers, multiline handling,
raw replacement idempotency, transactional rollback, source rejection before writes,
concurrent-load exclusion, refusal of monitoring database access, complete dbt builds,
duplicate-order fault injection and successful recovery. Full-build checks use unique
temporary schemas and remove only those schemas. The normal raw/staging/analytics
fixture remains available for inspection.

The monitoring account is also denied connection to the sample warehouse. The two
databases share a local PostgreSQL instance; this is an access boundary, not physical
failure isolation. The sample owns its warehouse and therefore has schema-changing
privileges there; PipeGuard's runtime account remains restricted in its own database.

## Monitoring and durable delivery

With the local PipeGuard API running, provision the sample producer from root:

```sh
uv run --env-file .env python scripts/configure_sample_monitoring.py
```

The administrator token stays in root configuration. Only an integration-scoped
producer token and IDs are saved in this sample's private `.env`. Re-running warehouse
provisioning preserves those values. Monitoring provisioning leaves an existing
producer configuration unchanged; revoke/rotate credentials through the API when
needed rather than treating this command as automatic credential recovery.

The runner emits a start and terminal observation for each attempt. To demonstrate
a retry manually, use the same run identity with different attempt numbers:

```sh
uv run --directory sample-pipelines/orders --env-file .env python run.py --run-id example_manual_retry --attempt 1 --simulate-first-attempt-failure
uv run --directory sample-pipelines/orders --env-file .env python run.py --run-id example_manual_retry --attempt 2
```

The first command intentionally returns nonzero. The second performs the real build.
The native Airflow DAG supplies these identities automatically. When monitoring
configuration is absent, standalone execution remains available; partial or invalid
configuration fails explicitly. The monitored DAG requires complete configuration.

Before each delivery, an immutable normalized observation is atomically published
as a private JSON file in ignored `target/events/<integration>/<job>`. Files contain
bounded metadata/error categories and never tokens or arbitrary error text. Event
identity is deterministic for run/attempt/state. Re-emission preserves the existing
observation timestamp, allowing exact HTTP replay without creating a contradiction.
A `.sent` marker means PipeGuard acknowledged durable receipt, not that processing
or the business job succeeded. Inspect PipeGuard's processing/run state for that.

Network failures retain pending files and do not turn a successful business build
into a failed build. The summary reports monitoring `pending`. Replay manually:

```sh
uv run --directory sample-pipelines/orders --env-file .env python run.py --replay-events
```

There is no background delivery worker yet. HTTP delivery is restricted to the local
API, ignores proxy settings, and refuses redirects. Storage errors in the outbox can
fail execution; an available local disk is required. Markers rely on the server's
acknowledged persistence: restoring the server database behind those acknowledgements
requires an operator-directed replay. Local files are not tamper-proof evidence.

Verification includes a controlled transport outage followed by real HTTP replay;
terminal-before-start replay retained the failed outcome. Unit checks cover stable
identity/timestamps, offline retention/replay, private error allowlisting, destination
restrictions and credential filtering before dbt. The native Airflow retry was also
verified end to end through PipeGuard's API.

## Quality observations

A completed dbt build produces a bounded quality report from matching manifest/run-results invocation IDs. The durable outbox includes rule identifiers, content fingerprints, outcomes and completeness; SQL, data rows and error messages stay local. Missing or ambiguous artifacts do not count as passes. Replaying events also replays quality reports. See the [quality contract](../../docs/contracts/quality-reports.md) and [failure matrix](../../docs/failure-coverage.md).

## Lineage observations

The adapter journals a bounded OpenLineage 2.0.2 profile alongside execution and quality events. It derives declared dataset dependencies from matching dbt artifacts and reports loader input/output boundaries separately. Expected step inventories prevent partial delivery from appearing complete. Source paths, SQL, rows, credentials and free-form errors are excluded. Failed early attempts retain explicit metadata gaps. See [contract](../../docs/contracts/lineage-events.md) and [operations](../../docs/lineage-operations.md).

Private logical backup/restore verification is documented in [local resilience](../../docs/local-resilience.md). The workload remains a monitored sample with separate raw/dbt transactions, not an atomic whole-warehouse publication system.


## Terminal fault for recovery acceptance

`--simulate-terminal-failure` deliberately fails before loading source data or invoking dbt on every attempt, recording the bounded synthetic `source_unavailable` category and lineage gap when monitoring is configured. It defaults off. Unlike `--simulate-first-attempt-failure`, the second attempt also fails. A new run without either fault flag follows the ordinary workload path. This option is confined to the independent sample workload; the recovery worker cannot add arbitrary parameters. See the [controlled live scenario](../../docs/recovery-live-scenario.md) before executing it against the monitored DAG.
