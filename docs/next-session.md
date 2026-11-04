# Next-session checkpoint

Verified: **2026-11-04**, after [Stage 12 local delivery acceptance](delivery-verification.md).

## Current verified state

- Stage 10's bounded advisory evaluation gate passes; broader live incident-class accuracy remains unestablished.
- Stage 11 passes [bounded local live acceptance](recovery-live-verification.md): separate approval/start, durable intent, one successful new run, 14 passing quality checks, complete recorded lineage, replay/conflict checks and disabled-state restoration. Earlier failures remain retained.
- The fresh audit passed **425 backend + 46 frontend + 64 workload + 13 Airflow cases**, strict TypeScript/format checks and production build. Contracts match runtime models. Fresh backups of all three databases passed disposable restore checks.
- Live services were restored after isolated browser faults. The source baseline remains **8 native runs / 14 attempt snapshots**. All **6,490** captured immutable records were preserved. The ledger remains **1 action / 1 approval / 1 dispatch / 2 observations**, with **16 investigation requests / 16 outcomes**.
- The DAG is **daily-but-paused**. Keep `PIPEGUARD_AIRFLOW_RECOVERY_ENABLED=0` and `PIPEGUARD_RECOVERY_EXECUTION_ENABLED=0`. The expired historical proposal cannot authorize new work. AI findings never authorize actions.

- Stage 12 local delivery acceptance passes on a fresh committed export: 548 suite cases, real HTTP/workload retry, quality/lineage, unchanged captured evidence, production-dashboard HTTP startup and controlled SIGTERM cleanup. The manual workflow is registered on GitHub; a manual hosted run is queued with zero jobs at the latest checkpoint and Linux execution remains unverified.

Runtime availability must be checked again after sleep, reboot or a closed session; these are verified checkpoint results, not a promise that services start automatically.

## Next work

1. **Stage 12 hosted-CI follow-up.** The isolated runner, manual workflow and operating procedures are implemented and locally verified. Included compute/spending controls were confirmed and manual run [41809107524](https://github.com/RJ1899157/PipeGuard/actions/runs/41809107524) was created under RJ1899157. GitHub reports it queued with zero jobs but rejects both cancellation methods as not yet queued. Inspect the run-page message; do not submit duplicates or increase spending limits to bypass this inconsistency. Automatic triggers remain disabled; Linux execution is pending.
2. **Stage 13: final security, performance and debugging gate.** Revalidate the integrated delivery after Stage 12: threat model, permissions, secrets/injection boundaries, dependency risks, recovery authority, representative larger histories/graphs, measured query/process performance, interruption/outage/restore behavior and final issue closure.
3. **Stage 14: final full-project multi-agent audit.** Independently review the final revision after Stage 13, covering all owned files, features, buttons/views, operating commands and documentation. Fix reproduced defects, retest affected behavior, measure optimization, preserve evidence and record unresolved risks before final sign-off.

See the [roadmap](roadmap.md). The current audit provides a baseline; do not repeat it from scratch unless changes or runtime evidence justify it. No new retained workload, recovery unpause or hosted generation is needed for the remaining delivery/hardening work.

## Explicit remaining limits

| Boundary                      | Current state                                                                                                                   | Needed for broader guarantees                                                                                                                  |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Container advisories          | 130 installed-source matches; no published nonzero trixie fixed versions in the matched records; official ARM64 image unchanged | Published compatible fixes or a separately reviewed image design; [current evidence](post-recovery-audit.md#dependency-and-container-findings) |
| Total host/network loss       | Watcher runs on this Mac                                                                                                        | An independent always-on device or externally hosted watcher                                                                                   |
| Disk/host loss                | Verified backups remain on this disk                                                                                            | Separately protected backup destination and transfer/restore procedure                                                                         |
| Larger/distributed deployment | Bounded snapshots and recovery inventories, growing retained history, local warehouse exclusion                                 | Reviewed incremental processing/retention and cross-host fencing                                                                               |
| Public multi-user access      | Local-owner interfaces on loopback                                                                                              | Named-user authentication, authorization, tenant isolation and deployment design                                                               |
| Atomic workload publication   | Raw loading and dbt transformations use separate transactions                                                                   | Reviewed publication design if atomic visibility is required; partial outcomes remain observable                                               |
| Broader AI accuracy           | Bounded evaluation passed; live coverage is limited                                                                             | Representative incident-class evaluation before stronger accuracy claims                                                                       |

These limits remain open; no external account, public endpoint, backup upload, unverified dependency switch or automatic recovery was introduced to hide them.

The follow-up preceding Stage 12 rechecked the official image manifest and advisory sources: 130 matches remain and the official ARM64 image is unchanged. No external backup volume is mounted. The reproduced code defects are closed in the preceding audit; the external-resource limits and optional deployment designs above are not represented as fixed. Stage 14 is now an explicit final gate rather than being implied by Stage 13.
