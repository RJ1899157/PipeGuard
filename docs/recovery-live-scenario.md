# Controlled live recovery scenario

**Subsequent checkpoint:** [Controlled live recovery acceptance](recovery-live-verification.md) is now verified. The results and authorization boundaries below describe this earlier checkpoint or procedure.

Prepared: 2026-11-03. **Phase 1 approved and completed; recovery execution remains unauthorized.** See the [live failure checkpoint](recovery-phase1-verification.md). This is the remaining Stage 11 acceptance procedure, following the [dashboard checkpoint](recovery-dashboard-verification.md). Local sample data only; no hosted AI calls or paid services are needed.

## Scope and approval points

The demonstration will ultimately contain two distinct runs of `pipeguard_orders/build_orders`:

1. A deliberately failed run with `simulate_terminal_failure: true`. Both its initial attempt and its one native retry fail with the explicit synthetic category `source_unavailable`, before source loading or dbt work. It is a controlled fault, not evidence of a real upstream outage.
2. One separately proposed and approved recovery run, using the existing fixed `recovery_execute_v1` body. The fault parameter is absent and defaults to false. This run performs the ordinary sample load, transformations and quality checks, and **may change the local sample warehouse**.

**First approval:** authorize manual scheduling, temporary unpause and the single terminal-failure run. Both recovery switches remain off during this phase. The exact unique failed-run identity is retained privately in `work/hardening/recovery-live-plan.json`; do not replace it after submission or resubmit an uncertain request under a new identity.

**Recovery approval:** once independent monitoring has recorded the terminal failure, present the exact fresh proposal, hash, target and warehouse impact for the user's decision. Enabling either capability switch is a separate operator action, never approval. Review-only decisions and AI findings cannot authorize execution. Starting the approved recovery remains a second explicit action. Do not generate a five-minute proposal while waiting for an unattended user response, extend its expiry or automatically approve it.

## Scheduling isolation

The usual DAG has an `@daily` schedule. `catchup=False` does not prevent an extra current scheduled run on unpause. To isolate this demonstration:

1. Confirm the DAG is paused, the six captured prior run identities/states/start/end times remain unchanged, and no queued/running run exists. Capture a fresh baseline if execution is deferred to another session.
2. With explicit scenario approval and while still paused, set `PIPEGUARD_AIRFLOW_MANUAL_ONLY=1` in the private `.env.airflow` and restart the owned Airflow launcher. This makes the parsed DAG use `schedule=None`; it does not unpause or enable recovery.
3. Wait for the public API to expose the new no-schedule timetable and false fault defaults. Require healthy scheduler/processor/database, no import errors and the same complete run inventory before unpausing. Configuration-file contents alone are not proof that serialization propagated.
4. Submit the one fixed fault run and temporarily unpause. Keep independent monitoring active. If submission loses its response, look up that exact native run ID rather than submitting another ID. Require both attempts and a terminal failed DAG run, then pause and verify before waiting for the recovery decision.
5. No unrelated queued or new scheduled run may be ignored. If the inventory differs unexpectedly, pause, preserve evidence and investigate before proceeding. Pausing does not stop an already running task.

`PIPEGUARD_AIRFLOW_MANUAL_ONLY` accepts only `0` or `1`; an invalid value refuses DAG import. It defaults to `0` (daily). The provisioning script preserves an explicitly selected mode; it does not enable recovery. Both fault parameters default to false and are JSON-Schema booleans. No fault option is added to the executable worker's fixed request body.

## Recovery acceptance

- Require the failed run's native identity, fresh complete observer scan, both failed attempts, retained incident history and immutable evidence bundle. The deterministic proposal must pass its existing eligibility checks without weakening them.
- Enable the dedicated source capability and worker capability only for the approved recovery demonstration. Restart Airflow for its source switch, then recheck health, scheduling mode, pause state, failure identity and idle run inventory before approval/dispatch. Under the explicit recovery-phase authorization, temporarily unpause the manual-only DAG so the separately started run can execute.
- Use the executable dashboard section, inspect the exact proposal/hash and obtain deliberate approval. Approval alone must create no new Airflow run. A separate explicit start must commit one intent before its one business POST.
- Verify the returned run's complete identity, fixed configuration, manual run type and dedicated recovery user using the public API. Independently observe its attempts, execution outcome, quality report and lineage/evidence delivery; worker reconciliation alone is not monitoring acceptance.
- Replay the **saved PipeGuard dispatch request** and require the same intent with no second run. Reconcile the exact external run and retain every earlier observation, including uncertainty.
- Verify the real Airflow duplicate-ID contract with one deliberately controlled diagnostic POST of the identical body after the target run is known. Expect conflict and unchanged source inventory; never treat conflict alone as evidence of success. This diagnostic is separate from the worker, which never repeats its POST. Perform it only within the approved recovery acceptance scope; stop and investigate any other response.
- Preserve the old failed run and both failed attempts. A successful **new** run must not turn the earlier failed run into success or erase its incident. Only independent observations may drive ordinary detector state changes.

## Stop and restore

On unexpected source inventory, loss of monitoring, stale evidence, expired approval, permission error or unknown response: retain the existing request/intent, pause the DAG where available and investigate. Never clear old tasks, delete history, force a success, silently replace an action or restore a backup over a live database. Reconciliation remains manual; an unresolved outcome stays visibly unresolved.

After acceptance or a stop, pause and verify the DAG; disable both recovery switches and restart the source process to revoke its capability. While paused, restore `PIPEGUARD_AIRFLOW_MANUAL_ONLY=0`, restart/reparse and verify the daily timetable without unpausing it. Check all prior run/evidence identities and retained records. Record actual results before marking Stage 11 complete.

## Preparation verified

| Check | Result on 2026-11-03 |
| --- | --- |
| Workload regression | **59 tests passed**, including both controlled terminal attempts, no work before failure and a separate successful run |
| DAG checks with pinned Airflow interpreter | **4 tests passed**: daily/default mode, manual mode/defaults, invalid-mode refusal and forwarding all four fault-flag combinations without executing subprocesses |
| Scoped Airflow authorization regression | **9 tests passed**; no live permissions enabled |
| Live observer | **6 existing runs / 11 attempt snapshots**, DAG paused, daily timetable, no import errors |
| Backups | Fresh PipeGuard, Airflow and selected sample-warehouse schemas restored and schema/row fingerprints verified in disposable databases; live databases were not replaced |

The backup manifests and the scenario identity stay in ignored private local storage. Restore checks cover the selected schemas, not roles/private configuration or whole-host loss. Backups remain on this disk. No dependency installation, schema migration, source-data edit, live fault submission, unpause, recovery approval or dispatch was performed during preparation.

References: [Airflow 3.3.2 DAG scheduling](https://airflow.apache.org/docs/apache-airflow/3.3.2/core-concepts/dags.html), [Airflow 3.3.2 parameter validation](https://airflow.apache.org/docs/apache-airflow/3.3.2/core-concepts/params.html), [execution operating guide](recovery-execution.md), [resilience procedures](local-resilience.md).
