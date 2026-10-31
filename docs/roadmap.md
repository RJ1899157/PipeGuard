# Delivery roadmap

This roadmap records product delivery milestones. Stage numbers correspond to the original thirteen-week plan; they are not fixed calendar deadlines or a claim that a stage is complete.

**Current state:** persistence and version 1 internal execution ingestion verified on PostgreSQL. Local HTTP API, scoped producer authentication, restricted runtime role and provisioning are verified. The independent orders pipeline is verified. Airflow scheduling and the bounded workload event adapter are verified. Quality-result contracts, deterministic incident detection, independent Airflow reconciliation and coverage health are verified. Bounded OpenLineage ingestion, historical traversal, lineage-delivery expectations and incident evidence snapshots are implemented and verified. The local read-only dashboard foundation is implemented with an initial attempt-scoped React Flow view. Next: expand graph/chart exploration and representative UI performance checks.

| Stage | Scope | Expected output | Acceptance criteria | State |
| --- | --- | --- | --- | --- |
| 1 | Repository and environment foundation | Desktop checkout, local Python environment, dependency metadata, application/workload boundaries, project guidance, GitHub connection | Environment synchronizes; repository belongs to RJ1899157; commits have the required author and committer | Complete; PostgreSQL container introduced in Stage 2 |
| 2 | Persistence and domain model | PostgreSQL schema, SQLAlchemy models, Alembic migrations | Disposable-DB migration; constraints, rollback, external identity, and retry-history checks | Complete for initial execution slice; replay, retry and conservative reconciliation verified |
| 3 | API and contracts | Versioned APIs, validation models, pagination, error responses, OpenAPI | Contract validation and database transaction checks | Initial API slice complete: auth, provisioning, scoped metadata reads, pagination, event receipt and OpenAPI verified |
| 4 | Independent sample pipeline | Reproducible source ingestion, raw/staging/mart transformations, dbt checks | Known outputs, malformed-input handling, and idempotent reruns | Complete: separate warehouse/environment, CSV loader, dbt models and fault/recovery checks |
| 5 | Orchestration and execution metadata | Airflow scheduling and documented metadata adapters | Success, failure, retry, duplicate delivery, and out-of-order event scenarios | Initial adapter complete: native retry and durable replay verified; independent polling reconciliation and lost-terminal recovery added in Stage 6 |
| 6 | Quality and deterministic detection | Versioned quality policies, incident grouping, severity, and lifecycle | Threshold boundaries, duplicate suppression, recovery conditions, and controlled injected faults | Initial local slice complete: execution/quality/coverage incidents, immutable history, source reconciliation and fault matrix verified; see failure-coverage report |
| 7 | Lineage and evidence | OpenLineage ingestion, historical lineage, provenance-preserving evidence | Replay handling, graph traversal, missing metadata, and traceable incident evidence | Initial local slice complete: bounded OpenLineage profile, step inventories, historical traversal, missing delivery detection and immutable scoped evidence snapshots verified |
| 8 | Responsive dashboard foundation | App shell, pipeline overview, execution history, and incident queue | Reviewed desktop/mobile layouts, keyboard use, loading/empty/error states | Initial local slice complete: approved combined design, live read-only views, desktop/mobile/keyboard and UI-state checks; see dashboard verification |
| 9 | Graph and chart exploration | Interactive lineage, execution timeline, and quality charts | Selection consistency, responsive behavior, performance fixtures, and accessible alternatives | In progress: initial attempt-scoped graph and text alternative included in Stage 8; charts, expanded timeline and measured browser fixtures remain |
| 10 | Grounded AI investigation | Bounded evidence bundles, ranked hypotheses, citations, and abstention | Groundedness evaluation, contradictory/missing evidence, prompt-injection scenarios, and reproducibility | Planned |
| 11 | Human-approved recovery | Bounded proposals, approval, authorization, execution, and audit history | Reject stale/expired/unauthorized proposals and duplicate execution; record failures and outcomes | Planned |
| 12 | Integrated operations and delivery | CI checks, end-to-end scenarios, operating procedures, and optional application metrics | Clean-environment startup and complete incident-to-recovery journey | Planned |
| 13 | Security, performance, and system debugging | Threat model, security review, measured optimization, full-system fault investigation, and regression report | Verify authentication/authorization, secrets/redaction, dependency risks, injection boundaries, recovery privileges, workload isolation, representative query/API/UI performance, and resolved regression scenarios | Planned |

## Review gates

- Review database ownership and the logical model before committing to the first schema.
- Validate the pipeline-to-application event contract before broad adapter work.
- Establish evidence provenance before introducing AI hypotheses.
- Review the dashboard design direction before expanding all product screens.
- Evaluate investigation quality and approval controls before connecting recovery execution.
- Complete an integrated demonstration and final security/performance review before claiming production readiness.

## Scope controls

Keep initial execution local with synthetic data. Cloud integrations, multi-tenant deployment, extensive distributed processing, and 3D exploration are optional extensions that require their own scope and acceptance criteria. Optimize from measured workloads rather than assuming one design is universally optimal.
