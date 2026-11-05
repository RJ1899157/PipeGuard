# PipeGuard

**Data pipeline observability, evidence-grounded investigation, and human-approved recovery.**

PipeGuard is a local-first platform designed to help operators understand pipeline failures and data-quality incidents. It collects execution metadata, quality results and bounded dataset lineage, detects incidents through deterministic rules and preserves supporting evidence. Manual hosted-AI investigation now has durable audit records and an incident-dashboard flow; the bounded local advisory evaluation gate passes using Groq-hosted GPT-OSS 120B. Broader incident-class accuracy remains unestablished. Human recovery review records bounded proposals and explicit decisions. A separate supervised recovery worker now provides executable approvals, durable dispatch intent and exact-run reconciliation through the CLI and dashboard; a controlled live failure-to-recovery chain is verified, with execution disabled again afterward.

> **Status: local monitoring and deterministic detection implemented.** Authenticated producer setup, event submission, replay protection, execution history and scoped reads are available. An independent orders workload with dbt transformations and quality checks is available. Airflow orchestration and scoped execution reporting are implemented. Deterministic incidents, versioned quality reports, read-only Airflow reconciliation and monitoring coverage checks are implemented. Dataset lineage, historical graph traversal and immutable incident evidence bundles are implemented through a bounded OpenLineage profile. The local dashboard now exposes pipeline coverage, execution attempts, incident history and attempt-scoped interactive lineage. Manual Groq investigation is integrated through authorized APIs and the incident dashboard, with durable audit history and bounded grounding checks. A controlled human-authorized recovery chain passes local acceptance; broader model-quality coverage remains limited. See the [live recovery checkpoint](docs/recovery-live-verification.md).

[Architecture](docs/architecture/overview.md) · [Domain model](docs/architecture/domain-model.md) · [Development setup](docs/development/setup.md) · [Delivery roadmap](docs/roadmap.md) · [Documentation index](docs/README.md) · [Incident operations](docs/incident-operations.md) · [Failure coverage](docs/failure-coverage.md) · [Lineage and evidence](docs/architecture/lineage-evidence.md)

## Problem and intended workflow

A pipeline can complete successfully while still producing stale, incomplete, or invalid data. Operators need to connect execution history with dataset dependencies and quality observations to understand impact and choose a recovery action.

PipeGuard's workflow is:

1. **Observe:** receive execution events, transformation artifacts, quality results, and lineage.
2. **Detect:** evaluate explicit policies and group related failures into incidents.
3. **Investigate:** capture evidence and generate hypotheses with traceable support and uncertainty.
4. **Recover:** present a bounded action for human approval and record execution outcomes.
5. **Review:** retain incident history, prior attempts, evidence, and audit records.

## System boundaries

| System                     | Responsibility                                                                                     | Location            |
| -------------------------- | -------------------------------------------------------------------------------------------------- | ------------------- |
| PipeGuard application      | Monitoring metadata, incident policies, evidence, investigation, approval workflows, and dashboard | `apps/pipeguard/`   |
| Monitored sample pipelines | Source ingestion, business-data transformations, quality checks, and controlled fault injection    | `sample-pipelines/` |

Sample pipelines emit observations consumed by PipeGuard. Business data stays in their warehouse; monitoring records belong to PipeGuard. See the [architecture overview](docs/architecture/overview.md) for planned service and database boundaries.

## Capabilities and coverage

- Pipeline and dataset catalog with execution and retry history.
- Versioned reported quality checks, including the sample pipeline’s integrity rules.
- Dataset lineage and downstream impact exploration.
- Deterministic incident detection with deduplication and lifecycle history.
- Captured evidence with provenance and redaction metadata.
- AI investigation with evidence citations, uncertainty, and abstention.
- Human-approved recovery with authorization, expiry, and audit records.
- Responsive operational dashboards and repeatable fault scenarios.

Execution history, reported quality, deterministic detection, observed lineage, advisory investigation and scoped recovery are implemented as bounded local slices. Broader quality policies and deployment extensions remain separate scope. The [roadmap](docs/roadmap.md) tracks implementation stages and acceptance criteria.

## Technology plan

| Layer                     | Target technologies                                            | Current state                                                                                 |
| ------------------------- | -------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| Python environment        | Python 3.12.16, uv, project-local `.venv`                         | Configured; persistence dependencies locked                                                   |
| Persistence               | PostgreSQL 17, SQLAlchemy 2, Alembic                           | Initial schema implemented                                                                    |
| API and validation        | FastAPI, Pydantic 2                                            | Authenticated local API and versioned contracts implemented                                   |
| Sample pipeline execution | Apache Airflow 3, dbt Core, OpenLineage                        | Orders/dbt workload, Airflow execution adapter and bounded OpenLineage ingestion implemented  |
| Web application           | Next.js 16, React 19, TypeScript 5, Phosphor icons, CSS tokens | Local dashboard with explicit advisory investigation; pnpm lockfile committed                 |
| Graphs and charts         | React Flow; Apache ECharts                                     | Attempt-scoped graph, execution timeline, quality charts and textual alternatives implemented |
| Runtime and checks        | Docker Compose, Pytest, Playwright, GitHub Actions             | Isolated delivery checks and both manual hosted Linux CI jobs passed                |
| Later integrations        | Marquez, Prometheus, optional GCP                              | Deferred                                                                                      |

Library patch versions, the official container base digest and the two-package Debian security overlay are locked; unresolved advisories are documented. Optional 3D visualization is an exploration, not a core dependency.

## Get started

With Git, uv 0.13.7, and Python 3.12.16 available:

```sh
git clone https://github.com/RJ1899157/PipeGuard.git
cd PipeGuard
uv sync --locked
```

The repository is private and requires authorized GitHub access. For the existing checkout on the development machine, use `/Users/rishabhjain/Desktop/PipeGuard` and run only `uv sync --locked`.

The command prepares the monitoring application’s `.venv`. The development setup documents database migration, API provisioning and startup. The [orders workload](sample-pipelines/orders/README.md) has its own environment and execution instructions. Docker Desktop is required for the existing PostgreSQL-backed local runtime. See [development setup](docs/development/setup.md) for environment and dependency policies.

For the dashboard, follow the [web setup](apps/pipeguard/web/README.md). It runs locally on port 3000 and uses the existing API without exposing its credential to the browser.

## Repository layout

```text
PipeGuard/
├── apps/pipeguard/          # Monitoring application boundary
├── sample-pipelines/       # Independent monitored workloads
├── docs/
│   ├── architecture/       # System boundaries and domain model
│   ├── development/        # Local setup and dependency policies
│   └── roadmap.md          # Delivery stages and acceptance criteria
├── .python-version         # Exact Python security-patch selection
├── pyproject.toml          # Python project metadata
└── uv.lock                 # Dependency resolution
```

## Project principles

Deterministic policies control incident state. AI suggestions must be tied to evidence and cannot approve or execute recovery. Secrets stay outside source control, and monitored workloads remain independent of the monitoring application.

All repository changes are owned by **RJ1899157**.

## Local hardening and operations

[Hardening verification](docs/hardening-verification.md) records independent local service monitoring, dedicated minimal credentials, verified database restore drills, consistent captured pagination, full-scope quality conflict summaries and measured query improvements. [Operating procedures](docs/local-resilience.md) describe the supported local boundaries and recovery checks.

See [manual investigation operations](docs/investigation-operations.md) for the current Stage 10 checkpoint and its limits.

Latest verification: [Stage 13 local acceptance](docs/stage13-verification.md) records 562 passing suite cases, bounded request/graph resources, measured graph improvements, actual HTTP deadline and database-access fault checks, three restore drills and preserved history. [Delivery operations](docs/delivery-operations.md) provides isolated checks and manual CI. Hosted Linux CI passed both jobs in [run #3](https://github.com/RJ1899157/PipeGuard/actions/runs/41818080465). The [roadmap](docs/roadmap.md) retains Stage 14's final full-project audit; [deployment risks](docs/security-threat-model.md#deployment-restrictions-and-unresolved-risks) remain explicit.

The [expanded AI evaluation](docs/investigation-expanded-evaluation.md) passes six version-11 trials across quality failures, monitoring gaps and conflicting attempt evidence, retaining two earlier failed cohorts. Current local checks pass 566 cases; these small synthetic trials do not establish general root-cause accuracy.

Final checkpoint: [Stage 14 audit](docs/stage14-audit.md) passed **599** tests plus current browser, restore, preservation and hosted Linux CI checks. All fourteen roadmap stages have local acceptance checkpoints; remaining image maintenance and deployment limits are recorded explicitly.
