# Documentation

PipeGuard documentation describes product scope, proposed architecture, local development, and delivery criteria. Proposed behavior is explicitly distinguished from implemented functionality.

## Start here

[Next-session checkpoint](next-session.md) records the verified state before the break and the requirements that still depend on external resources or a future deployment design.

| Document                                                     | Purpose                                                                                   |
| ------------------------------------------------------------ | ----------------------------------------------------------------------------------------- |
| [Project overview](../README.md)                             | Product problem, planned capabilities, technology plan, and current status                |
| [Architecture overview](architecture/overview.md)            | Service boundaries, data ownership, metadata flow, and deployment scope                   |
| [Domain model](architecture/domain-model.md)                 | Entity identity, relationships, event handling, and persistence invariants                |
| [Dashboard foundation](architecture/dashboard-foundation.md) | Design checkpoint, graph technology decision, display invariants and planned verification |
| [Development setup](development/setup.md)                    | Repository access, Python environment, dependencies, and verification status              |
| [Delivery roadmap](roadmap.md)                               | Thirteen delivery stages with outputs and acceptance criteria                             |

## Dashboard

- [Setup and local access](../apps/pipeguard/web/README.md)
- [Foundation verification](dashboard-verification.md)
- [Graph and chart verification](exploration-verification.md)
- [System audit and interruption recovery](system-audit.md)
- [Pre-investigation hardening verification](hardening-verification.md)
- [Local resilience and backup/restore](local-resilience.md)

## Operations and security

- [Investigation integration verification](investigation-verification.md): regression, grounding, browser and live provider checks.

- [Advisory investigation](investigation-operations.md): durable Groq investigations, bounded evidence projection and remaining Stage 10 work.

- [Container security triage](container-security.md): installed-package advisories, release classifications and unresolved upstream risks.
- [Local resilience operations](local-resilience.md): watcher, private backups, restore verification and limits.

## Sample workloads

- [Orders pipeline](../sample-pipelines/orders/README.md): independent warehouse, ingestion, dbt models, quality checks and verification.

## Documentation conventions

- Label design proposals and planned functionality clearly.
- Update setup instructions when commands, dependencies, or service requirements change.
- Record significant architecture decisions and tradeoffs alongside their affected design.
- Add API contracts, migration instructions, operating procedures, and incident runbooks when those systems exist.
- Keep examples synthetic and secret-free. Avoid credentials, private payloads, and machine-specific data in shared examples.
- Keep personal lessons, exercises, course recommendations, and individual progress outside the repository.

## Implemented contracts

- [Execution events v1](contracts/execution-events.md): validation, replay, reconciliation and local command.
- [Execution JSON Schema](contracts/execution-event-v1.schema.json): machine-readable field contract.

- [Local HTTP API](contracts/http-api.md): authentication, endpoints, privileges and verified boundaries.
- [OpenAPI v1](contracts/http-api-v1.openapi.json): machine-readable HTTP contract.

## Orchestration

- [Local Airflow](../infra/airflow/README.md): isolated installation, private configuration, DAG controls and verified retry behaviour.

## Incident monitoring

- [Detection architecture](architecture/incident-detection.md): deterministic rules, immutable evidence, source authority and recovery semantics.
- [Operations](incident-operations.md): worker setup, API inspection, scope and heartbeat behavior.
- [Failure coverage](failure-coverage.md): scenario matrix, verification methods and residual limits.
- [Quality report v1](contracts/quality-reports.md): rule outcomes, inventory and replay contract.

## Lineage and evidence

- [Architecture](architecture/lineage-evidence.md): dataset identity, step inventory, historical graph semantics and evidence provenance.
- [Contract](contracts/lineage-events.md): bounded OpenLineage profile and authenticated APIs.
- [Operations](lineage-operations.md): enrollment, delivery, replay and snapshot capture.
- [Verification](lineage-verification.md): failure scenarios and live checkpoint evidence.
