"""Run source validation, raw replacement, and dbt build under one workload lock."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from orders_pipeline.loader import InvalidSource, WAREHOUSE_LOCK, Warehouse, parse_orders, replace_orders

ROOT = Path(__file__).resolve().parents[2]


def run(source: Path, settings: Warehouse):
    rows = parse_orders(source)
    invocation = uuid4().hex
    artifacts = ROOT / "target" / invocation
    artifacts.mkdir(parents=True)
    environment = os.environ | {
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data/orders.csv")
    args = parser.parse_args()
    try:
        summary = run(args.input, Warehouse.from_environment())
        print(json.dumps(summary))
        return 0 if summary["dbt_succeeded"] else 1
    except InvalidSource as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
    except Exception:
        # Source values, connection strings and subprocess exception details stay private.
        print(json.dumps({"error": "sample_pipeline_failed"}), file=sys.stderr)
    return 1
