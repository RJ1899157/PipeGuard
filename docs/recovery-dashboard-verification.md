# Executable recovery dashboard checkpoint

**Subsequent checkpoint:** [Controlled live recovery acceptance](recovery-live-verification.md) is now verified. The results and authorization boundaries below describe this earlier checkpoint or procedure.

Date: 2026-11-03. Stage 11 remains in progress. The CLI's separate executable policy now has scoped HTTP routes and an incident-dashboard flow through a supervised worker. Both execution switches remain **0**, and `pipeguard_orders` remains **paused**. No real recovery run was started for this milestone.

## Delivered

- Separate review-only and executable sections; existing review approvals cannot authorize execution.
- Exact proposal/evidence inspection; separate approval and start confirmations; immutable rejection/cancellation and dispatch observations.
- Five-proposal keyset pages, compact expandable records, explicit refresh and unavailable-worker states.
- Saved exact pending requests, deliberate replay and separate exact-run reconciliation. Uncertain replies never trigger automatic execution retries.
- Fixed local broker paths and supervised worker commands. Airflow credentials stay in the separately configured worker; the API does not load them. See the [operating contract](recovery-execution.md#scoped-dashboard-and-http-interface).
- Corrected list freshness text to reflect the active incident or pipeline list instead of another list's fetch status. Fetch time remains distinct from monitoring freshness.

## Verification evidence

| Area | Result |
| --- | --- |
| Backend | **415 tests passed**, including 12 new scoped HTTP/bridge cases; one existing Starlette/HTTPX deprecation warning |
| Frontend | **39 tests passed**, including strict executable-request paths, field validation and uncertain-request retention |
| Build | Production build and TypeScript unused-local/parameter checks passed |
| HTTP | Live worker reports disabled; scoped history readable; fresh live proposal rejected with 409; unauthenticated history 401; nonexistent incident 404; runtime OpenAPI equals committed contract |
| Browser broker | Rejected cross-origin/cross-site/missing-origin/wrong-content-type requests (403), invalid IDs/unrecognized fields/oversized bodies (400), wrong method (405) and rebound Host (403) |
| Browser interaction | Keyboard approval without start, separate start confirmation, lost response, saved-request replay after reload, reconciliation, rejection, cancellation and both pagination directions verified with a disposable fake source |
| Layout | Desktop 1440 × 1100, tablet 768 × 1024 and mobile 390 × 844 checked; no horizontal overflow at tablet/mobile, including expanded proposal JSON |
| Live preservation | All **5,914** captured immutable row IDs and database-native hashes retained; mutable event-processing fields excluded; later monitor receipts may be added |
| Actual Airflow | Same **6 run identities/states/start/end timestamps** and **11 attempt snapshots**; DAG remains paused |
| Live action tables | Actions, decisions, dispatches and dispatch events each remain **0** |
| Hosted AI | Existing **16 requests / 16 outcomes**; no Groq generation requested |
| Cleanup and services | Disposable browser schema removed; original API restored; authenticated readiness, liveness and dashboard return 200 |

### Lost-response experiment

The browser used an isolated PostgreSQL schema and a fake source. A one-shot fault replaced the successful dispatch HTTP response with a 503 **after** durable intent and the uncertain observation were saved. Refresh and page reload retained the exact pending request. Explicit replay returned the same intent without another source start. A later exact-run lookup appended success while preserving the original uncertainty.

Final disposable counts: **8 proposals, 3 decisions, 1 dispatch intent, 2 observations, 1 original failed run, 1 simulated start and 1 simulated lookup**. Approval alone had zero starts. The simulated successful external outcome did not alter the original failed run. These checks exercised the real dashboard, broker, scoped API and execution service, with the worker/source replaced inside the disposable fixture; they do not prove real Airflow execution acceptance.

## Screenshots

The desktop and mobile interaction screenshots show explicitly labeled synthetic disposable data. The live screenshot shows the restored real incident inspector with execution disabled.

- [Disposable desktop interactions](audit/execution-dashboard-desktop.png)
- [Disposable mobile payload inspector](audit/execution-dashboard-mobile.png)
- [Live disabled execution state](audit/execution-dashboard-live.png)

## Remaining acceptance

Review a concrete controlled live scenario before enabling either capability switch or unpausing the daily DAG. Account for its schedule on unpause. Verify real deterministic-run-ID conflict/visibility behavior and the full failure → fresh proposal → approval → new run → independently monitored outcome chain. Preserve the original failure and all attempts. AI output is never authorization.

No migration, dependency installation or live evidence deletion was needed. This checkpoint does not repeat backup restoration or claim exhaustive distributed-failure coverage. Existing trusted-local-owner, same-host outage, off-host backup, bounded history and cross-system race limitations remain as documented in the [execution guide](recovery-execution.md) and [previous CLI checkpoint](recovery-execution-verification.md).
