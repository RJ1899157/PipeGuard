# Next-session checkpoint

**Superseded:** [2026-11-02 investigation checkpoint](investigation-verification.md). Stage 10 now includes durable API/dashboard investigations and a passing bounded [evaluation gate](investigation-evaluation.md). GPT-OSS 120B replaces Qwen. The historical pre-break snapshot below is retained for context; the [Stage 11 review milestone](recovery-verification.md) now includes durable proposals and explicit review decisions. The [Airflow authorization prerequisite](recovery-airflow-authorization.md) is now verified with execution disabled. The [2026-11-03 executable CLI checkpoint](recovery-execution-verification.md) now includes separate executable approvals, durable intent and reconciliation; the [executable dashboard checkpoint](recovery-dashboard-verification.md) adds scoped HTTP controls, separate approval/start confirmations and uncertain-response replay. Controlled live recovery acceptance remains pending.

Saved on 2026-11-01 (Asia/Kolkata), after the pre-investigation hardening audit.

## Verified before the break

- API liveness, authenticated readiness and dashboard returned HTTP 200. The independent user watcher was running and reported API/database healthy and monitor fresh.
- Fresh logical backups of PipeGuard, Airflow and the sample warehouse were created and restore-verified in disposable databases. Schema and data checks passed; no live database was replaced and no restore-check databases remained. Private backup identifiers and manifests stay under ignored `data/local/backups/`.
- The official `postgres:17` registry digest still matched the pinned image. All 116 recorded Debian advisory matches were rechecked against the primary trixie tracker: no release-record changes or newly published fixed-version candidates.
- The previous implementation checkpoint passed 342 automated tests plus build, browser and runtime checks. This final pass changed documentation only; it did not rerun those suites or introduce a new implementation.

## Remaining requirements and dependencies

| Requirement                          | Current boundary                                                          | What is needed                                                                                                          |
| ------------------------------------ | ------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Unfixed container library advisories | Current official PostgreSQL 17 image; unresolved upstream issues remain   | Published compatible fixes, followed by image review and regression/restore checks; see [triage](container-security.md) |
| Detect this Mac losing power         | The watcher runs on this Mac                                              | An independent always-on device or externally hosted watcher                                                            |
| Survive loss of this disk/host       | Verified backups are private but on the same disk                         | A separately protected backup destination and reviewed transfer/restore procedure                                       |
| Larger or distributed deployment     | Bounded snapshots, growing retained history and local warehouse exclusion | Reviewed incremental processing/retention and cross-host fencing; no evidence deletion or unsafe lock removal           |
| Public multi-user access             | Services remain local-owner interfaces bound to loopback                  | Separate authentication, authorization, tenant isolation and deployment design before exposing them                     |
| Atomic workload publication          | Raw loading and dbt transformations use separate transactions             | A reviewed publication design if atomic visibility becomes a requirement; partial outcomes remain observable            |

These requirements are not marked complete. No external account, public endpoint, backup upload, dependency-base switch or automatic recovery was introduced to work around them.

## Resume

1. Confirm Docker and the local services are available using the existing [setup guide](development/setup.md) and [resilience procedures](local-resilience.md). Service availability after sleep, reboot or a closed development session must be checked again.
2. Keep the sample DAG paused until a deliberate scenario requires a run.
3. Keep `PIPEGUARD_AIRFLOW_RECOVERY_ENABLED=0`. The dedicated scoped account is verified; its capability switch is not human approval. Existing `recovery_review_v1` approvals remain non-executable.
4. Keep `PIPEGUARD_RECOVERY_EXECUTION_ENABLED=0` in `.env.recovery`. The manual executable policy and fault checks are implemented. Next review a concrete live scenario, including the daily schedule on unpause, then verify actual conflict semantics and the independently monitored recovery chain. Executable dashboard controls are verified against a disposable fake source; their live acceptance remains pending. AI findings must never authorize an action.

Stage 10's bounded advisory gate passes, Stage 11 is in progress, and Stages 12–13 remain planned in the [roadmap](roadmap.md). The next session does not require repeating the completed audit from scratch; recheck runtime state and any upstream changes first.
