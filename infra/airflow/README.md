# Local orders orchestration

Airflow 3.3.2 on Python 3.12.16 runs the independent orders workload with LocalExecutor.
It has its own `.venv`, hash-pinned requirements and PostgreSQL metadata database.
PipeGuard receives bounded producer events; it never queries Airflow internal tables.
The UI/API listens on `127.0.0.1:8080`. This configuration is for local development.

## Dependency boundary

The earlier roadmap considered Airflow 3.1. The implementation selects the verified
3.3.2 release and its official Python 3.12 constraints. Neither API nor dbt packages
are installed into this environment. The DAG launches the sample's own Python
interpreter; dbt therefore continues to use its separate lockfile and environment.

Official references:

- [Apache installation and constraints](https://airflow.apache.org/docs/apache-airflow/3.3.2/installation/installing-from-pypi.html)
- [Simple auth manager](https://airflow.apache.org/docs/apache-airflow/3.3.2/core-concepts/auth-manager/simple/index.html)
- [Release constraints](https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-3.12.txt)

`constraints-3.12.txt` is the unmodified Apache release file. `requirements.in` selects
Airflow and both PostgreSQL drivers required by its synchronous/async metadata paths.
`security-constraints.txt` updates vulnerable transitive dependencies; the OpenTelemetry
family is updated together. `requirements.lock` records the complete compatible
resolution and hashes. To install from root:

```sh
uv venv infra/airflow/.venv --python 3.12.16
uv pip sync --python infra/airflow/.venv/bin/python infra/airflow/requirements.lock
```

To intentionally regenerate a resolution, review the official constraint version,
then run `uv run python scripts/compile_airflow_requirements.py` and rerun validation.
The resolver replaces only the named upstream constraints and still checks every
package's declared dependency requirements. It does not force incompatible packages
or bypass TLS/hash verification.
Do not install Airflow into the monitoring app or sample environment.

### Reviewed dependency advisories

The 2026-10-31 audit queried installed package/version pairs against OSV and checked
maintainer advisories. The security constraints address:

| Package       | Selected version | Maintainer advisory and local applicability                                                                                                                                                                                                                                                                                                                                                   |
| ------------- | ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| certifi       | 2026.10.23       | [GHSA-6q48-6c7w-9gw2](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2): compromised emSign intermediate keys; update the trust store even though the sample uses loopback HTTP                                                                                                                                                                              |
| dnspython     | 2.9.1            | [GHSA-45c3-73f7-pv4m](https://github.com/rthalley/dnspython/security/advisories/GHSA-45c3-73f7-pv4m): excessive DNS parser CPU; the sample has no external DNS input                                                                                                                                                                                                                          |
| Mako          | 1.4.3            | [GHSA-5639-2j2p-m4mx](https://github.com/sqlalchemy/mako/security/advisories/GHSA-5639-2j2p-m4mx): Windows drive-letter template traversal; not applicable to this Mac, still patched for portability                                                                                                                                                                                         |
| OpenTelemetry | 1.45.2 / 0.66b2  | [GHSA-xcq7-p3pf-p88h](https://github.com/open-telemetry/opentelemetry-python/security/advisories/GHSA-xcq7-p3pf-p88h): unbounded tracestate parsing; no external tracing inputs are configured                                                                                                                                                                                                |
| PyJWT         | 2.15.1           | [GHSA-42vr-xj54-vc7v](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-42vr-xj54-vc7v), [GHSA-x33g-cr3x-6449](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-x33g-cr3x-6449): unverified-payload recursion and inconsistent OKP JWKs; Airflow uses JWT authentication, with no external JWK configuration in this sample                                                |
| urllib3       | 2.8.0            | [GHSA-8988-9cw3-xx77](https://github.com/urllib3/urllib3/security/advisories/GHSA-8988-9cw3-xx77), [GHSA-gh4c-6fx4-qh6g](https://github.com/urllib3/urllib3/security/advisories/GHSA-gh4c-6fx4-qh6g), [GHSA-vxq7-64xx-v4gw](https://github.com/urllib3/urllib3/security/advisories/GHSA-vxq7-64xx-v4gw): proxy TLS, deflate loop and unbounded chunk parsing; no external proxy is configured |

No-known-advisory results are time-specific checks, not a production security claim.

## Local preparation

Start PostgreSQL and the PipeGuard API using the root setup instructions. Configure
the sample warehouse, dependencies and scoped producer, then Airflow:

```sh
uv run --env-file .env python scripts/configure_sample_monitoring.py
uv run --env-file .env python scripts/configure_airflow.py
uv run --env-file .env.airflow python scripts/run_airflow.py init
uv run --env-file .env.airflow python scripts/run_airflow.py start
```

The sample warehouse and `.venv` must already exist. Provisioning uses root private
configuration only for setup. `.env.airflow` contains only orchestrator configuration;
the workload's `.env` contains only warehouse and integration-scoped producer values.
The DAG passes an explicit allowlist of workload variables, omitting Airflow database
credentials and signing keys. The workload strips monitoring/orchestrator variables
before invoking dbt. No secrets are embedded in the DAG or passed as command arguments.

`airflow_owner` owns only the `airflow` metadata database. The metadata role cannot
connect to PipeGuard or the sample warehouse; the other runtime roles cannot connect
to Airflow. All three databases share one local server, so this is access isolation,
not physical failure isolation.

Runtime files and logs stay under ignored `data/local/airflow`. The local UI user is
`RJ1899157`; its generated password is stored privately in `data/local/airflow/users.json`
with mode 0600 and is preseeded so initialization does not print generated passwords.
SimpleAuthManager is development authentication, not a production identity system.
The local `PipeGuardAuthManager` extension preserves the administrator and observer
roles while restricting the dedicated recovery account to the sample DAG/run scope.
Recovery writes stay disabled by default. See the [authorization checkpoint](../../docs/recovery-airflow-authorization.md)
for the version/startup guards, permission matrix and verification. Start Airflow
through `scripts/run_airflow.py` so the reviewed auth module is on its search path.
Authentication is enabled; the all-admin bypass is disabled.

The launcher starts API server, scheduler and DAG processor, limits execution to
one task, disables the scheduler's network log server and public health server,
and cleans up its process groups on Ctrl+C. The API binds only loopback. There is
no triggerer because this DAG has no deferrable tasks. LocalExecutor runs on the
host; the configuration does not claim container isolation. On macOS the launcher
uses the environment's explicit fork-safety setting for this development executor.

## DAG and attempts

`pipeguard_orders` has a daily schedule, `catchup=False`, and one `build_orders`
task. It is paused on creation. A task invocation encompasses CSV loading and dbt
build/tests; this is deliberately one monitored job, not an aggregation of many
Airflow task states. It has one retry, a five-second retry delay and bounded
execution/subprocess times.

The task reads documented SDK context. Its external PipeGuard run ID is a stable
SHA-256-based identifier derived from DAG ID, DAG run ID and task ID. Native
`ti.try_number` maps to the PipeGuard attempt number. Retries reuse the run identity
and create new attempts. The `simulate_first_attempt_failure` boolean parameter
fails attempt 1 with a bounded synthetic category; attempt 2 runs the real workload.
It is false by default and accepts no arbitrary input paths or commands. The separate `simulate_terminal_failure` boolean fails every attempt before warehouse work, so the one retry also fails. It is false by default; ordinary recovery runs do not carry this fault parameter.

Use the UI or the documented CLI through the launcher:

```sh
uv run --env-file .env.airflow python scripts/run_airflow.py cli dags list-import-errors --output json
uv run --env-file .env.airflow python scripts/run_airflow.py cli dags trigger pipeguard_orders --run-id example_retry --conf '{"simulate_first_attempt_failure":true}'
uv run --env-file .env.airflow python scripts/run_airflow.py cli dags unpause pipeguard_orders
uv run --env-file .env.airflow python scripts/run_airflow.py cli dags list-runs pipeguard_orders --output json
uv run --env-file .env.airflow python scripts/run_airflow.py cli dags pause pipeguard_orders
```

Unpausing can also run the current daily scheduled interval. Pause after demonstrations
if scheduled work is not wanted. A manually triggered run of a paused DAG waits for
unpause. CLI listings can reflect the previous pause value while the update commits;
read the DAG again to confirm. Each new manual demonstration needs a fresh DAG run ID.

## Verification and limits

A real scheduled run and a real manual controlled-retry run both succeeded through
the scheduler/LocalExecutor. PipeGuard's HTTP API verified that the manual run had
attempt 1 `failed/source_unavailable`, attempt 2 `succeeded`, and an overall
`succeeded` outcome without deleting the failed attempt. DAG import checks returned
no errors. After verification the example DAG was paused. The API/UI components
remain available locally. Optional Graphviz rendering is not installed; CLI commands
emit its warning without preventing execution. Existing test tooling also emits an
HTTPX deprecation warning.

The adapter records normal workload starts/outcomes and source/dbt exceptions. Abrupt
worker termination or an SDK failure before workload entry can leave missing producer
terminal observations. The independent public-API reconciler retains available
Airflow evidence and flags missing coverage; quality, lineage and deterministic
incidents are implemented. Recovery execution remains planned.

Catchable SIGINT/SIGTERM and subprocess timeouts stop owned process groups before
releasing workload resources. A persistent local file lock is inherited by dbt, so
SIGKILL of its parent retains exclusion while that child survives. The PostgreSQL
advisory lock remains in place too. The local lock protects cooperating runners across checkouts under the same Unix account, using a stable owner-private per-warehouse path under Application Support (or local state on Linux). Other accounts/hosts and direct SQL writers require separate fencing. Never unlink an active lock file.
SIGKILL cannot run cleanup handlers or invent missing outcomes; independent
reconciliation exposes available source evidence and coverage gaps. This is not
atomic warehouse rollback. Host power loss, disk failure and off-host notifications
require separate operations.
See the sample README for durable event delivery semantics.

## Independent monitoring

The incident worker uses a dedicated `pipeguard_observer:viewer` account and public Airflow APIs. It reads DAG runs, native try history and health without access to the Airflow database. Source coverage becomes explicitly incomplete on authentication, transport, health, history or pagination failures. See [incident operations](../../docs/incident-operations.md) and [failure coverage](../../docs/failure-coverage.md).


## Manual scheduling for controlled recovery acceptance

The optional private `.env.airflow` setting `PIPEGUARD_AIRFLOW_MANUAL_ONLY=1` selects `schedule=None` when the DAG is parsed; `0` or an absent setting retains `@daily`. Any other value refuses import. Changing it requires an owned launcher restart and verification that the serialized public DAG timetable changed, while the DAG remains paused. It does not unpause, enable recovery or remove queued runs. Provisioning preserves the selected scheduling mode.

The [controlled recovery scenario](../../docs/recovery-live-scenario.md) describes the explicit approval, terminal fault, separate recovery and restoration procedure. Do not unpause for that scenario until the no-schedule timetable and idle source inventory are verified.
