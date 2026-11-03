"""Prepare a disabled local recovery CLI with only runtime DB and scoped Airflow access."""
import json
import os
from pathlib import Path
import sys
from uuid import UUID

from local_files import read_private, write_private
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/pipeguard/src"))
from pipeguard.db.models import MonitorPolicy
from pipeguard.db.permissions import verify_runtime_access
from pipeguard.recovery.airflow import DAG, TASK, USER


def main():
    root = Path(__file__).resolve().parents[1]
    job_id = UUID(os.environ["PIPEGUARD_RECOVERY_JOB_ID"])
    url = make_url(os.environ["PIPEGUARD_API_DATABASE_URL"])
    if (url.drivername != "postgresql+psycopg" or url.host != "127.0.0.1" or url.database != "pipeguard"
            or url.username != "pipeguard_api"):
        raise ValueError("Restricted local recovery database required")
    engine = create_engine(url, hide_parameters=True)
    try:
        with engine.connect() as connection:
            verify_runtime_access(connection)
        with Session(engine) as session:
            policy = session.scalar(select(MonitorPolicy).where(MonitorPolicy.job_id == job_id))
            if not policy or policy.airflow_dag_id != DAG or policy.airflow_task_id != TASK:
                raise ValueError("Exact configured sample target required")
    finally:
        engine.dispose()
    users = json.loads(read_private(root / "data/local/airflow/users.json", 65536))
    password = users[USER]
    if not isinstance(password, str) or not password or any(char in password for char in "\r\n"):
        raise ValueError("Private dedicated Airflow credential required")
    values = {"PIPEGUARD_API_DATABASE_URL": url.render_as_string(hide_password=False),
        "PIPEGUARD_RECOVERY_JOB_ID": str(job_id), "PIPEGUARD_RECOVERY_EXECUTION_ENABLED": "0",
        "PIPEGUARD_AIRFLOW_RECOVERY_USERNAME": USER, "PIPEGUARD_AIRFLOW_RECOVERY_PASSWORD": password}
    write_private(root / ".env.recovery", "".join(f"{key}={value}\n" for key, value in values.items()))
    print("Private recovery configuration prepared; execution disabled")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Recovery configuration failed (private details withheld)")
