# Development setup

## Available components

The project includes PostgreSQL 17, seventeen SQLAlchemy metadata models (including incident, lineage and evidence records), Alembic
migrations, execution ingestion, an authenticated HTTP API and integration tests.
The independent [orders workload](../../sample-pipelines/orders/README.md) adds source ingestion, dbt models and quality checks. Deterministic incident detection, lineage and a local read-only dashboard are implemented. See the [dashboard setup](../../apps/pipeguard/web/README.md) for frontend startup and its local owner access boundary.

## Prerequisites

- Python 3.12, uv, Git and Docker Desktop.
- GitHub access as `RJ1899157` for the private repository.
- Node.js 22 and pnpm 11.25.0 for the web application.

The primary checkout is `/Users/rishabhjain/Desktop/PipeGuard`. Run the following
commands from the repository root. Python packages are installed only in `.venv`;
`uv.lock` pins the resolved application and development dependencies.

## First local startup

```sh
uv sync --locked
uv run python scripts/init_local_env.py
```

The credential generator creates a mode-0600 `.env` and refuses to overwrite an
existing file. `.env.example` documents names and placeholders. Never commit
`.env`, print its contents in shared logs, or copy real credentials into examples.
Start Docker Desktop when ready to use the database, then run:

```sh
docker compose up -d --wait postgres
uv run --env-file .env alembic upgrade head
uv run --env-file .env alembic current
```

PostgreSQL listens on `127.0.0.1:55432`. Compose pins the upstream PostgreSQL 17
image by digest. The image used at this checkpoint reports PostgreSQL 17.11.
The database `pipeguard` belongs to `pipeguard_owner`, a non-superuser without
role-creation or database-creation privileges. This account is for migrations;
the restricted `pipeguard_api` runtime role is provisioned separately below. The database
admin credential is separate. The sample warehouse has a separate account and database; Airflow has its own metadata role and isolated environment.

Initialization scripts execute only on a new database volume. Changing passwords
in `.env` does not change existing database credentials; rotate those explicitly
before updating local configuration. Do not remove the volume to fix credentials
if it contains needed data.

For subsequent starts, reuse `.env` and run Compose followed by `alembic upgrade
head`. `uv run --env-file .env` loads environment values without shell activation.

## API startup

After applying migrations, configure runtime privileges and private API credentials:

```sh
uv run --env-file .env python scripts/configure_api.py
uv run --env-file .env python scripts/run_api.py
```

The provisioner is restricted to the local `pipeguard` database. It uses the local
PostgreSQL administrator for role creation and the owner for grants, saves a separate
runtime connection and administrator token privately in `.env`, and prints no secrets.
Repeated provisioning retains existing private values. Run it again after migrations
that add API-accessible tables. Do not copy placeholder values from `.env.example`.

The API runs at `http://127.0.0.1:8000`; Ctrl+C stops it. Startup refuses an owner or
privileged account. The public `/health/live` endpoint reports liveness; all metadata
routes require a bearer token. Read the [HTTP contract](../contracts/http-api.md)
for producer setup, token handling, endpoints and local boundaries.

## Database and API checks

```sh
uv run --env-file .env pytest -q
uv run --env-file .env alembic check
```

Tests require a reachable PostgreSQL database and completed API provisioning; they create unique `test_<uuid>`
schemas. They migrate and drop only those generated schemas. Use the local
synthetic-data database, never a production connection. Missing database
configuration fails explicitly rather than silently skipping integration checks.

The suite checks migration upgrade/downgrade/re-upgrade, metadata consistency,
retry-history preservation, scoped identities, rejected duplicate event keys,
foreign keys, rollback, permitted processing changes, and event content protection.
The ingestion checks also cover exact replay responses, concurrent deliveries,
receipt durability and conservative execution reconciliation. See the
[execution contract](../contracts/execution-events.md) for supported local commands.

## Migration policy

Use forward migrations for retained data. Inspect generated migrations before
applying them. The initial downgrade deletes all six tables and requires an
explicit `-x allow_data_loss=true` override, intended only for disposable data.
It is not a production recovery procedure. Always use Alembic rather than
`Base.metadata.create_all`, because event protection triggers live in migrations.

## Independent orders workload

From the repository root, with PostgreSQL running:

```sh
uv run --env-file .env python scripts/configure_sample_warehouse.py
uv sync --project sample-pipelines/orders --locked --python 3.12
uv run --directory sample-pipelines/orders --locked --env-file .env python run.py
uv run --directory sample-pipelines/orders --locked --env-file .env pytest -q
```

Workload dependencies live in `sample-pipelines/orders/.venv` and its own lockfile;
its private `.env` contains only warehouse configuration. Do not run it using the
monitoring owner's connection or administrator API token. See the workload README
for expected outputs, failure semantics and artifact locations. For scoped event reporting and orchestration, follow the
[Airflow setup](../../infra/airflow/README.md).

## Stop services

```sh
docker compose stop postgres
```

This preserves the named database volume. `docker compose down` removes the
containers/network while preserving the volume. Adding `--volumes` destroys
stored data and is not part of routine shutdown.

## Boundaries and verification

Monitoring dependencies remain in the root `.venv`; the independent orders workload uses its own local `.venv` and lockfile; future JavaScript dependencies belong in
local `node_modules`, and Airflow has an isolated constrained `.venv` and hash-pinned requirements.
GitHub changes and commits use the repository owner, `RJ1899157`.

The persistence, ingestion and API checkpoint passed 74 automated tests against local
PostgreSQL, including CLI and restricted-role HTTP checks, plus Alembic metadata
comparison. Real loopback HTTP verification passed as described in the API contract.
No browser, performance or production-security verification is claimed. See the [roadmap](../roadmap.md) for remaining acceptance criteria.

The sample checkpoint now passes 31 workload checks, including repeated dbt builds, an injected uniqueness failure and recovery. Both database access directions were verified: workload credentials cannot connect to monitoring, and monitoring runtime credentials cannot connect to the warehouse.

The orchestration checkpoint includes the 31 workload checks above and a real native Airflow failure/retry success flow, verified through PipeGuard HTTP reads. Airflow runtime configuration remains in ignored `.env.airflow` and `data/local/airflow`.

## Incident worker

After the API and Airflow are available, follow [incident monitoring operations](../incident-operations.md) to provision a dedicated read-only observer, enroll the job and start the detector using private `.env.monitoring`. Review [failure coverage](../failure-coverage.md) before interpreting monitoring confidence.

## Lineage and evidence

See [lineage operations](../lineage-operations.md) for migration, explicit delivery expectations and immutable incident snapshots. The orders adapter uses its existing isolated environment; no Marquez service or cloud account is required.

## Current hardening checkpoint

The historical test counts above describe their original checkpoints. See [current hardening verification](../hardening-verification.md) for the latest integrated checks and [local resilience](../local-resilience.md) for independent watcher installation, dedicated credentials, private backups, restore drills and interrupted-drill inspection. No public deployment or off-host monitoring is configured.
