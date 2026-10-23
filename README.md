# PipeGuard

PipeGuard is a local-first platform for data pipeline observability and incident management. It ingests pipeline metadata and quality results, tracks lineage, detects incidents deterministically, gathers evidence, and offers evidence-grounded investigation with human-approved recovery.

## Keep the two systems separate

- `apps/pipeguard/` is the monitoring application.
- `sample-pipelines/` holds independent pipelines that PipeGuard monitors.

The sample pipelines are inputs to the monitoring system, not part of the PipeGuard application itself.

## Local development status

Week 1 setup is in progress. Python 3.12 is the target runtime; project Python dependencies will be installed only into `.venv/`. Docker Desktop is intentionally left stopped until a later task requires containers.

See [AGENTS.md](AGENTS.md) for repository boundaries, security expectations, and the `RJ1899157`-only GitHub and commit identity policy.
