# Local orders orchestration

Airflow 3.3.2 on Python 3.12 runs the independent orders workload with LocalExecutor.
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
`requirements.lock` records the resolved packages and hashes. To install from root:

```sh
uv venv infra/airflow/.venv --python 3.12
uv pip sync --python infra/airflow/.venv/bin/python infra/airflow/requirements.lock
```

To intentionally regenerate a resolution, review the official constraint version,
then use the command recorded at the top of `requirements.lock` and rerun validation.
Do not install Airflow into the monitoring app or sample environment.

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
It is false by default and accepts no arbitrary input paths or commands.

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
worker termination or an SDK failure before workload entry can leave missing terminal
observations. A polling reconciler using Airflow's public API is not implemented;
there is no false claim of complete capture of every scheduler/worker failure.
OpenLineage, quality-result contracts, deterministic incidents and recovery actions
are later stages. See the sample README for durable event delivery semantics.
