# Recovery: scoped Airflow authorization

Checkpoint: 2026-11-02. Stage 11's Airflow permission prerequisite is implemented and verified against the local Airflow **3.3.2** service. Dispatch remains disabled and unimplemented. This checkpoint does not enable execution or change the meaning of any existing review approval.

**Update 2026-11-03:** a separate [manual executable CLI](recovery-execution.md) now exists, with durable intent and reconciliation verified in isolation. Both capability switches remain off; no live recovery was dispatched. The original authorization checks below remain the 2026-11-02 checkpoint.

## Account and scope

The built-in SimpleAuthManager `user` role grants broad DAG write access. Recovery therefore uses a dedicated `pipeguard_recovery:viewer` account with the local `PipeGuardAuthManager` extension. The existing administrator and read-only observer retain their prior permissions.

| Recovery permission                                                                         | Current behavior                                                     |
| ------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| Read the exact `pipeguard_orders` DAG and its run metadata                                  | Allowed                                                              |
| Start a run of that exact DAG                                                               | Denied by default; requires the separate server process switch below |
| Other DAGs, wildcard scope or missing target                                                | Denied                                                               |
| Pause/unpause, update or delete DAGs/runs; clear tasks; inspect task/code/audit entities    | Denied                                                               |
| Configuration, connections, variables, pools, assets, teams, HITL approval and global views | Denied through the authorization hooks                               |

The reviewed public API maps the allowed POST run permission to `trigger_dag_run`. Asset materialization also checks that DAG permission, but requires a separate asset permission that recovery never receives. Bulk updates and task clearing require PUT permission, which is denied. Run reads can contain configuration and metadata; they are not a guarantee that arbitrary DAG configuration would be safe to display. The future dispatcher must validate and retain only its explicit response allowlist.

The administrator remains `RJ1899157`. The service account identifies future Airflow actions, not Git commits: GitHub authorship remains exclusively the user's identity. No recovery account is added to GitHub.

## Disabled execution boundary

Provisioning writes this private Airflow server configuration:

```dotenv
AIRFLOW__CORE__AUTH_MANAGER=pipeguard_airflow_auth.PipeGuardAuthManager
PIPEGUARD_AIRFLOW_RECOVERY_ENABLED=0
```

Only the literal value `1` admits the narrowly scoped POST authorization. This is a server capability switch, **not human approval**, an action queue or an authorization to reuse `recovery_review_v1` decisions. It stays `0` until a separately reviewed executable policy, durable dispatcher and reconciliation checks are implemented. Re-running provisioning resets it to `0`; a running server must be restarted to load changed environment configuration.

The extension refuses startup if the installed core version differs from 3.3.2, the all-admin bypass is enabled, the configured API host is not `127.0.0.1`, or the dedicated account is missing, duplicated, assigned a broader role or given teams. It also rejects missing, malformed or non-private password files and missing account passwords before the parent can generate or print any credentials. The launcher sets its child module search path to the reviewed auth directory outside the DAG folder. An Airflow upgrade requires source/API review and updated checks before changing the version guard.

Passwords are preseeded with independent generated values in ignored, owner-only `data/local/airflow/users.json`. Provisioning preserves existing values, rejects unsafe private-file permissions, malformed records and symlinks, and uses atomic owner-only writes. It never prints passwords. No recovery credential enters Next.js, the sample task, producer configuration or the read-only observer client.

SimpleAuthManager remains development authentication. The extension narrows this service account's permissions; it does not turn the local deployment into a public or multi-tenant identity system. The trusted local owner can change configuration and signing credentials.

## Verification

- **9 authorization tests** in Airflow's existing isolated environment. The DAG permission matrix covers **1,680 combinations**, including enabled/disabled/invalid switch values, targets, methods and every current DAG entity. Additional checks cover role/team escalation, list/batch scope, global resources, inherited administrator/observer behavior, startup guards, missing/unsafe credential files and the installed public-route permission mapping.
- Private provisioning regression: all accounts preseeded, independent generated passwords, existing values retained, unsafe permissions/malformed records/symlinks rejected. The launcher regression checks removal of an inherited module search path.
- **12 live HTTP checks**: allowed DAG/run reads; forbidden other-DAG, configuration, connection, variable, pool, asset and task reads; forbidden DAG patch, run creation and run deletion. Denied write probes used invalid bodies or an absent run ID, so an unexpected authorization failure could not modify an existing run.
- Existing administrator login/read and the observer's complete scan passed. The same **6 run identities/states/start/end timestamps** remained unchanged, with **11 attempt snapshots**. The DAG stayed paused; no workload or Groq generation was requested.
- **340 backend tests passed** (one existing upstream deprecation warning); see the adjacent [recovery checkpoint](recovery-verification.md). No database migration, dependency installation or frontend change was needed for this prerequisite.

Run the isolated permission checks from the repository root:

```sh
PYTHONPATH=infra/airflow/auth infra/airflow/.venv/bin/python -m unittest discover -s infra/airflow/tests -v
uv run --locked --env-file .env pytest -q apps/pipeguard/tests/test_operational_files.py
```

The live checks establish the current disabled authorization boundary. They do not verify a successful external recovery dispatch, deterministic-ID conflict handling, lost responses or interruption reconciliation. Those remain dispatcher acceptance requirements. No run was created merely to exercise a successful POST.

References: [Airflow 3.3.2 auth manager extension interface](https://airflow.apache.org/docs/apache-airflow/3.3.2/core-concepts/auth-manager/index.html), [SimpleAuthManager roles and development boundary](https://airflow.apache.org/docs/apache-airflow/3.3.2/core-concepts/auth-manager/simple/index.html), and the installed, pinned `airflow/api_fastapi/core_api/routes/public/dag_run.py` and `assets.py` route implementations.
