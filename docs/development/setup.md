# Development setup

## Available components

The project includes PostgreSQL 17, six SQLAlchemy metadata models, an Alembic
migration and persistence integration tests. There is no API, dashboard, incident
engine or sample workload yet.

## Prerequisites

- Python 3.12, uv, Git and Docker Desktop.
- GitHub access as `RJ1899157` for the private repository.
- Node.js 22 and pnpm will be needed for the future web application.

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
a separate restricted runtime role must precede API deployment. The database
admin credential is separate. Airflow and sample warehouse accounts are deferred.

Initialization scripts execute only on a new database volume. Changing passwords
in `.env` does not change existing database credentials; rotate those explicitly
before updating local configuration. Do not remove the volume to fix credentials
if it contains needed data.

For subsequent starts, reuse `.env` and run Compose followed by `alembic upgrade
head`. `uv run --env-file .env` loads environment values without shell activation.

## Database checks

```sh
uv run --env-file .env pytest -q
uv run --env-file .env alembic check
```

Tests require a reachable PostgreSQL database and create unique `test_<uuid>`
schemas. They migrate and drop only those generated schemas. Use the local
synthetic-data database, never a production connection. Missing database
configuration fails explicitly rather than silently skipping integration checks.

The suite checks migration upgrade/downgrade/re-upgrade, metadata consistency,
retry-history preservation, scoped identities, rejected duplicate event keys,
foreign keys, rollback, permitted processing changes, and event content protection.
Out-of-order event storage is tested; automated reconciliation and exact replay
responses will be tested with ingestion implementation.

## Migration policy

Use forward migrations for retained data. Inspect generated migrations before
applying them. The initial downgrade deletes all six tables and requires an
explicit `-x allow_data_loss=true` override, intended only for disposable data.
It is not a production recovery procedure. Always use Alembic rather than
`Base.metadata.create_all`, because event protection triggers live in migrations.

## Stop services

```sh
docker compose stop postgres
```

This preserves the named database volume. `docker compose down` removes the
containers/network while preserving the volume. Adding `--volumes` destroys
stored data and is not part of routine shutdown.

## Boundaries and verification

Python dependencies remain in `.venv`; future JavaScript dependencies belong in
local `node_modules`, and Airflow constraints must remain isolated as necessary.
Repository identity and commit rules are in [AGENTS.md](../../AGENTS.md).

The initial checkpoint passed 16 PostgreSQL integration tests and Alembic metadata
comparison. No API, browser, performance or production-security verification is
claimed. See the [roadmap](../roadmap.md) for remaining acceptance criteria.
