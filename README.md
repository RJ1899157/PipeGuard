# PipeGuard

PipeGuard is a local-first platform for data pipeline observability and incident management. It ingests pipeline metadata and quality results, tracks lineage, detects incidents deterministically, gathers evidence, and offers evidence-grounded investigation with human-approved recovery.

## Keep the two systems separate

- `apps/pipeguard/` is the monitoring application.
- `sample-pipelines/` holds independent pipelines that PipeGuard monitors.

The sample pipelines are inputs to the monitoring system, not part of the PipeGuard application itself.

## Local development status

Python 3.12 is pinned for this project. Python dependencies are managed with uv and installed into the project-local `.venv/` from `pyproject.toml` and `uv.lock`. Docker Desktop is intentionally left stopped until a planned task needs containers.

To synchronize the Python environment, run `uv sync --locked` from the project root. This environment currently contains no application dependencies; they will be added and pinned as the relevant roadmap work begins.

See [AGENTS.md](AGENTS.md) for repository boundaries, security expectations, and the `RJ1899157`-only GitHub and commit identity policy.

## Architecture

- [Proposed domain model and database boundaries](docs/architecture/domain-model.md)

The logical design is documented. Database schema implementation and migration checks are still pending.
