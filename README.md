# PipeGuard

**Data pipeline observability, evidence-grounded investigation, and human-approved recovery.**

PipeGuard is a local-first platform designed to help operators understand pipeline failures and data-quality incidents. It will collect execution metadata, quality results, and lineage; detect incidents through deterministic rules; and present supporting evidence alongside AI-generated hypotheses.

> **Status: persistence and internal event ingestion implemented.** PostgreSQL storage, versioned migrations, validated event receipts, replay protection and execution projections are available through an internal service and local command. The HTTP API, sample pipelines, incident processing and dashboard remain planned.

[Architecture](docs/architecture/overview.md) · [Domain model](docs/architecture/domain-model.md) · [Development setup](docs/development/setup.md) · [Delivery roadmap](docs/roadmap.md) · [Documentation index](docs/README.md)

## Problem and intended workflow

A pipeline can complete successfully while still producing stale, incomplete, or invalid data. Operators need to connect execution history with dataset dependencies and quality observations to understand impact and choose a recovery action.

PipeGuard's planned workflow is:

1. **Observe:** receive execution events, transformation artifacts, quality results, and lineage.
2. **Detect:** evaluate explicit policies and group related failures into incidents.
3. **Investigate:** capture evidence and generate hypotheses with traceable support and uncertainty.
4. **Recover:** present a bounded action for human approval and record execution outcomes.
5. **Review:** retain incident history, prior attempts, evidence, and audit records.

## System boundaries

| System | Responsibility | Location |
| --- | --- | --- |
| PipeGuard application | Monitoring metadata, incident policies, evidence, investigation, approval workflows, and dashboard | `apps/pipeguard/` |
| Monitored sample pipelines | Source ingestion, business-data transformations, quality checks, and controlled fault injection | `sample-pipelines/` |

Sample pipelines emit observations consumed by PipeGuard. Business data stays in their warehouse; monitoring records belong to PipeGuard. See the [architecture overview](docs/architecture/overview.md) for planned service and database boundaries.

## Planned capabilities

- Pipeline and dataset catalog with execution and retry history.
- Data freshness, volume, schema, and integrity checks.
- Dataset lineage and downstream impact exploration.
- Deterministic incident detection with deduplication and lifecycle history.
- Captured evidence with provenance and redaction metadata.
- AI investigation with evidence citations, uncertainty, and abstention.
- Human-approved recovery with authorization, expiry, and audit records.
- Responsive operational dashboards and repeatable fault scenarios.

These are delivery targets, not currently available features. The [roadmap](docs/roadmap.md) tracks implementation stages and acceptance criteria.

## Technology plan

| Layer | Target technologies | Current state |
| --- | --- | --- |
| Python environment | Python 3.12, uv, project-local `.venv` | Configured; persistence dependencies locked |
| Persistence | PostgreSQL 17, SQLAlchemy 2, Alembic | Initial schema implemented |
| API and validation | FastAPI, Pydantic 2 | Pydantic execution contract implemented; HTTP API planned |
| Sample pipeline execution | Apache Airflow 3, dbt Core, OpenLineage | Planned; environments isolated as required |
| Web application | Next.js 16, React 19, TypeScript 5, Tailwind 4, shadcn/ui | Planned |
| Graphs and charts | React Flow, Apache ECharts | Planned |
| Runtime and checks | Docker Compose, Pytest, Playwright, GitHub Actions | PostgreSQL Compose and persistence tests available; browser tests and CI planned |
| Later integrations | Marquez, Prometheus, optional GCP | Deferred |

Library patch versions and container image references will be selected and locked at implementation. Optional 3D visualization is an exploration, not a core dependency.

## Get started

With Git, uv, and Python 3.12 available:

```sh
git clone https://github.com/RJ1899157/PipeGuard.git
cd PipeGuard
uv sync --locked
```

The repository is private and requires authorized GitHub access. For the existing checkout on the development machine, use `/Users/rishabhjain/Desktop/PipeGuard` and run only `uv sync --locked`.

The command prepares `.venv`; it does not start an application. Docker Desktop is only needed when container-backed services are introduced. See [development setup](docs/development/setup.md) for environment and dependency policies.

## Repository layout

```text
PipeGuard/
├── apps/pipeguard/          # Monitoring application boundary
├── sample-pipelines/       # Independent monitored workloads
├── docs/
│   ├── architecture/       # System boundaries and domain model
│   ├── development/        # Local setup and dependency policies
│   └── roadmap.md          # Delivery stages and acceptance criteria
├── AGENTS.md               # Project and GitHub identity rules
├── .python-version         # Python minor-version selection
├── pyproject.toml          # Python project metadata
└── uv.lock                 # Dependency resolution
```

## Project principles

Deterministic policies control incident state. AI suggestions must be tied to evidence and cannot approve or execute recovery. Secrets stay outside source control, and monitored workloads remain independent of the monitoring application.

All repository changes are owned by **RJ1899157**. See [AGENTS.md](AGENTS.md) for author, committer, and account verification requirements.
