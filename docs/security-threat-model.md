# Local deployment threat model

Scope: the delivered local-owner PipeGuard deployment, including advisory AI and
disabled-by-default recovery. This is a bounded assessment, not certification or
proof that every possible attack or failure is covered.

## Assets and trust boundaries

- **Retained evidence:** execution attempts, incident transitions, quality/lineage
  observations, captured bundles and recovery/investigation ledgers. Prior failures
  must survive a successful retry or new recovery run.
- **Credentials:** provisioning/owner, restricted application, producer, observer,
  recovery, warehouse, watchdog and hosted-provider credentials have different roles.
  Private files and backups are excluded from Git and served assets.
- **Business effects:** only the workload changes its warehouse. An exact recovery
  proposal needs a decision and a separate start; AI cannot supply either authority.
- **Browser boundary:** Next.js holds the local administrator credential server-side.
  The UI is an owner interface, not a named-user login or public multi-tenant service.
- **Source/provider boundary:** producer observations and AI prose can be incomplete
  or wrong. Hashes establish retained-content integrity, not business truth.
- **Operating boundary:** localhost binding and owner-private files protect against
  unintended network exposure and other OS users. A malicious process running as
  the same Unix owner can read that owner's files and forge browser headers; this
  deployment does not claim isolation from such a process or a privileged host user.

## Threat and control review

| Threat                                                  | Implemented control                                                                                                                              | Verification and residual boundary                                                                                                                 |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Unauthorized metadata access or cross-integration reads | Bearer authentication, scoped queries, server-only broker credential, runtime privilege verification                                             | API scope/revocation/startup tests; authorized in-flight work may finish after revocation                                                          |
| Cross-site browser actions and DNS rebinding            | Loopback listeners, Host/Origin/fetch-metadata checks, no API CORS, explicit JSON mutation admission                                             | Backend and frontend boundary tests plus production HTTP smoke; native owner processes are trusted                                                 |
| Script injection through evidence or AI output          | Nonce CSP, replaced client nonce headers, React text rendering, no dynamic command/SQL generation from prose                                     | CSP/renderer and contract tests plus source review; third-party libraries and unsafe-inline positioning styles remain dependencies                 |
| Slow or oversized request bodies                        | 64 KiB API cap before copying oversized chunks, 15-second absolute read deadline, 32 concurrent body readers per worker, strict declared lengths | Direct ASGI regressions and isolated TCP checks; these do not limit connection/header establishment or all processing time                         |
| Stalled dashboard streams                               | Byte caps, five-second absolute stream-read deadline, cancellation without waiting for a broken source to acknowledge                            | UTF-8/size/stalled/trickle/cancellation tests; synchronous JSON parsing is byte-bounded, not preemptible                                           |
| Excessive graph materialization                         | At most two graph builders per worker; streamed event batches; 1,000-event, 8 MiB canonical-payload and 10,000-mention scan budgets              | Dense fixtures, payload-budget and concurrent-admission tests; `graph_limit` means partial, never complete                                         |
| SQL/command/path injection                              | Bound SQL values, quoted identifiers or fixed migration identifiers, schema/path checks, fixed subprocess argument lists and endpoint allowlists | Ingestion, operational-file, warehouse and recovery tests plus source review; privileged maintenance still requires a trusted operator             |
| Replay, ambiguous delivery or lost terminal events      | Durable receipts/outboxes, stable identities, immutable history and independent public-Airflow reconciliation                                    | Retry/replay/out-of-order/interruption tests; polling cannot invent events never received by any source                                            |
| Prompt injection or unsupported AI conclusions          | Bounded allowlisted evidence projection, citations, deterministic validation and abstention; durable request before inference                    | Offline evaluation and injection/contradiction tests; broader live incident-class accuracy is unestablished                                        |
| Provider cost or evidence disclosure                    | Manual generation through the durable incident API, operator Free-plan assertion, fixed Groq endpoints and incident concurrency/cooldown/daily caps; connectivity diagnostic is metadata GET only                                     | Mocked metadata-only/dry-run/endpoint guards; no diagnostic generation; metadata cannot verify Free billing or inference/schema behavior; local assertions cannot enforce a later paid-plan change                               |
| Unauthorized or duplicate recovery                      | Separate scoped worker/account, two switches, exact hash/expiry, separate approval/start, durable intent, no blind POST retry                    | Recovery permission matrix, supervised-process, conflict/replay and unknown-outcome tests; start still requires fresh explicit authority           |
| Credential leakage                                      | Private atomic writes, restricted subprocess environments, sanitized errors, no access logs, server-only secrets                                 | Secret scans of owned source and served assets; the trusted host owner and logical backup contents remain sensitive                                |
| Database access loss or corrupt persistence             | Restricted roles, constraints/triggers, transaction handling, query/lock timeouts, pre-ping and distinct live/ready checks                       | Disposable runtime-access outage/restoration and backup restore drills; an unresponsive host/network can still exceed server-side statement timers |
| Supply-chain compromise                                 | Frozen Python/pnpm locks, Airflow hashes, pinned container and action commits, time-specific advisory queries                                    | Python/pnpm checks and Debian/OSV image triage; absence of matches does not prove absence of vulnerabilities                                       |
| Interrupted delivery tooling                            | Fresh committed export, fresh credentials, unique temporary Compose project, owned process cleanup and nonzero failures                          | Successful local delivery and catchable SIGTERM drill; SIGKILL, Docker loss and host loss can prevent cleanup                                      |

## Deployment restrictions and unresolved risks

1. Keep PostgreSQL/API/dashboard/Airflow on loopback. Public or multi-user deployment
   needs named-user authentication, authorization, TLS, tenant isolation and a
   separate exposure review. Header checks are not a substitute for that design.
2. Keep both recovery switches at `0` and the sample DAG paused after verification.
   Never interpret a historical approval or AI hypothesis as permission for a new run.
3. The image has unresolved installed-source advisory matches. Apply a compatible
   upstream fix when available; a base-image redesign requires its own compatibility
   and restore review. Do not describe these matches as fixed or proven unreachable.
4. The watcher and backups share this Mac. Host/network/disk loss needs an independent
   watcher and separately protected backups. Additional code on the same host does
   not establish physical independence.
5. Warehouse loading and dbt use separate transactions. Partial effects are observable;
   atomic publication, direct SQL writers and cross-host fencing need separate design.
6. History grows. Per-read limits preserve bounded behavior but do not provide a
   retention policy or incremental detector. Review those before larger deployment.
7. Rate limits and body/graph caps are process-local admission controls. They are not
   a distributed DoS defense, aggregate heap quota or universal latency guarantee.

See [Stage 13 verification](stage13-verification.md), [failure coverage](failure-coverage.md),
[container triage](container-security.md) and [resilience operations](local-resilience.md).

Primary implementation references: [Python absolute timeouts](https://docs.python.org/3.12/library/asyncio-task.html#asyncio.timeout_at),
[Node 22 streams](https://nodejs.org/download/release/v22.23.4/docs/api/webstreams.html),
[PostgreSQL query plans](https://www.postgresql.org/docs/17/using-explain.html),
[OSV query semantics](https://google.github.io/osv.dev/post-v1-querybatch/).
