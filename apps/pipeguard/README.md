# PipeGuard application

Monitoring application boundary, separate from `sample-pipelines/`.

- `src/pipeguard/db/`: SQLAlchemy metadata models and explicit database configuration.
- `migrations/`: reviewed Alembic schema revisions and event-history protection.
- `src/pipeguard/ingestion/`: validated execution receipts and transactional projections.
- `tests/`: PostgreSQL integration checks using disposable schemas.

Run commands from the repository root; see [development setup](../../docs/development/setup.md).
The HTTP API, dashboard and incident workflows are not implemented yet.
See the [execution contract](../../docs/contracts/execution-events.md) for ingestion scope and local commands.
