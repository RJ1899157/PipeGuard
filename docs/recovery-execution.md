# Manual recovery dispatch and reconciliation

Checkpoint: 2026-11-03. Stage 11 now includes a separate executable policy, immutable approvals/cancellation, durable dispatch intent and exact-run reconciliation through a **local operator CLI and supervised dashboard/API flow**. Execution remains disabled. The dashboard separates review-only proposals from executable actions, with distinct approval and start confirmations. Stage 11's controlled live recovery acceptance remains pending.

## Supported action

Policy `recovery_execute_v1` supports one new run of the explicitly configured local `pipeguard_orders` DAG and `build_orders` task. The endpoint is fixed to `http://127.0.0.1:8080`. No browser/model/user argument can provide an endpoint, DAG, task, command, SQL, schedule change or arbitrary run configuration.

A fresh executable proposal has a five-minute expiry, immutable evidence-bundle reference/hash, deterministic evidence fingerprint, exact request body and warehouse-impact statement. It lives in `recovery_actions`, separately from `recovery_proposals`. Old `recovery_review_v1` approvals cannot be converted or reused.

The prospective Airflow run ID is `pipeguard-execution-` followed by the new action UUID's hexadecimal form. Its configuration contains only the fixed policy and action UUID. Independent monitoring derives its ordinary execution ID from that DAG/run/task identity, preserving the original failed run and attempts. The worker never edits an original run, attempt or incident, and never fabricates a successful monitoring outcome.

## Permission and configuration boundary

The CLI is an interface for this trusted local owner, using an owner-private configuration file. It is not a public multi-user API or an alternative GitHub identity. Operator records use `local_administrator`; Airflow records its dedicated `pipeguard_recovery` service identity; Git commits remain attributable only to RJ1899157.

After migrations and runtime grants, prepare the private worker configuration:

```sh
uv run --locked --env-file .env python scripts/configure_recovery.py
```

This creates ignored, mode-0600 `.env.recovery` with only the restricted PipeGuard runtime database URL, exact job binding, dedicated Airflow username/password and disabled worker switch. No root database password, administrator bearer token, Airflow signing key or Groq key is copied. Reconfiguration resets execution to disabled.

Two distinct process switches default to `0`:

| Private configuration | Switch                                 | Purpose                                                                                                  |
| --------------------- | -------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `.env.recovery`       | `PIPEGUARD_RECOVERY_EXECUTION_ENABLED` | Admit fresh executable proposals, approval and dispatch only when the literal value is `1`               |
| `.env.airflow`        | `PIPEGUARD_AIRFLOW_RECOVERY_ENABLED`   | Admit the dedicated account's narrowly scoped run-creation permission only when the literal value is `1` |

Neither switch is human approval. Airflow must restart to load a server environment change. Neither switch unpauses a DAG. They remain disabled until a deliberate live scenario is approved and its effects reviewed. Inspection, reconciliation, rejection and cancellation remain available with the worker switch disabled. Replaying a previously committed operation also does not require renewing authority or expiry.

## Operator workflow

The commands below are templates, not an instruction to enable execution or unpause the current DAG. Each mutation requires a caller-chosen UUID replay key. Retain the exact action ID, hash and request key printed/used for the operation. Never replace an uncertain dispatch with another action.

```sh
uv run --locked --env-file .env.recovery python scripts/run_recovery.py propose \
  --incident INCIDENT_UUID --key PROPOSAL_REQUEST_UUID

uv run --locked --env-file .env.recovery python scripts/run_recovery.py inspect \
  --action ACTION_UUID

uv run --locked --env-file .env.recovery python scripts/run_recovery.py decide \
  --action ACTION_UUID --key APPROVAL_REQUEST_UUID --hash EXACT_PROPOSAL_SHA256 \
  --decision approve --confirmed

uv run --locked --env-file .env.recovery python scripts/run_recovery.py dispatch \
  --action ACTION_UUID --key DISPATCH_REQUEST_UUID --hash EXACT_PROPOSAL_SHA256 --confirmed

uv run --locked --env-file .env.recovery python scripts/run_recovery.py reconcile \
  --dispatch DISPATCH_UUID --key RECONCILIATION_REQUEST_UUID
```

Inspect the exact payload, target, expiry, evidence identity and warehouse impact before approving. Approval does not start a run. Dispatch is a second explicit command bound to the same proposal/hash. `--confirmed` is literal deliberate confirmation of those effects; an AI investigation or review-only approval does not supply it.

Use `decide --decision reject` to reject a proposal, or `decide --decision cancel` to withdraw it before a dispatch intent exists, with the same explicit hash/confirmation arguments. A cancellation is a separate immutable event and may follow approval. Once intent exists, cancellation is refused: the worker cannot assert that an external run stopped or never started.

## Admission and dispatch ordering

1. Revalidate the executable proposal's hash/policy, exact target, expiry, current failure/attempt, unprocessed receipts, evidence fingerprint/bundle and monitoring/source freshness. The independent Airflow failure must include a native run ID whose DAG/run/task hash matches PipeGuard's failed execution identity.
2. Require a matching executable approval and no cancellation. Refuse another reserved action for the same failed run, including an earlier rejection. Refuse unresolved dispatches for the same job.
3. Read Airflow health, exact DAG configuration and a complete bounded run inventory. Require an unpaused, importable DAG, the matching failed source run and no running/queued/unknown executions. Authentication happens here, before durable intent.
4. Revalidate local evidence and commit the immutable dispatch intent, including the exact normalized body/hash, approval, failed run and deterministic external identity.
5. Repeat source preflight and local expiry/evidence checks immediately before the business POST. If these checks refuse execution, append a rejection without sending it.
6. Send **one** start request, with no mutation retry, token refresh, redirect or proxy. Save a bounded allowlisted outcome. A lost response, provider error, interruption or failure to save the outcome leaves the existing intent uncertain.

A shared session advisory lock serializes executable mutations across commands. No SQL transaction spans the external request. If the process or database connection dies, the committed intent and database uniqueness constraints still prevent later commands from sending another POST for that action or failed run. Commands encountering an existing intent return it even after expiry, with a different replay key, or while disabled.

These checks are point-in-time checks, not distributed fencing of Airflow or every ingestion writer. Another trusted administrator or scheduler can change source state after preflight. A database lock does not create an atomic transaction across PostgreSQL and Airflow, and no exactly-once guarantee is claimed.

## Uncertainty and retained outcomes

HTTP 400/401/403/404/422 from the business POST are recorded as explicit source rejection. HTTP 409, throttling, redirects, server errors and transport/response failures remain uncertain. A conflict response alone is not proof that the expected run exists.

Reconciliation only reads the exact deterministic run ID. It requires matching DAG/run ID, fixed configuration marker, manual REST-API origin, dedicated triggering identity and null logical date. Different ownership becomes a conflict; missing or unavailable reads remain unknown. **A 404 lookup never permits resubmission**: the original request might still be in flight or visibility might be delayed.

Each observation is appended with a sequence, source, safe code and bounded facts. Raw provider notes, configuration, error bodies, headers and credentials are not retained or displayed. Success cannot erase a prior failure. Contradictory terminal reports or a regression from terminal to active state become a sticky conflict. `state` shows the latest observation; `last_known_state` separately preserves the latest non-unknown status. Earlier observations always remain in history.

Unknown/conflicting outcomes block another action for that job. There is no automatic reset, retry, cancellation after dispatch or operator override in this version. One reservation per failed run is deliberately conservative, even if the source explicitly rejected the POST.

## Storage, limits and current acceptance

Migration `b7c903f4a821` adds `recovery_actions`, `recovery_action_decisions`, `recovery_dispatches` and `recovery_dispatch_events`. Runtime access is SELECT/INSERT; UPDATE/DELETE/TRUNCATE are protected by immutable-history triggers. Database owners can change protections; this is not tamper-proof evidence.

Payloads are limited to 16 KiB and event facts to 2 KiB. Each dispatch retains at most 100 observations; admission/history/source inventories fail closed at their documented 100-record bounds. Transport responses are bounded to 2 MB with five-second socket timeouts. A separate supervisor gives the complete CLI command 45 seconds, then terminates its owned child group with up to five seconds for cleanup before escalation. This also covers trickling responses that evade socket-inactivity timeouts. A timeout may follow an externally accepted request: inspect and reconcile its durable intent instead of resubmitting. There is no background auto-executor or reconciliation daemon; an unattended stop remains visibly uncertain until an operator reconciles it. Same-host loss remains undetectable from the failed host itself.

The isolated checks cover replay, expiry/staleness, review-policy exclusion, unapproved/rejected/cancelled actions, concurrent commands, different proposals for one failed run, preflight changes, SQL immutability, source response/identity failures, lost replies and simulated database failures. Real child processes are terminated with SIGKILL after intent and SIGTERM after a **synthetic** external-request marker; these tests never start Airflow and are not a host-power-loss experiment. The full regression and live disabled checks are recorded in the [execution checkpoint](recovery-execution-verification.md).

The [controlled live scenario](recovery-live-scenario.md) is prepared but not executed. Remaining acceptance: a deliberately approved live failure → fresh executable proposal → approval → new run → independent monitored outcome chain; actual API duplicate-ID/visibility checks. The executable dashboard flow is now verified against a disposable source in the [dashboard checkpoint](recovery-dashboard-verification.md). Existing review controls remain unchanged. Until that work passes, Stage 11 stays in progress and both switches stay off.

References: [Airflow 3.3.2 public API authentication](https://airflow.apache.org/docs/apache-airflow/3.3.2/security/api.html), [PostgreSQL session advisory locks](https://www.postgresql.org/docs/17/explicit-locking.html#ADVISORY-LOCKS), [scoped Airflow authorization](recovery-airflow-authorization.md), [recovery design](recovery-design.md).

## Scoped dashboard and HTTP interface

The incident inspector has a separate **Executable recovery** section. Approval and starting a run require separate checkboxes bound to the exact proposal ID and hash. Rejection/cancellation are retained; cancellation cannot withdraw an existing dispatch intent. Pages contain at most five proposals, with expandable payload inspection and retained external observations. Refresh is explicit.

Authenticated routes use the incident's integration scope; mutations require the administrator credential. Executable action IDs are checked against that incident before starting a worker. Reconciliation resolves the dispatch from the scoped action, never from a browser-selected external run ID.

| Method | Route suffix under `/v1/incidents/{incident_id}` | Purpose |
| --- | --- | --- |
| GET | `/recovery-actions` | History, worker availability, disabled state and eligibility; `limit` 1–5 and optional `before` action UUID |
| POST | `/recovery-actions` | Propose with a UUID `request_key` |
| POST | `/recovery-actions/{action_id}/decisions` | `approve`, `reject` or `cancel`; request key, exact hash and literal `confirmed: true` |
| POST | `/recovery-actions/{action_id}/dispatch` | Separate start request; request key, exact hash and literal `confirmed: true` |
| POST | `/recovery-actions/{action_id}/reconcile` | Read the exact known external run; request key only |

The API invokes only fixed CLI commands and validated arguments. The bridge checks that `.env.recovery` is an owner-private regular file, passes a minimal environment without API/Groq/owner-database credentials, and starts the worker offline without dependency synchronization. The API does not read the Airflow credentials into its own process. The existing worker supervisor remains responsible for its 45-second command deadline; the outer bridge bounds its wait and terminates its owned process group. `status` reads only the worker execution switch after restricted database validation; it makes no Airflow request. An unavailable worker leaves stored history readable and disables mutation controls.

The browser accesses a same-origin local broker with fixed upstream paths and a server-only administrator credential. Mutation bodies are bounded to 2 KiB; responses to 2 MiB. It rejects unrecognized fields, cross-origin requests and arbitrary targets. An unresolved request is saved in session storage before submission and is never automatically retried. The operator can retry that exact saved request. Retrying a saved start **may start the first run if the original request never reached the worker**; it is not a read-only check. If intent already exists, replay returns that intent without another source POST. Checking external outcome is a separate operation. Session storage belongs to one browser session and is not the authoritative audit record; the database retains intent even if browser storage is lost.
