# Live human-authorized recovery acceptance

Date: 2026-11-03. **Stage 11's initial bounded local recovery slice passes acceptance.** The approved sample run completed through the actual Airflow API and scheduler, independently observed by PipeGuard. Both execution switches are now **0**, and the daily DAG is **paused**. This is not a production-readiness or exactly-once guarantee.

## Authorization and exact identities

The user approved the terminal-failure phase, then explicitly authorized preparing an executable proposal. After seeing its exact identity, hash, warehouse impact and expiry, the user delegated the approve/reject choice. The operator recorded approval only after validation. A separate user response, **“Start and verify this run,”** authorized dispatch and verification. Neither a Groq finding nor a review-only approval authorized this run.

| Record | Identity |
| --- | --- |
| Original failed source run | `stage11-terminal-ace60424741f4d5c98f6d8af6e4941ba` |
| Original failure incident | `b222d353-13e3-4129-8712-0c7300e0d1cd` |
| Executable action | `4c10493e-e9b3-4d94-92ca-662a06718ce1` |
| Exact proposal SHA-256 | `640ada4dbdf2b19a04719eaf0d13e1c525217ac4df0f2f554318a4b28913bbbc` |
| Approval | `53b97fe2-36e1-4f1b-8b0c-2481d3b2cdd5` |
| Durable dispatch | `55cc31c5-56f1-47a4-b226-6c13f2e84dd4` |
| New native run | `pipeguard-execution-4c10493ee9b34d9492ca662a06718ce1` |
| New PipeGuard run | `3c89bf28-138d-4178-9536-3ff48ed34826` |

Proposal creation: 13:44:18 UTC; approval: 13:46:15 UTC; first dispatch observation: 13:47:24 UTC. Expiry was 13:49:18 UTC. Approval and dispatch occurred within the original five-minute window; no expiry was extended. The source run started at 13:47:25.768895 UTC and finished successfully at 13:47:35.334557 UTC.

## End-to-end results

| Check | Result |
| --- | --- |
| Approval separation | One proposal and approval; zero dispatches and still seven native runs before the explicit start |
| Actual identity | Fixed body/configuration, `logical_date: null`, manual run type, `rest_api` trigger and dedicated `pipeguard_recovery` source user verified |
| Durable dispatch | One intent; queued response then successful exact-run lookup retained as two immutable observations |
| Independent execution monitoring | New run `succeeded`, one successful attempt, no reconciliation conflict; independent read-only source observation agrees |
| Quality | One complete report with **14 checks, all passing** |
| Lineage | **8 complete lineage events / 16 dataset mentions** for the new run |
| Original failure | Old run still `failed`; both attempts still `failed/source_unavailable`; original incident remains open |
| Saved dispatch replay | Exact saved request returned the same intent; no extra intent or native run |
| Real duplicate-ID behavior | One separately authorized diagnostic POST of the identical native body returned **409**; source inventory unchanged |
| Capability revocation | After disabling/restarting, the same fixed-body source write was denied with **403**; no new run |
| Total source inventory | **8 native runs / 14 native attempt snapshots**; all seven prior native identities/states/start/end times preserved |
| Historical evidence | All **5,914** previously captured immutable row IDs and database-native hashes unchanged; later monitoring receipts may be added |
| Final ledger | **1 action / 1 approval / 1 dispatch / 2 observations** |
| Hosted AI | Still **16 requests / 16 outcomes**; no Groq generation or paid service used |

The worker sent one business start request. The diagnostic 409 and disabled-permission 403 probes were separate explicit verification calls with the same known native identity; they were not worker retries. The historical failure was not converted into success. The new run completed ordinary sample warehouse loading/dbt work; its execution and quality outcomes were verified separately.

## Restoration and retained evidence

The DAG was paused before revoking both capabilities. Airflow restarted with `PIPEGUARD_AIRFLOW_RECOVERY_ENABLED=0` and `PIPEGUARD_AIRFLOW_MANUAL_ONLY=0`; the worker file has `PIPEGUARD_RECOVERY_EXECUTION_ENABLED=0`. The public API confirms the daily timetable, paused state, healthy components and no import errors. API readiness and dashboard return 200. The expired proposal still displays its successful dispatch history; expiry does not erase completed work or prevent inspection.

Fresh post-acceptance backups of PipeGuard, Airflow and the selected sample-warehouse schemas were restored in disposable databases and passed schema/row fingerprint checks. No live database was replaced. Private manifests remain in ignored local storage; these backups remain on this disk and do not cover whole-host loss.

[Dashboard evidence: successful dispatch retained with execution disabled](audit/recovery-live-success.png). The [failure checkpoint](recovery-phase1-verification.md) retains the two failed attempts and the source/producer timing repair.

No application code, dependency or schema changed in this acceptance step, so automated suites were not repeated here. The preceding implementation checkpoint passed **419 backend tests**; the earlier dashboard checkpoint passed **39 frontend tests**, TypeScript checks and production build. These historical counts are distinct from the actual live acceptance checks above.

## Scope and next stage

The bounded fixed-action local Stage 11 acceptance is complete. Stage 12 covers integrated delivery/CI and clean-environment procedures; Stage 13 covers the final security, measured performance and debugging review. Recovery remains manual and disabled by default. Existing trusted-local-owner, bounded-history, cross-system race, same-host outage and off-host-backup limits remain. No broad action catalog, unattended recovery or production guarantee is implied.
