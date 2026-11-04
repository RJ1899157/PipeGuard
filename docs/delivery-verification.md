# Stage 12 local delivery verification

Date: **2026-11-04**. Tested revision: `c7bb0538132eb1ff92c989eb93cf04bec8b97cf6`.
Platform: macOS ARM64 with Docker Desktop. [Structured evidence](audit/stage12-delivery.json).

## Result

Local acceptance passes. The delivery runner exported the committed source without
private configuration, existing virtual environments or generated bundles. It
installed locked dependencies into three fresh virtual environments, initialized
a new PostgreSQL instance on an ephemeral loopback port using temporary in-memory
storage, migrated and provisioned it, and removed its temporary resources afterward.
The retained project's volume and databases were not used as test fixtures.

| Check                                                                        | Result                                                       |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------ |
| Backend suite, including stored-contract equality and recovery API lifecycle | 425 passed; one existing Starlette/HTTPX deprecation warning |
| Workload suite, including real dbt fault/recovery checks                     | 64 passed                                                    |
| Constrained Airflow interpreter suite                                        | 13 passed                                                    |
| Frontend suite                                                               | 46 passed                                                    |
| Migrations and metadata consistency                                          | Passed                                                       |
| Dependency consistency in all three Python environments                      | Passed                                                       |
| Frozen frontend install, strict TypeScript/unused checks and formatting      | Passed                                                       |
| Production build                                                             | Passed                                                       |
| Isolated authenticated HTTP/workload scenario                                | Passed                                                       |
| Built dashboard HTTP startup and access boundaries                           | Passed                                                       |
| Normal temporary-stack shutdown                                              | Passed                                                       |
| Controlled SIGTERM during a separate delivery check                          | Nonzero failure reported; cleanup passed                     |

The 548 suite cases do not include the separate HTTP acceptance and interruption
drills as additional pytest cases. Timings in structured evidence describe this
machine and its warm dependency caches, not a clean-download benchmark.

## HTTP acceptance details

The fresh catalog contained no integrations before the scenario. The check started
its own authenticated API, provisioned an integration-scoped producer and quality
policy, then deliberately failed the first orders attempt before warehouse work.
The detector opened an execution-failure incident and captured an evidence bundle.

The second attempt ran the actual CSV loading/dbt workload successfully. HTTP reads
confirmed one successful overall run, both `failed` and `succeeded` attempts, the
earlier `source_unavailable` category, a resolved execution incident with its earlier
history still present, an unchanged captured evidence bundle, 14 passing quality
checks and reported-complete attempt-scoped lineage.

The test transport remapped only the producer's three fixed POST paths to its
ephemeral API listener. Production port-8000 validation was unchanged. No hosted
AI request, scheduler run or recovery dispatch was made. Synthetic source adapters
exercise recovery proposal/approval/start/replay paths in the backend suite; the
previously authorized actual Airflow recovery remains documented separately in the
[live recovery checkpoint](recovery-live-verification.md).

The built dashboard started on a separate listener. Its HTTP check verified the
document, CSP and frame protection, rejected unexpected Host/cross-origin requests,
and returned `dashboard_not_configured` without a credential. This did not execute
a browser or repeat the earlier interactive visual audit.

## Interruption and retained-state checks

A second isolated runner received SIGTERM after reaching the backend suite. It
returned failure rather than success and reported completed cleanup. Its temporary
containers and project-labelled volumes were absent afterward. This is catchable
termination evidence; SIGKILL, Docker outage and host-loss limits remain explicit.

After acceptance, the retained API and dashboard returned HTTP 200, the Airflow DAG
was still paused and its source inventory remained eight runs. Both private recovery
switches remained `0`. Recovery records stayed at **1 action / 1 decision / 1 dispatch /
2 observations**; investigation records stayed at **16 requests / 16 outcomes**.
All **6,490 historical row IDs** from the preceding audit baseline were still present.
This follow-up checked ID presence and ledger counts; it does not claim to repeat
the preceding audit's complete content-hash comparison.

## CI status and remaining gate

GitHub registered the **Delivery checks** workflow as active. Its YAML parses,
uses full action commit pins and read-only contents permission, and has only a
manual `workflow_dispatch` trigger. After the owner confirmed included compute
and spending controls, [manual run 41809107524](https://github.com/RJ1899157/PipeGuard/actions/runs/41809107524)
was dispatched against `594c991` under actor and triggering actor `RJ1899157`.
The dispatch returned HTTP 502, but independent reads confirmed run creation.
At the follow-up snapshot it remained `queued` with zero jobs; normal and force
cancellation both returned HTTP 409 claiming it had not been queued yet. This is
an inconsistent GitHub scheduling state, not a recorded application test failure.
This historical queue snapshot is superseded by the hosted acceptance below.

### Hosted Linux acceptance follow-up

On 2026-11-04, the owner manually started [run #3](https://github.com/RJ1899157/PipeGuard/actions/runs/41818080465) against
`0dc22d91dd26c0d7978cb8f610a4f48b0e4ba709`. Both **Application, workload and Airflow**
and **Dashboard types, tests and production build** completed successfully. The
Python job reached temporary PostgreSQL shutdown; both isolated runners reported
completion. Actor and triggering actor were RJ1899157. This verifies the Linux
delivery path as well as the separately recorded local acceptance. The private
per-suite logs/reports were not uploaded, as designed. No retained local source
run, hosted AI generation, recovery dispatch or billing change was introduced.

The owner requested deletion of old run #1. GitHub rejected DELETE with 403 and
normal/force cancellation with 409 claiming the run had not been queued. The old
record remains unresolved and is not used as proof of CI acceptance. Automatic
triggers remain disabled.

One initial preparation run passed the Python suites but failed the newly added
HTTP scenario because it assumed a configurable producer port. The acceptance
transport was corrected and the complete fresh-export check then passed at the
revision above. The failed preparation run remains recorded in private local logs.

Stage 12's local and hosted Linux delivery paths are verified. Stage 13's
[local gate](stage13-verification.md) also passes. Stage 14's final full-project
audit remains required. Optional application metrics were not added
without a concrete operating need. Existing container-advisory, off-host monitoring,
off-device backup, broader AI evaluation and deployment limits remain open in the
[next-session checkpoint](next-session.md#explicit-remaining-limits).
