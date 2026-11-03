# Stage 11: human-approved recovery design

Status: Stage 11's first review-only milestone is implemented: durable proposals and human decisions, scoped APIs and deterministic freshness checks. The [operating guide](recovery-operations.md) defines the current boundary. Review approvals cannot execute actions or become executable approvals under a future policy. The dedicated Airflow recovery identity and disabled-by-default scoped authorization are now [verified](recovery-airflow-authorization.md). A separate [manual CLI worker](recovery-execution.md) now implements executable approvals, durable dispatch intent and reconciliation with both capability switches disabled. A [scoped HTTP/dashboard flow](recovery-dashboard-verification.md) now invokes this supervised worker with distinct approval/start confirmations. [Controlled live recovery acceptance](recovery-live-verification.md) now passes for this fixed local action; both switches were disabled again afterward. The investigation gate is evaluated separately; an AI finding is never an authorization.

## First action and boundary

Start with one explicitly configured action: request a **new run of the local sample orders DAG**. Do not clear tasks, overwrite earlier attempts, edit DAGs, run arbitrary commands, execute generated SQL, change credentials or unpause schedules implicitly. The new run must have a deterministic external correlation key and appear in monitoring as a separate execution. Its success cannot remove the earlier failure or its incident history.

Require an explicit application configuration binding from the monitored job to the existing local Airflow connection and exact `pipeguard_orders` DAG. Job names, model text and browser parameters cannot select an endpoint or DAG. A paused DAG needs a separate reviewed decision: the recovery worker must not silently change its scheduling state.

## Durable proposal

Persist an immutable proposal containing:

- Incident/job/integration identity, fixed action/version, creation time and short expiry.
- Fresh evidence bundle ID/hash, latest incident-history watermark and the expected failed execution/attempt state.
- Exact normalized action parameters, payload hash, preconditions and proposer identity.
- A human-readable impact statement: a new sample run may change the local sample warehouse. No claim of atomic rollback; partial transformation outcomes remain observable.

Proposal creation must run deterministic eligibility checks. Block resolved incidents, unsupported conditions, unknown or running attempts, contradictory execution reports, incomplete source coverage, truncated evidence, unavailable monitoring, unconfigured target mapping and unhealthy dependencies. Lineage/quality gaps require investigation; they do not automatically justify rerunning a pipeline.

## Approval and freshness

Approvals are immutable events bound to a proposal ID **and its exact hash**, authenticated administrator identity and expiry. Acknowledging an incident, checking the AI evidence-consent box or approving a different proposal does not approve this action. The UI must show the target, effect and evidence age before a deliberate confirmation.

Revalidate at approval **and immediately before execution**: proposal not expired, incident still eligible, history/evidence watermark unchanged, target mapping unchanged, dependencies healthy, no competing in-flight run, and the approved parameters/hash identical. Reject stale approvals rather than regenerating proposals or silently extending their expiry.

## Dispatch, failures and interruption

Reserve one execution with a database uniqueness constraint and shared lock before sending a request. Commit that dispatch intent before contacting Airflow. Use the proposal's deterministic Airflow run ID so reconciliation can search for that exact execution after a lost response. Disable transport retries and redirects for the mutating request.

Record dispatch accepted, explicitly rejected or **unknown**. A timeout/process stop is unknown until independent reconciliation finds the exact run or a trustworthy terminal rejection. An absent response is never permission to send a second action. A database lock alone does not provide exactly-once execution across systems; the external deterministic ID and reconciliation are required, and their Airflow API behavior must be verified before enabling dispatch.

Keep proposal, approval, intent, response and reconciliation history append-only. Monitoring independently records the new run and all its attempts; the recovery worker cannot mark the original incident resolved. Cancellation before dispatch is a separate immutable event; cancellation after dispatch cannot imply the external run stopped.

## Implementation order and acceptance

1. Proposal/approval schema, restricted database permissions and immutable audit records.
2. Scoped read APIs, administrator-only proposal/approval APIs, bounded inputs and explicit UI confirmation. Keep dispatch disabled.
3. Stale/expired/unauthorized/hash-mismatch/duplicate/concurrent proposal and approval checks in isolated schemas.
4. Verify the installed Airflow API's exact-run lookup, deterministic ID conflicts, paused-DAG behavior and failure responses against official documentation and the local instance.
5. Add an opt-in worker with the fixed action allowlist and a disabled-by-default execution flag. Verify interruption before/after dispatch, lost replies, duplicate scheduling, database/provider outages and reconciliation.
6. Deliberately approve one synthetic scenario and verify its complete incident → proposal → approval → new run → monitored outcome chain before enabling broader actions.

These checks pass for the bounded local slice described in the live acceptance report. Existing host-loss/off-host-backup and trusted-local-owner limitations still apply.
