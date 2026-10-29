# Development setup

## Current support

The repository currently supports creating a Python development environment. There is no runnable API, dashboard, database migration, sample workload, Compose configuration, or CI workflow yet.

## Prerequisites

| Tool | Requirement | Used for |
| --- | --- | --- |
| Git | Installed | Version control |
| GitHub authentication | Access as `RJ1899157` | Private repository access and remote changes |
| Python | 3.12 selected through `.python-version` | Application runtime |
| uv | Installed | Environment creation and dependency resolution |
| Node.js and pnpm | Planned Node.js 22 environment | Future web application |
| Docker Desktop | Required when container services are introduced | Future PostgreSQL and orchestration services |

`.python-version` selects Python 3.12; `pyproject.toml` currently declares a minimum of 3.12 rather than an upper-bound restriction. The lockfile contains no third-party application packages yet. Python patch versions and service image references will be documented when the runtime configuration is finalized.

## Existing development checkout

The primary development folder is:

```text
/Users/rishabhjain/Desktop/PipeGuard
```

From that folder:

```sh
uv sync --locked
uv run python --version
```

`uv sync --locked` creates or synchronizes `.venv` without accepting a changed dependency resolution. The Python version command checks the selected interpreter; it is not an application test.

Optional shell activation:

```sh
source .venv/bin/activate
```

Activation is unnecessary when running commands through `uv run`.

## New checkout

```sh
git clone https://github.com/RJ1899157/PipeGuard.git
cd PipeGuard
uv sync --locked
```

GitHub access must be configured for the private repository. Do not clone a similarly named repository under another owner.

## Dependency policy

- Add Python application packages using uv and keep installations inside `.venv`.
- Commit `pyproject.toml` and `uv.lock` together when dependency declarations change.
- Keep `.venv`, credentials, local data, and generated output out of source control.
- When the web project exists, install JavaScript packages in its local `node_modules` and commit its pnpm lockfile. Python virtual environments do not manage JavaScript packages.
- Isolate Airflow and provider dependencies from the API environment if their supported constraints differ.
- Pin container images when Compose services are added. Container dependencies are installed inside their images rather than the host `.venv`.

## Docker lifecycle

Docker Desktop is intentionally left stopped until a task requires container-backed services. Start it at that point, then use the repository's service instructions once they exist. No service startup or teardown command is prescribed yet because there is no Compose configuration.

## GitHub identity

Repository owner and active account must be `RJ1899157`. Commit author and committer must use the configured Rishabh Jain identity and account-associated noreply address. Verify them before commits and remote writes, as specified in [AGENTS.md](../../AGENTS.md).

## Verification status

Python environment synchronization and repository connection have been completed. There are no application tests, migration checks, browser checks, or performance results to report yet. Each delivery stage adds its relevant acceptance checks; consult the [roadmap](../roadmap.md).
