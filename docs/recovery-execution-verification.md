# Executable recovery checkpoint

**Subsequent checkpoint:** [Controlled live recovery acceptance](recovery-live-verification.md) is now verified. The results and authorization boundaries below describe this earlier checkpoint or procedure.

Date: 2026-11-03. **CLI implementation milestone; live recovery acceptance pending.** Execution remains disabled in both the worker and Airflow. The current DAG remains paused. No live proposal, approval or dispatch was created for this milestone.

## Delivered

- Separate `recovery_execute_v1` proposal/approval storage. Review-only decisions cannot supply executable authority.
- Explicit hash-bound approval, rejection and cancellation before intent; five-minute expiry, fixed sample target, fresh evidence and independent source identity checks.
- Committed dispatch intent before the business POST, unique reservation per action/approval/failed run/external identity, shared cross-command lock and no mutation retries.
- Independent exact-run reconciliation with immutable observations, uncertain not-found results, ownership validation and retained contradictory outcomes.
- Owner-private, disabled worker configuration and a manual CLI. A 45-second supervising process bounds commands, with termination/escalation of its owned child group.

See [operating instructions and limits](recovery-execution.md) for the exact commands, two capability switches and conservative reservation semantics. The executable workflow is CLI-only. The dashboard and HTTP recovery API remain review-only.

## Verification

| Area                      | Result                                                                                                                                                                                                          |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Backend regression        | **403 passed**, including 24 executable-recovery tests, 37 transport tests and 10 operational-file tests; one existing upstream Starlette/HTTPX deprecation warning                                             |
| Airflow authorization     | **9 passed** in the existing Airflow environment, including its 1,680-case DAG permission matrix                                                                                                                |
| Real process interruption | SIGKILL after committed intent and SIGTERM after a synthetic external-request marker leave uncertain intent; replay sends no new request                                                                        |
| Concurrency and failures  | Concurrent dispatch refused; different proposals cannot repeat a failed-run action; lost replies, absent lookup, database outcome failure, expiry/stale state and preflight changes covered in isolated schemas |
| Ledger integrity          | Runtime SELECT/INSERT only; owner-level UPDATE/DELETE/TRUNCATE rejected by immutable-history triggers; hashes/approval bindings checked before dispatch and reconciliation                                      |
| Migrations                | Head `b7c903f4a821`; no metadata drift; disposable migration roundtrip and protected downgrade pass                                                                                                             |
| Live disabled worker      | CLI proposal creation refuses with `recovery_execution_disabled`; both capability switches are `0`; worker file is mode 0600                                                                                    |
| Live source adapter       | Dedicated account authenticates; paused DAG blocks preflight; exact absent-run lookup returns unknown; observed transport calls contain no business POST                                                        |
| Preservation              | All **5,716** captured immutable-row IDs and database-native hashes preserved; mutable receipt processing fields excluded; later monitoring receipts may be added                                               |
| Existing workload         | Same **6 Airflow run identities/states/start/end timestamps**, **11 attempt snapshots**, DAG paused; worker makes no original run/attempt/incident updates                                                      |
| Live action records       | `recovery_actions`, `recovery_action_decisions`, `recovery_dispatches`, `recovery_dispatch_events` each contain **0** records                                                                                   |
| Hosted investigation      | Existing **16 requests / 16 outcomes**; no Groq generation or paid service requested                                                                                                                            |
| Services and backups      | API liveness/readiness and dashboard return 200; monitor restarted; pre-migration and final post-migration PipeGuard backups restore-verified in new disposable databases                                       |

No dependency, browser asset, sample workload or Airflow DAG changed. Frontend visual checks and sample dbt execution were not repeated for this backend/CLI milestone. No claim is made that these isolated tests reproduce every power-loss, distributed race or real-provider failure.

## Issues found and corrected during verification

The initial full run exposed intermittent failures in older review fixtures: host timestamps could be a few milliseconds ahead of Docker's PostgreSQL clock. Fresh fixture heartbeats and complete scan times now use the same database clock as admission. Production freshness and future-time checks were not relaxed. The corrected full suite passes.

The first post-migration restore check found a textual cast-distribution difference in the new partial unique index's equivalent `IN` predicate. The row comparison passed; the strict schema comparison refused the mismatch. The index now uses the simpler `decision <> 'cancel'` condition, equivalent under the three-value decision constraint. The live empty index was replaced transactionally to match the unreleased migration; no records were removed. A fresh final backup passes the unchanged strict schema/row checks. Private files retain the earlier unverified archive and cleaned attempt; no live database was restored or replaced.

## Remaining Stage 11 work

1. Review a controlled live fault scenario, including the scheduling effects of unpausing the daily DAG, before enabling either switch or changing its schedule.
2. Verify actual Airflow deterministic-ID conflict/visibility behavior and a deliberately approved failure → executable proposal → approval → new run → independently monitored outcome chain. Keep the earlier failure and every attempt visible.
3. **Completed in the subsequent [dashboard checkpoint](recovery-dashboard-verification.md):** executable approval/dispatch/history controls and uncertain-response replay verified with a disposable source. The original test totals above describe the CLI checkpoint.

The host-loss/off-host-backup, trusted-local-owner, bounded-history and cross-system timing limits remain. The current implementation provides durable uncertainty and prevents its own repeat dispatch; it does not establish exactly-once external execution or complete Stage 11 acceptance.
