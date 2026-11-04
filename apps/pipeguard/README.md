# PipeGuard application

Monitoring application boundary, separate from `sample-pipelines/`.

- `src/pipeguard/db/`: SQLAlchemy metadata models and explicit database configuration.
- `migrations/`: reviewed Alembic schema revisions and event-history protection.
- `src/pipeguard/api/`: authenticated local HTTP routes and explicit response contracts.
- `src/pipeguard/ingestion/`: validated execution receipts and transactional projections.
- `tests/`: PostgreSQL integration checks using disposable schemas.

Run commands from the repository root; see [development setup](../../docs/development/setup.md).
The dashboard, deterministic incidents, quality observations, lineage and immutable evidence are implemented. Manual advisory investigation and the separate human-authorized recovery flow pass bounded local acceptance; broader model-quality coverage and production deployment remain outside that claim. Both recovery capability switches remain off. The local HTTP API
is documented in the [HTTP contract](../../docs/contracts/http-api.md).
See the [execution contract](../../docs/contracts/execution-events.md) for ingestion scope and local commands.
