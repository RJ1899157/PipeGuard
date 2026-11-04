# Integrated delivery operations

Stage 12 makes delivery reproducible without using retained incidents, private
configuration or the running local warehouse as test fixtures.

## Isolated verification

Prerequisites: Git, Python 3.12, uv 0.11.23, Docker with Compose 2.24.4 or later,
Node.js 22 and pnpm 11.25.0. Start Docker Desktop before the Python checks.
The runner also checks Node as invoked through pnpm: a launcher that silently
selects another Node major fails admission even if the shell's `node` is 22.
From the repository root:

```sh
uv run --locked python scripts/check_delivery.py
```

The default checks both environments; use `--suite python` or `--suite web` for
one area. `--revision <commit>` selects a committed revision; the default is
`HEAD`. Uncommitted changes are deliberately excluded. Commit intended changes
before using this command to verify them.

The runner:

1. Exports tracked source into a fresh owner-private temporary directory. No
   existing `.env`, virtual environment, database, model or generated bundle is copied.
2. Installs the application, orders workload and Airflow into three separate
   `.venv` directories from their reviewed locks. Airflow installation requires hashes.
3. Creates new local credentials and a uniquely named Compose project. PostgreSQL
   uses temporary in-memory storage and an automatically allocated loopback port.
   The retained `pipeguard` Compose project and its named volume are untouched.
4. Applies migrations, provisions restricted runtime and workload roles, runs the
   suites and contract/migration checks, and checks all three dependency environments.
5. Starts a separate authenticated HTTP API and runs a deliberate orders failure
   followed by a real dbt retry. It checks the original failed attempt, incident
   opening/resolution, unchanged captured evidence, 14 passing quality checks and
   complete reported lineage for the successful attempt.
6. Installs the dashboard from its frozen lockfile, checks strict unused/type rules,
   tests and formatting, and creates a production build in the temporary export.
   A separate HTTP smoke check starts that build, checks document/security headers,
   rejects foreign Host/Origin requests and confirms missing credentials fail closed.
   It does not execute a browser or connect to retained metadata.
7. Stops owned process groups and removes only its uniquely named temporary
   container/network. It checks for remaining containers before deleting the export.

No scheduler is started, no live DAG is unpaused, no hosted AI request is made and
no recovery execution is authorized by this runner. Recovery's separate API
approval/start and replay/failure paths run against synthetic source adapters in
the existing suite. The actual authorized Airflow recovery journey is recorded
in the [live recovery checkpoint](recovery-live-verification.md); this runner does
not claim to repeat that live source scenario.

The producer retains its fixed port-8000 destination restriction. The acceptance
scenario wraps only its HTTP transport to route the three admitted producer POST
paths to the separately owned temporary API port. The workload, dbt operations,
payloads, authentication and API ingestion are real; the fixture does not relax
production endpoint validation. The dashboard smoke similarly supplies its required
Host header while using a separate test listener.

### Results and interrupted checks

The command exits nonzero on a failed step or incomplete cleanup. Private logs and
`result.json` remain under `data/local/delivery-checks/<id>/` in the invoking checkout.
The report identifies the exact revision, each step, elapsed times and cleanup outcome.
It is not a performance benchmark or a vulnerability scan.

Ctrl+C and SIGTERM request cleanup. SIGKILL, Docker failure or host loss can prevent
cleanup; no handler can guarantee otherwise. If cleanup is incomplete, the runner
prints the private workspace location and records the exact Compose project name.
Inspect that specific project with `docker compose ls --all` and `docker ps --all`
before stopping/removing its containers. Temporary PostgreSQL data is disposable.
Never use global Docker pruning, delete retained volumes, or substitute the live
database connection into the isolated check.

## GitHub Actions

[Delivery checks](../.github/workflows/delivery.yml) provides separate Linux Python
and dashboard jobs using the same runner. It is **manual only** (`workflow_dispatch`). Before starting a run, confirm the
private repository's available included compute and spending controls.
No hosted run or free billing allowance is implied by the presence of the workflow.
After confirming the allowance, the owner can choose **Actions → Delivery checks →
Run workflow**, selecting the intended branch.

The workflow uses read-only repository permissions, no persisted checkout credential,
no repository secrets, no provider key, no deployment step and no Git write operation.
Actions are pinned to reviewed full commit hashes; dependencies remain locked.
Runs on the same ref cancel superseded checks and jobs have bounded timeouts.
Private environments and logs are not uploaded as artifacts or cached. If an action
fails, do not upload its private export to obtain diagnostics.

Automatic push/pull-request triggers and required branch checks remain a separate
owner decision. CI never creates commits under a bot or another identity.

Official references: [GitHub workflow security](https://docs.github.com/en/actions/reference/security/secure-use),
[uv integration](https://docs.astral.sh/uv/guides/integration/github/),
[Compose attribute replacement](https://docs.docker.com/reference/compose-file/merge/#replace-value).

## Retained local stack: startup and shutdown

For a new retained environment, follow [development setup](development/setup.md)
and the separate [Airflow setup](../infra/airflow/README.md). Existing installations
reuse their private configuration and volume; credential generators must not be
rerun to overwrite them.

For subsequent startup:

1. Start Docker Desktop and `docker compose up -d --wait postgres`.
2. Apply reviewed forward migrations with `uv run --locked --env-file .env alembic upgrade head`.
   Reapply API grants with `uv run --locked --env-file .env python scripts/configure_api.py`.
3. Start `uv run --locked --env-file .env python scripts/run_api.py` in its own terminal.
   Check API liveness at `http://127.0.0.1:8000/health/live`; authenticated readiness
   must also pass before treating database-dependent functions as healthy.
4. Start `uv run --locked --env-file .env.airflow python scripts/run_airflow.py start`
   in its own terminal, retaining daily-but-paused scheduling and recovery switches at `0`.
5. Start `uv run --locked --env-file .env.monitoring python scripts/run_monitor.py`
   in its own terminal; inspect dashboard monitoring coverage and watcher status.
6. Install/build the frontend as described in its [setup](../apps/pipeguard/web/README.md),
   then start `uv run --locked --env-file .env python scripts/run_dashboard.py` in its
   own terminal. Visit `http://127.0.0.1:3000/`.

Stop dashboard, monitor, Airflow and API through Ctrl+C in their respective owned
terminals, then use `docker compose stop postgres`. This preserves stored data.
Check for unfinished workload/backup activity before planned shutdown. An intentional
stop may produce watcher alerts; it is not evidence of data deletion. Do not unpause
the DAG or enable recovery merely to check startup. See [local resilience](local-resilience.md)
for watchdog handling and backup/restore procedures.

Same-host monitoring and same-disk backups retain their documented host-loss limits.
