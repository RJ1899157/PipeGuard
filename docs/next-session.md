# Next-session checkpoint

Latest verification: **2026-11-05**, after [container maintenance](container-maintenance.md).
Earlier stage checkpoints below retain their original evidence and counts.

## Current verified state

- Stage 10's bounded advisory evaluation gate passes; broader live incident-class accuracy remains unestablished.
- Stage 11 passes [bounded local live acceptance](recovery-live-verification.md): separate approval/start, durable intent, one successful new run, 14 passing quality checks, complete recorded lineage, replay/conflict checks and disabled-state restoration. Earlier failures remain retained.
- The earlier post-recovery audit passed **425 backend + 46 frontend + 64 workload + 13 Airflow cases**, strict TypeScript/format checks and production build. Contracts match runtime models. Fresh backups of all three databases passed disposable restore checks.
- Live services were restored after isolated browser faults. The source baseline remains **8 native runs / 14 attempt snapshots**. All **6,490** captured immutable records were preserved. The ledger remains **1 action / 1 approval / 1 dispatch / 2 observations**, with **16 investigation requests / 16 outcomes**.
- The DAG is **daily-but-paused**. Keep `PIPEGUARD_AIRFLOW_RECOVERY_ENABLED=0` and `PIPEGUARD_RECOVERY_EXECUTION_ENABLED=0`. The expired historical proposal cannot authorize new work. AI findings never authorize actions.

- Stage 12 local delivery acceptance passes on a fresh committed export: 548 suite cases, real HTTP/workload retry, quality/lineage, unchanged captured evidence, production-dashboard HTTP startup and controlled SIGTERM cleanup. The manual workflow is registered on GitHub; [run #3](https://github.com/RJ1899157/PipeGuard/actions/runs/41818080465) passed both hosted Linux jobs against `0dc22d91dd26c0d7978cb8f610a4f48b0e4ba709`.

- Stage 13 uses patched **Python 3.12.16 / Node.js 22.23.4** and passes **562 cases** plus real HTTP admission, runtime database-access outage/restoration, production startup and three fresh restore drills. API/dashboard were refreshed; **7,688** captured rows retain IDs/content hashes, source **8/14** and ledgers are unchanged. The prior GitHub checkpoint and implementation push succeeded; both hosted Linux CI jobs subsequently passed in [run #3](https://github.com/RJ1899157/PipeGuard/actions/runs/41818080465).

The prepared checkout keeps its uv/Node launchers in ignored `data/local/toolchain/bin`.
To select them in a new terminal from the repository root, use
`export PATH="$PWD/data/local/toolchain/bin:$PATH"`. System runtimes were not replaced;
the original three environments are preserved in private runtime rollback storage.

Runtime availability must be checked again after sleep, reboot or a closed session; these are verified checkpoint results, not a promise that services start automatically.

- The [expanded AI evaluation](investigation-expanded-evaluation.md) passes its six-trial version-11 gate for quality failure, source gaps and conflicting attempt evidence. Two failed earlier cohorts remain retained. Current checks pass **566 cases**; the public ledger stays **16/16**, with **16 additional evaluation requests/outcomes** isolated separately. Confidence and broader real-world accuracy remain unestablished.

## Final checkpoint and future work

[Stage 14](stage14-audit.md) passed its bounded local audit on 2026-11-05 with **599** cases,
current browser evidence, three fresh restores and both hosted Linux CI jobs on
`5f10728e70a4200167337d63195dea1ecc4c1e91`. All **8,226** Stage 14 baseline rows retain
content hashes. All **16** isolated AI records replay without new generation. Recovery
remains off, the DAG paused and source inventory **8/14**.

The published APT 3.0.4 fix is now deployed: all 599 cases and both hosted CI jobs
passed again. All 10,807 pre-maintenance immutable rows retain content hashes;
three database backups passed restores before and after the switch.

No mandatory owned-code stage remains. Future maintenance includes
upstream image/advisory updates and any explicitly
chosen deployment expansion. The owner deferred old GitHub run #1 cleanup and
declined off-device monitoring/backups; do not treat them as blocked code work.

## Explicit remaining limits

| Boundary                      | Current state                                                                                                              | Needed for broader guarantees                                                                                                             |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Container advisories          | 130 matches across 95 source/version pairs after verified APT 3.0.4 patch | Future compatible upstream fixes; [current evidence](container-maintenance.md) |
| Total host/network loss       | Watcher runs on this Mac                                                                                                   | An independent always-on device or externally hosted watcher                                                                              |
| Disk/host loss                | Verified backups remain on this disk                                                                                       | Separately protected backup destination and transfer/restore procedure                                                                    |
| Larger/distributed deployment | Bounded snapshots and recovery inventories, growing retained history, local warehouse exclusion                            | Reviewed incremental processing/retention and cross-host fencing                                                                          |
| Public multi-user access      | Local-owner interfaces on loopback                                                                                         | Named-user authentication, authorization, tenant isolation and deployment design                                                          |
| Atomic workload publication   | Raw loading and dbt transformations use separate transactions                                                              | Reviewed publication design if atomic visibility is required; partial outcomes remain observable                                          |
| Broader AI accuracy           | Original bounded evaluation and three-class synthetic expansion passed; broader real-world coverage remains limited                                                                        | Representative incident-class evaluation before stronger accuracy claims                                                                  |

These limits remain open; no external account, public endpoint, backup upload, unverified dependency switch or automatic recovery was introduced to hide them.

The follow-up preceding Stage 12 rechecked the official image manifest and advisory sources: 130 matches remain and the official ARM64 image is unchanged. No external backup volume is mounted. The reproduced code defects are closed in the preceding audit; the external-resource limits and optional deployment designs above are not represented as fixed. Stage 14 is now an explicit final gate rather than being implied by Stage 13.
