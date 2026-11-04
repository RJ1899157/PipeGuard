"""Verify a committed revision in a private fresh export, never the retained local stack."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tarfile
import tempfile
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def stop(process):
    for kind in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, kind)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            continue
        if kind == signal.SIGKILL:
            break


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("python", "web", "all"), default="all")
    parser.add_argument("--revision", default="HEAD", help="Committed revision; working changes are not copied")
    args = parser.parse_args()
    os.umask(0o077)
    revision = subprocess.check_output(
        ["git", "rev-parse", "--verify", "--end-of-options", args.revision + "^{commit}"],
        cwd=ROOT, text=True).strip()
    if not re.fullmatch(r"[0-9a-f]{40,64}", revision):
        raise RuntimeError("Invalid committed revision")
    identity = uuid4().hex
    output = ROOT / "data/local/delivery-checks" / identity
    output.mkdir(parents=True, mode=0o700)
    workspace = Path(tempfile.mkdtemp(prefix="pipeguard-delivery-"))
    source = workspace / "source"
    source.mkdir()
    # Discard private application/provider configuration and inherited tool overrides.
    environment = {k: v for k, v in os.environ.items()
                   if k in {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SSL_CERT_FILE"}}
    environment.update(UV_PYTHON="3.12", UV_NO_PROGRESS="1", NEXT_TELEMETRY_DISABLED="1",
                       DO_NOT_TRACK="1", CI="1")
    result = {"revision": revision, "suite": args.suite, "steps": [], "passed": False,
              "cleanup_passed": False, "compose_project": "pipeguard-check-" + identity}
    compose = None

    def run(label, command, *, cwd=source, timeout=900, extra_env=None):
        log = output / (f"{len(result['steps']) + 1:02d}-" + label + ".log")
        step = {"name": label, "passed": False}
        result["steps"].append(step)
        started = time.monotonic()
        print(label, flush=True)
        with log.open("wb") as stream:
            process = subprocess.Popen(command, cwd=cwd, env=environment | (extra_env or {}), stdout=stream,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = process.wait(timeout=timeout)
            finally:
                stop(process)
                step["seconds"] = round(time.monotonic() - started, 3)
        step["passed"] = code == 0
        if code:
            raise RuntimeError(label + " failed; inspect its private log")

    def uv(*arguments):
        return ["uv", "run", "--locked", "--env-file", str(source / ".env"), *arguments]

    def interrupted(signum, frame):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, interrupted)
    try:
        archive = workspace / "source.tar"
        subprocess.run(["git", "archive", "--format=tar", "--output=" + str(archive), revision],
                       cwd=ROOT, env=environment, check=True, timeout=30)
        with tarfile.open(archive) as package:
            package.extractall(source, filter="data")
        if any(source.glob(".env*")) and any(p.name != ".env.example" for p in source.glob(".env*")):
            raise RuntimeError("Committed export contains private configuration")
        if args.suite in ("python", "all"):
            run("application-environment", ["uv", "sync", "--locked", "--python", "3.12"])
            run("new-private-configuration", ["uv", "run", "--locked", "python", "scripts/init_local_env.py"])
            override = source / "compose.delivery.yaml"
            override.write_text('''services:
  postgres:
    ports: !override
      - "127.0.0.1::5432"
    volumes: !override
      - ./infra/postgres/init.sh:/docker-entrypoint-initdb.d/01-pipeguard.sh:ro
    tmpfs:
      - /var/lib/postgresql/data
''')
            compose = ["docker", "compose", "--project-name", result["compose_project"],
                       "--file", "compose.yaml", "--file", "compose.delivery.yaml"]
            run("temporary-postgres", [*compose, "up", "--detach", "--wait", "--wait-timeout", "90", "postgres"], timeout=180)
            address = subprocess.check_output([*compose, "port", "postgres", "5432"],
                                             cwd=source, env=environment, text=True, timeout=30).strip()
            if not re.fullmatch(r"127\.0\.0\.1:[0-9]{1,5}", address):
                raise RuntimeError("Temporary database must bind loopback")
            port = address.rsplit(":", 1)[1]
            configuration = source / ".env"
            configuration.write_text(configuration.read_text().replace("=55432\n", "=" + port + "\n")
                                     .replace(":55432/", ":" + port + "/"))
            (source / ".delivery-check.json").write_text(json.dumps({"project": result["compose_project"], "port": int(port)}))
            run("migrations", uv("alembic", "upgrade", "head"))
            run("runtime-role", uv("python", "scripts/configure_api.py"))
            run("sample-warehouse", uv("python", "scripts/configure_sample_warehouse.py"))
            run("backend-suite", uv("pytest", "-q"))
            run("migration-consistency", uv("alembic", "check"))
            run("workload-environment", ["uv", "sync", "--project", "sample-pipelines/orders", "--locked", "--python", "3.12"])
            run("workload-suite", ["uv", "run", "--directory", "sample-pipelines/orders", "--locked",
                                   "--env-file", ".env", "pytest", "-q"])
            run("airflow-environment", ["uv", "venv", "infra/airflow/.venv", "--python", "3.12"])
            run("airflow-pinned-install", ["uv", "pip", "sync", "--python", "infra/airflow/.venv/bin/python",
                                          "--require-hashes", "infra/airflow/requirements.lock"])
            run("airflow-suite", [str(source / "infra/airflow/.venv/bin/python"), "-m", "unittest",
                                  "discover", "-s", "infra/airflow/tests", "-v"],
                extra_env={"PYTHONPATH": str(source / "infra/airflow/auth"),
                           "AIRFLOW_HOME": str(source / "data/local/airflow-check"),
                           "AIRFLOW__CORE__LOAD_EXAMPLES": "False"})
            for name, interpreter in (("application", ".venv/bin/python"),
                                      ("workload", "sample-pipelines/orders/.venv/bin/python"),
                                      ("airflow", "infra/airflow/.venv/bin/python")):
                run(name + "-dependency-consistency", ["uv", "pip", "check", "--python", interpreter])
            run("http-workload-acceptance", uv("python", "scripts/check_delivery_scenario.py"), timeout=240)
        if args.suite in ("web", "all"):
            web = source / "apps/pipeguard/web"
            run("web-runtime", ["node", "--eval", "if(process.versions.node.split('.')[0]!=='22')process.exit(1)"])
            run("web-dependencies", ["pnpm", "install", "--frozen-lockfile"], cwd=web)
            run("web-types", ["pnpm", "exec", "tsc", "--noEmit", "--noUnusedLocals", "--noUnusedParameters"], cwd=web)
            run("web-suite", ["pnpm", "test"], cwd=web)
            run("web-format", ["pnpm", "exec", "prettier", "--check", "app", "components", "lib", "tests", "proxy.ts", "next.config.ts"], cwd=web)
            run("web-build", ["pnpm", "build"], cwd=web)
        result["passed"] = True
    except (Exception, KeyboardInterrupt) as error:
        # Child output stays private; avoid leaking inherited or generated credentials.
        result["failure_type"] = type(error).__name__
        print("Delivery check did not pass; inspect the private logs.", flush=True)
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            if compose is not None:
                run("temporary-postgres-stop", [*compose, "down", "--timeout", "10"], timeout=60)
                remaining = subprocess.check_output(
                    ["docker", "ps", "--all", "--quiet", "--filter", "label=com.docker.compose.project=" + result["compose_project"]],
                    cwd=source, env=environment, text=True, timeout=30).strip()
                if remaining:
                    raise RuntimeError("Temporary container remains")
            shutil.rmtree(workspace)
            result["cleanup_passed"] = True
        except Exception:
            print("Cleanup incomplete; private workspace retained at " + str(workspace), flush=True)
            result["passed"] = False
        (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        signal.signal(signal.SIGTERM, previous)
        print("Private delivery report: " + str(output / "result.json"), flush=True)
    return 0 if result["passed"] and result["cleanup_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
