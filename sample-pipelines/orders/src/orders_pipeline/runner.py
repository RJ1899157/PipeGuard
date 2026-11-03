"""Run source validation, raw replacement, and dbt build under one workload lock."""
from datetime import datetime, timezone
from contextlib import contextmanager
import argparse
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import pwd
import signal
import stat
import subprocess
import sys
import time
from uuid import uuid4

from orders_pipeline.loader import InvalidSource, WAREHOUSE_LOCK, Warehouse, parse_orders, replace_orders
from orders_pipeline.observer import Observer
from orders_pipeline.quality import extract
from orders_pipeline.lineage import extract as extract_lineage, gap as lineage_gap

ROOT = Path(__file__).resolve().parents[2]


def _warehouse_lock_path(settings):
    # OS account identity avoids checkout-specific paths or divergent HOME values.
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    base = home / "Library/Application Support/PipeGuard" if sys.platform == "darwin" else home / ".local/state/pipeguard"
    for directory in (base, base / "warehouse-locks"):
        if directory.is_symlink():
            raise ValueError("Warehouse lock directory must not be a symlink")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        information = directory.stat()
        if information.st_uid != os.getuid() or information.st_mode & 0o077:
            raise ValueError("Warehouse lock directory must be owner-private")
    identity = ["127.0.0.1" if settings.host == "localhost" else settings.host,
                settings.port, settings.database]
    return base / "warehouse-locks" / (sha256(json.dumps(identity).encode()).hexdigest() + ".lock")


@contextmanager
def _warehouse_guard(path):
    """Keep local runner exclusion alive in dbt even if its parent is SIGKILLed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        information = os.fstat(descriptor)
        if (not stat.S_ISREG(information.st_mode) or information.st_uid != os.getuid()
                or information.st_mode & 0o077):
            raise ValueError("Warehouse lock file must be owner-private and regular")
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("warehouse_busy") from None
                time.sleep(0.05)
        yield descriptor
    finally:
        # Never unlink or explicitly unlock: an inherited child descriptor can
        # still own this same lock after the parent's descriptor is closed.
        os.close(descriptor)


def _run_dbt(command, environment, log, lock_fd=None):
    """Stop dbt before releasing the warehouse lock on catchable interruption."""
    process = None
    interruption = None
    handlers = {kind: signal.getsignal(kind) for kind in (signal.SIGINT, signal.SIGTERM)}
    def interrupted(signum, frame):
        nonlocal interruption
        interruption = signum
        if process is not None:
            raise InterruptedError("workload_interrupted")
    for kind in handlers:
        signal.signal(kind, interrupted)
    try:
        process = subprocess.Popen(command, env=environment, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True,
                                   pass_fds=() if lock_fd is None else (lock_fd,))
        if interruption is not None:
            raise InterruptedError("workload_interrupted")
        returncode = process.wait(timeout=120)
        return subprocess.CompletedProcess(command, returncode)
    finally:
        for kind in handlers:
            signal.signal(kind, signal.SIG_IGN)
        try:
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
        finally:
            for kind, handler in handlers.items():
                signal.signal(kind, handler)


def run(source: Path, settings: Warehouse):
    rows = parse_orders(source)
    invocation = uuid4().hex
    artifacts = ROOT / "target" / invocation
    artifacts.mkdir(parents=True)
    environment = {key: value for key, value in os.environ.items()
                   if key in {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL"}} | {
        "DBT_SEND_ANONYMOUS_USAGE_STATS": "false", "DBT_USE_COLORS": "false",
        "ORDERS_HOST": settings.host, "ORDERS_PORT": str(settings.port),
        "ORDERS_DATABASE": settings.database, "ORDERS_USER": settings.user,
        "ORDERS_SCHEMA_PREFIX": settings.prefix, "DBT_ENV_SECRET_ORDERS_PASSWORD": settings.password,
    }
    with _warehouse_guard(_warehouse_lock_path(settings)) as lock_fd, settings.connect() as connection:
        connection.execute("SELECT pg_advisory_lock(%s)", (WAREHOUSE_LOCK,))
        load_started_at = datetime.now(timezone.utc).isoformat()
        replace_orders(connection, rows, settings.prefix)
        load_finished_at = datetime.now(timezone.utc).isoformat()
        # The session lock spans raw replacement and dbt's independently committed models.
        command = [str(Path(sys.executable).with_name("dbt")), "build", "--project-dir", str(ROOT / "dbt"),
                   "--profiles-dir", str(ROOT / "dbt"), "--target-path", str(artifacts),
                   "--log-path", str(artifacts / "logs")]
        with (artifacts / "dbt-console.log").open("w") as log:
            result = _run_dbt(command, environment, log, lock_fd)
    summary = {"invocation": invocation, "rows_loaded": len(rows), "dbt_succeeded": result.returncode == 0,
               "artifacts": str(artifacts.relative_to(ROOT)),
               "load_started_at": load_started_at, "load_finished_at": load_finished_at}
    (artifacts / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def execute(source, settings, observer=None, run_id=None, attempt=1, simulate_first_failure=False,
            simulate_terminal_failure=False):
    run_id = run_id or "manual-" + uuid4().hex
    delivery = []
    if observer:
        delivery.append(observer.emit(run_id, attempt, "running"))
    try:
        if simulate_terminal_failure or (simulate_first_failure and attempt == 1):
            raise RuntimeError("controlled_source_unavailable")
        summary = run(source, settings)
    except Exception as error:
        code = "validation_failed" if isinstance(error, InvalidSource) else "execution_error"
        if simulate_terminal_failure or (simulate_first_failure and attempt == 1):
            code = "source_unavailable"
        if observer:
            observer.emit(run_id, attempt, "failed", code)
            observer.emit_lineage(run_id, attempt, lineage_gap(run_id, attempt))
        raise
    state = "succeeded" if summary["dbt_succeeded"] else "failed"
    if observer:
        if summary.get("artifacts"):
            delivery.append(observer.emit_quality(run_id, attempt, extract(ROOT / summary["artifacts"])))
            delivery.append(observer.emit_lineage(run_id, attempt,
                extract_lineage(ROOT / summary["artifacts"], run_id, attempt, summary, settings.prefix)))
        delivery.append(observer.emit(run_id, attempt, state, None if state == "succeeded" else "validation_failed"))
    return summary | {"external_run_id": run_id, "attempt_number": attempt,
                      "monitoring": "disabled" if observer is None else ("acknowledged" if all(delivery) else "pending")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data/orders.csv")
    parser.add_argument("--run-id")
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument("--simulate-first-attempt-failure", action="store_true")
    parser.add_argument("--simulate-terminal-failure", action="store_true")
    parser.add_argument("--replay-events", action="store_true")
    args = parser.parse_args()
    try:
        observer = Observer.from_environment(ROOT)
        if args.replay_events:
            if observer is None:
                raise ValueError("Monitoring configuration required")
            result = observer.replay()
            print(json.dumps(result))
            return 0 if result["pending"] == 0 else 1
        summary = execute(args.input, Warehouse.from_environment(), observer, args.run_id,
                          args.attempt, args.simulate_first_attempt_failure, args.simulate_terminal_failure)
        print(json.dumps(summary))
        return 0 if summary["dbt_succeeded"] else 1
    except InvalidSource as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
    except Exception:
        print(json.dumps({"error": "sample_pipeline_failed"}), file=sys.stderr)
    return 1
