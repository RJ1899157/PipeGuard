# Synthetic orders pipeline

Independent monitored workload: a bounded CSV snapshot is loaded into PostgreSQL,
then transformed and checked by dbt Core. It imports no monitoring application code
and uses its own database, credentials, Python environment and lockfile. It does not
yet publish execution events to PipeGuard; orchestration/adapters follow in Stage 5.

## Layout and outputs

| Surface | Responsibility |
| --- | --- |
| `data/orders.csv` | Deterministic synthetic source; no real customer data |
| `src/orders_pipeline/` | Strict source validation, transactional replacement and runner |
| `dbt/models/sources.yml` | Source definition and source quality assertions |
| `staging.stg_orders` | Standardized rows, UTC order date and calculated order total |
| `analytics.orders` | Order-level table, including cancelled orders |
| `analytics.daily_revenue` | Completed-order counts and revenue grouped by UTC date |
| `target/<invocation>/` | Ignored per-run dbt logs, manifest, run results and summary |

The supplied fixture contains five orders. Expected `daily_revenue` output:

| UTC date | Completed orders | Revenue |
| --- | ---: | ---: |
| 2026-10-01 | 2 | 139.98 |
| 2026-10-02 | 2 | 41.00 |

The cancelled order is excluded from revenue. Totals use PostgreSQL numeric values,
not floating-point arithmetic. Revenue is expressed in fixture monetary units;
this sample does not perform currency conversion or multi-currency aggregation.

## Setup and execution

Start the existing local PostgreSQL service. From the repository root:

```sh
uv run --env-file .env python scripts/configure_sample_warehouse.py
uv sync --project sample-pipelines/orders --locked --python 3.12
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
3.12; `uv.lock` records the full resolution. Do not install the unrelated default
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
a competing run fails safely on the configured lock timeout instead of interleaving.

Source row shape validation and business-quality validation are distinct. Repeated
order IDs can be valid CSV rows but fail dbt's uniqueness checks. dbt also checks
nulls, accepted statuses, nonnegative totals and revenue reconciliation. A failing
upstream test prevents dependent models from building. dbt model builds are separate
transactions, so the entire raw/staging/mart workflow is **not** one atomic refresh:
a failed build may leave old marts alongside a newer raw snapshot. Consumers must
inspect run results before treating a refresh as current. Restoring the source and
rerunning repairs this fixture without deleting failure artifacts.

The runner bounds the dbt subprocess to 120 seconds and connection/lock waits.
Artifact cleanup/retention is manual at this stage. Model provenance and data-quality
observations will be integrated with PipeGuard in later checkpoints.

## Verification

```sh
uv run --directory sample-pipelines/orders --locked --env-file .env pytest -q
```

19 checks cover exact fixture values, malformed fields/headers, multiline handling,
raw replacement idempotency, transactional rollback, source rejection before writes,
concurrent-load exclusion, refusal of monitoring database access, complete dbt builds,
duplicate-order fault injection and successful recovery. Full-build checks use unique
temporary schemas and remove only those schemas. The normal raw/staging/analytics
fixture remains available for inspection.

The monitoring account is also denied connection to the sample warehouse. The two
databases share a local PostgreSQL instance; this is an access boundary, not physical
failure isolation. The sample owns its warehouse and therefore has schema-changing
privileges there; PipeGuard's runtime account remains restricted in its own database.
