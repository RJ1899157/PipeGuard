"""Run source validation, raw replacement, and dbt build under one workload lock."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from orders_pipeline.loader import InvalidSource, WAREHOUSE_LOCK, Warehouse, parse_orders, replace_orders
from orders_pipeline.observer import Observer
from orders_pipeline.quality import extract

ROOT = Path(__file__).resolve().parents[2]


def run(source: Path, settings: Warehouse):
    rows = parse_orders(source)
    invocation = uuid4().hex
    artifacts = ROOT / "target" / invocation
    artifacts.mkdir(parents=True)
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("PIPEGUARD_", "AIRFLOW"))} | {
        "DBT_SEND_ANONYMOUS_USAGE_STATS": "false", "DBT_USE_COLORS": "false",
        "ORDERS_HOST": settings.host, "ORDERS_PORT": str(settings.port),
        "ORDERS_DATABASE": settings.database, "ORDERS_USER": settings.user,
        "ORDERS_SCHEMA_PREFIX": settings.prefix, "DBT_ENV_SECRET_ORDERS_PASSWORD": settings.password,
    }
    with settings.connect() as connection:
        connection.execute("SELECT pg_advisory_lock(%s)", (WAREHOUSE_LOCK,))
        replace_orders(connection, rows, settings.prefix)
        # The session lock spans raw replacement and dbt's independently committed models.
        command = [str(Path(sys.executable).with_name("dbt")), "build", "--project-dir", str(ROOT / "dbt"),
                   "--profiles-dir", str(ROOT / "dbt"), "--target-path", str(artifacts),
                   "--log-path", str(artifacts / "logs")]
        with (artifacts / "dbt-console.log").open("w") as log:
            result = subprocess.run(command, env=environment, stdout=log, stderr=subprocess.STDOUT,
                                    timeout=120, check=False)
    summary = {"invocation": invocation, "rows_loaded": len(rows), "dbt_succeeded": result.returncode == 0,
               "artifacts": str(artifacts.relative_to(ROOT))}
    (artifacts / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def execute(source, settings, observer=None, run_id=None, attempt=1, simulate_first_failure=False):
    run_id = run_id or "manual-" + uuid4().hex
    delivery = []
    if observer:
        delivery.append(observer.emit(run_id, attempt, "running"))
    try:
        if simulate_first_failure and attempt == 1:
            raise RuntimeError("controlled_source_unavailable")
        summary = run(source, settings)
    except Exception as error:
        code = "validation_failed" if isinstance(error, InvalidSource) else "execution_error"
        if simulate_first_failure and attempt == 1:
            code = "source_unavailable"
        if observer:
            observer.emit(run_id, attempt, "failed", code)
        raise
    state = "succeeded" if summary["dbt_succeeded"] else "failed"
    if observer:
        if summary.get("artifacts"):
            delivery.append(observer.emit_quality(run_id, attempt, extract(ROOT / summary["artifacts"])))
        delivery.append(observer.emit(run_id, attempt, state, None if state == "succeeded" else "validation_failed"))
    return summary | {"external_run_id": run_id, "attempt_number": attempt,
                      "monitoring": "disabled" if observer is None else ("acknowledged" if all(delivery) else "pending")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data/orders.csv")
    parser.add_argument("--run-id")
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument("--simulate-first-attempt-failure", action="store_true")
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
                          args.attempt, args.simulate_first_attempt_failure)
        print(json.dumps(summary))
        return 0 if summary["dbt_succeeded"] else 1
    except InvalidSource as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
    except Exception:
        print(json.dumps({"error": "sample_pipeline_failed"}), file=sys.stderr)
    return 1
