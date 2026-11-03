# Live terminal-failure checkpoint

**Subsequent checkpoint:** [Controlled live recovery acceptance](recovery-live-verification.md) is now verified. The results and authorization boundaries below describe this earlier checkpoint or procedure.

Date: 2026-11-03. The user explicitly approved **phase 1 only** of the [controlled scenario](recovery-live-scenario.md): manual scheduling, one deliberately failed run with two failed attempts, and re-pause. Recovery execution was not authorized or performed. Stage 11 remains in progress.

## Observed result

| Item | Verified result |
| --- | --- |
| Source run | `stage11-terminal-ace60424741f4d5c98f6d8af6e4941ba`, terminal `failed` |
| PipeGuard run | `8e6beca4-b671-4daf-ae9f-4d9444342654`, terminal `failed`, no reconciliation conflict |
| Execution-failure incident | `b222d353-13e3-4129-8712-0c7300e0d1cd`, open, retained history |
| Native and producer attempts | Attempt 1 and attempt 2 both failed; each retains the synthetic `source_unavailable` reason |
| Attempt 1 workload interval | 11:18:25.331230–11:18:25.582029 UTC, 251 ms |
| Attempt 2 workload interval | 11:18:33.006003–11:18:33.039430 UTC, 33 ms |
| Independent source | Read-only observer confirms terminal failure and both native attempts; **7 native runs / 13 attempt snapshots** total |
| Existing runs | All six prior native run identities, states and start/end times unchanged |
| Warehouse | Selected raw/staging/analytics schema and row fingerprints unchanged; source CSV hash unchanged |
| Evidence | All **5,914** previously captured immutable row IDs/hashes preserved; two untruncated incident evidence snapshots retained, including the snapshot before the projection repair |
| Execution ledger | Actions, decisions, dispatches and dispatch events each remain **0** |
| Hosted investigation | Still **16 requests / 16 outcomes**; no Groq generation |
| Final scheduling | Daily timetable restored and verified through public API; DAG **paused**, no import errors, source components healthy |
| Capability switches | Worker and Airflow recovery switches both remain **0** |

The task failed before source loading/dbt invocation. No quality report or complete dataset lineage was fabricated. The dashboard truthfully shows unknown quality and partial lineage. The source scheduler times remain independent observations; the intervals above are producer workload times.

## Projection race found and fixed

The independent source scan created attempt 1 before its producer start arrived. The source projection deliberately ignored a late start to avoid regressing terminal source evidence. On the producer terminal handoff, the old reducer reset scheduler timestamps but did not rebuild the already stored producer start. This left the displayed start missing even though the accepted receipt survived.

The handoff now restores validated, **processed** producer start receipts for the same integration/job/run/attempt before applying its terminal. Normal source reconciliation also repairs older producer projections with a missing start from the same retained receipts. It does not substitute scheduler times or invent boundaries. The ordinary reducer still detects conflicting producer starts, invalid intervals and terminal disagreements. Four added regression cases cover source-first queued/running/failed handoffs, repairing an older projection, and conflicting starts; the existing late-producer case now asserts its workload start.

The API and independent monitor were restarted with the fix. The next ordinary reconciliation repaired the real first attempt to its original producer start. Original receipt/observation/history/evidence records were retained. A new immutable evidence snapshot records the repaired projection; the earlier snapshot remains available.

## Verification

The final full backend regression passes **419 tests** (110.71 seconds). No frontend source, dependency, schema migration, recovery permission or recovery policy changed. The live dashboard was refreshed and both failed attempts, reasons, intervals and honest quality/lineage gaps were visually checked. See [retained attempts](audit/recovery-phase1-attempts.png).

The first full regression run exposed an older task-timeout fixture missing the newly introduced false-default terminal-fault parameter; the fixture now supplies both documented parameters. A cooldown assertion also failed in that run and passed in isolation; its cause was not established. The final full rerun passes, including the cooldown and timeout-fixture checks. The existing upstream Starlette/HTTPX deprecation warning remains.

## Next approval boundary

Phase 1 is complete. Before the recovery phase, recheck the seven-run idle baseline and source health. Obtain authorization to temporarily select manual scheduling, enable both narrowly scoped recovery capabilities, unpause and prepare the fresh proposal. Show its exact hash, target, expiry, evidence and warehouse impact for a separate human decision; starting remains a separate explicit action. No proposal has been created while waiting, so there is no unattended five-minute approval window.

Then verify the approved new run, real deterministic-ID visibility/conflict behavior, saved-request replay, independent monitoring, quality and lineage. Preserve the failed run and both attempts. Finish by disabling capabilities and restoring daily-but-paused scheduling. Do not claim Stage 11 complete before that chain passes.
