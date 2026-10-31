"""Bounded polling cycle, receipt recovery and durable detector completion heartbeat."""
import logging
import os
import time

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from pipeguard.db.models import IngestedEvent, MonitorPolicy, MonitorHeartbeat, Observation
from pipeguard.db.permissions import verify_runtime_access
from pipeguard.ingestion.service import process
from pipeguard.detection.airflow import AirflowClient, SourceUnavailable
from pipeguard.detection.service import evaluate_job, observe, now_utc
from pipeguard.detection.projection import reconcile


def cycle(bind, client=None):
    with Session(bind) as session:
        pending = list(session.scalars(select(IngestedEvent.id).where(
            IngestedEvent.processing_state == "pending").order_by(IngestedEvent.received_at).limit(100)))
        policies = list(session.scalars(select(MonitorPolicy)))
    failures = False
    for event_id in pending:
        try:
            process(bind, event_id)
        except Exception:
            failures = True
    for policy in policies:
        try:
            _job_cycle(bind, client, policy)
            _heartbeat(bind, "job:" + str(policy.job_id))
        except Exception:
            # A failing job must not prevent evaluation of unrelated jobs.
            failures = True
    if failures:
        raise RuntimeError("detector_cycle_incomplete")
    _heartbeat(bind, "detector")


def _heartbeat(bind, name):
    with Session(bind) as session, session.begin():
        session.execute(insert(MonitorHeartbeat).values(name=name, completed_at=now_utc())
                        .on_conflict_do_update(index_elements=["name"], set_={"completed_at": now_utc()}))


def _job_cycle(bind, client, policy):
    if policy.airflow_dag_id:
        try:
            if client is None:
                raise SourceUnavailable("source_not_configured")
            snapshots = client.scan(policy.airflow_dag_id, policy.airflow_task_id)
            with Session(bind) as session, session.begin():
                for when, payload in client.run_facts:
                    observe(session, policy.job_id, "airflow", "airflow_run", payload, when)
                for when, payload in snapshots:
                    observe(session, policy.job_id, "airflow", "airflow_attempt", payload, when)
                known = {o.payload["external_run_id"] for o in session.scalars(select(Observation).where(
                    Observation.job_id == policy.job_id, Observation.kind == "airflow_attempt"))}
                current = {p["external_run_id"] for _, p in snapshots}
                status = {"status": "incomplete", "error_code": "source_history_disappeared"} if known - current else {"status": "complete"}
                observe(session, policy.job_id, "airflow", "source_configuration",
                        {"is_paused": client.is_paused}, now_utc())
                observe(session, policy.job_id, "airflow", "source_scan", status,
                        now_utc(), key="scan:" + now_utc().isoformat())
            reconcile(bind, policy.job_id, snapshots)
        except (SourceUnavailable, KeyError, ValueError, TypeError) as exc:
            code = str(exc) if isinstance(exc, SourceUnavailable) else "source_invalid_response"
            with Session(bind) as session, session.begin():
                for when, payload in getattr(client, "run_facts", []):
                    observe(session, policy.job_id, "airflow", "airflow_run", payload, when)
                for when, payload in getattr(client, "partial", []):
                    observe(session, policy.job_id, "airflow", "airflow_attempt", payload, when)
                observe(session, policy.job_id, "airflow", "source_scan",
                        {"status": "incomplete", "error_code": code}, now_utc(),
                        key="scan:" + now_utc().isoformat())
            reconcile(bind, policy.job_id, getattr(client, "partial", []))
    evaluate_job(bind, policy.job_id)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    engine = create_engine(os.environ["PIPEGUARD_API_DATABASE_URL"], hide_parameters=True, pool_pre_ping=True,
                           connect_args={"connect_timeout": 5, "options": "-cstatement_timeout=10000 -clock_timeout=5000"})
    with engine.connect() as connection:
        verify_runtime_access(connection)
    client = AirflowClient(os.environ["PIPEGUARD_AIRFLOW_USERNAME"], os.environ["PIPEGUARD_AIRFLOW_PASSWORD"])
    # Never emit tracebacks containing driver parameters, remote response bodies, or credentials.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.CRITICAL)
    try:
        while True:
            try:
                cycle(engine, client)
                if args.once:
                    return 0
            except Exception:
                print("Monitor cycle failed; completion heartbeat was not advanced", flush=True)
                if args.once:
                    return 1
            time.sleep(15)
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
