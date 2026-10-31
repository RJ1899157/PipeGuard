# Failure coverage and verification

This matrix records implemented behavior and verification scope. It is not a claim that every possible real-world failure can be observed or uniquely diagnosed. Detection preserves uncertainty when evidence is missing or contradictory.

## Execution and delivery

| Scenario | Detection / retained evidence | Verification |
| --- | --- | --- |
| Failed attempt followed by successful native retry | Overall run succeeds; prior failed attempt and resolved execution incident remain | Real Airflow retry plus PostgreSQL tests |
| Terminal before start, late old attempt, exact replay | No terminal regression or duplicated occurrence | All six orders of start/failure/retry-success, duplicate each delivery, evaluate after each delivery |
| Success/failure/cancellation contradiction | Reconciliation flag and open conflicting-evidence incident | All six ordered unequal terminal pairs |
| Process killed after durable receipt, before projection | Receipt remains; worker projects it after restart; no invented terminal success | Real child SIGKILL in isolated PostgreSQL schema |
| Worker dies without terminal observation | Deadline incident; independent Airflow polling can supply source terminal evidence | Timeout boundary tests; source-only and lost-terminal reconciliation tests |
| Workload never starts / is blocked upstream | Configured DAG/task public history and DAG-run failure evidence | Every documented task-state mapping, source-only projection and missing-history tests |
| Failed DAG whose monitored task is skipped or absent | Separate DAG-run failure observation/incident; absent task produces incomplete source coverage | Adapter normalization and source-fault tests; no fabricated task failure |
| Missing intermediate attempt | Attempt-history coverage incident; late missing evidence can recover coverage | Gap/reordered-history tests |
| Queued, deferred, waiting or running too long | Per-attempt missing-terminal deadline; legitimate skip remains explicit | Exact before/at-deadline tests and source state mapping |
| Job never runs | Optional explicit expected-activity interval plus grace | Before/at-deadline and explicit new-activity recovery tests |
| Producer reports future event time | Clock-skew uncertainty; future success cannot clear execution failure | Clock-skew tests |
| Event identity reused for different content | HTTP 409 plus immutable hash-only conflict observation | Execution and quality conflict tests |
| API unreachable | Private local outbox retains both execution and quality observations; replay later | Real execution outage/replay in orchestration checkpoint; quality routing/outage tests |
| Projection database operation fails after receipt | Durable receipt remains pending, retried by worker | Injected database operation failure at HTTP boundary |
| Unsupported or invalid stored contract | Failed processing metadata; backlog remains visible, other receipts continue | Invalid stored-contract and existing unsupported-contract tests |
| Duplicate concurrent detector processes | One incident and deduplicated history | Eight evaluations across four threads with independent database sessions |
| Detector crashes inside incident transaction | Incident/history writes roll back; completion heartbeat not advanced | Injected detector exception with transaction assertions |

## Quality

| Scenario | Detection / retained evidence | Verification |
| --- | --- | --- |
| dbt pass, fail/warn, error, skip, unrecognized outcome | Bounded rule/version/outcome evidence; every nonpass visible | Artifact tests and database tests |
| Execution succeeds but quality fails | Execution and quality remain independent | 36 combinations of execution, quality, source health and replay |
| Quality report arrives without any execution event | Execution-evidence gap plus quality failure if applicable | Orphan quality report tests |
| Missing / malformed / oversized artifacts | Incomplete inventory, never an invented pass | Artifact extraction bounds and malformed/missing artifact tests |
| Results and manifest come from different invocations | Unknown outcomes and incomplete inventory | Mismatched invocation test |
| Duplicate result identifiers | Unknown outcomes and incomplete inventory | Duplicate result test |
| Manifest check absent from run results | Unknown check and incomplete inventory | Partial-result tests |
| Complete result inventory changes | Coverage warning; removed checks cannot silently count as unchanged coverage | Inventory-change test |
| Same rule passes on a later retry | Same-version quality failure resolves; earlier failure remains | Late-arrival and replay quality tests |
| Rule implementation changes | New fingerprint; previous version's failure does not implicitly recover | Version-isolation and macro-content tests |
| Same rule/version/attempt reports contradictory outcomes | Open quality-conflict uncertainty | Database tests |
| Terminal run without complete quality report | Quality-missing incident after configured grace | Missing/incomplete/complete recovery tests |

The full orders build currently reports three transformed models and fourteen quality checks. The live milestone run reported fourteen passes, complete inventory, two attempts and a resolved execution incident. This validates the sample flow; it does not demonstrate all business-quality dimensions such as freshness and schema drift.

## Monitoring and dependencies

| Scenario | Detection / retained evidence | Verification |
| --- | --- | --- |
| Airflow authentication, HTTP, timeout, connection or invalid JSON failure | Fixed safe source error and incomplete coverage | Transport fault tests; dedicated viewer login verified live |
| Observer attempts to modify Airflow | Denied by viewer role | Live forbidden DAG-run write request |
| Scheduler, metadata or DAG processor unhealthy; DAG import error | Incomplete source coverage; already readable source facts still retained | Source health and partial-scan tests |
| Incomplete pages, changing page contents, missing tries, missing timestamps | Explicit source gap, never complete coverage | Pagination/history/shape tests |
| Previously observed runs disappear | History-disappeared coverage fault; stored facts remain | Two-cycle history disappearance test |
| Source exceeds response/scan limits or uses task mapping | Explicit unsupported/incomplete coverage | Boundary checks and mapping/oversize response tests |
| Detector stopped | API computes global and per-job heartbeat staleness after 90 seconds | Heartbeat age tests |
| One watched job fails evaluation | Other jobs still evaluated; affected job and global completion remain stale | Selective job failure isolation test |
| Integration disabled or job not enrolled | Disabled-monitor condition or unmonitored coverage status | Disabled integration and coverage tests |
| Airflow DAG paused with an expected activity policy | Scheduled-source-paused condition | Explicit policy behavior; sample intentionally has no activity expectation |
| Secret values in source conf/notes/executor configuration | Excluded from normalized snapshots | Secret-marker allowlist test and local artifact review |

## Residual limits and operational requirements

- An external watchdog is required to notify while the host, API or database is unavailable. No in-process detector can guarantee notification from a powered-off host.
- Polling is eventual. Execution evidence that changes and disappears between polls may be unavailable; pre-existing history purged before the first scan cannot be reconstructed. Source history retention must exceed expected monitoring outages.
- A configured job/task is the observation boundary. Unregistered pipelines, unmapped tasks, business rules that were never defined and unconfigured external dependencies are not implicitly covered.
- The example supports one unmapped task per watch and full dbt builds. Dynamic task mapping and selected dbt invocations must get dedicated contracts before being represented as fully covered.
- Producer success and complete-inventory reports are attributed claims. A malicious producer or database administrator can falsify them. Immutable history and hashes do not prove business truth.
- Policy replacement, administrative evidence adjudication and incident notification delivery are not implemented. Contradictory evidence remains open rather than being automatically dismissed.
- No real host power failure, disk-full event, PostgreSQL server crash, network partition, Airflow worker kill, or distributed failover was performed. Process SIGKILL, source transport faults, database-operation faults and detector crashes were exercised as specified above.
- Retained evidence currently grows without automatic archival; scans over 10,000 DAG runs produce explicit incomplete coverage. Incremental processing, retention policies, off-host alerts/backups and measured scale/security work remain required before production use.

## Checkpoint evidence — 2026-10-31

- PostgreSQL suite: 155 passing tests, including deterministic detection, source faults, HTTP scope, concurrency, append-only enforcement and controlled SIGKILL.
- Independent workload suite: 38 passing tests, including artifact completeness and quality outbox delivery.
- Alembic: no model/schema drift at revision `fc50161412bd`.
- Live Airflow `milestone_incident_retry`: Airflow success; PipeGuard success without reconciliation flag; attempt 1 failed (`source_unavailable`), attempt 2 succeeded; fourteen passing checks with complete inventory; execution incident resolved and retained.
- Dedicated Airflow viewer denied an attempted write. Live API schema matched the checked-in OpenAPI document.
- Private runtime configurations checked for owner-only permissions. Generated local logs/artifacts were checked against actual configured credentials; no matches. This targeted check is not a full security audit.
- One legacy synthetic HTTP smoke-test job remains explicitly unmonitored in coverage. The active orders/Airflow job has an explicit watch; the legacy catalog entry is not silently counted as healthy.

The monitoring suite emits an upstream Starlette/HTTPX test-client deprecation warning. It does not fail the checks; the final dependency/security checkpoint remains planned.
