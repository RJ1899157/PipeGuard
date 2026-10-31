"""Backfill missing execution boundaries from independently stored orchestrator evidence."""
from datetime import datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from pipeguard.db.models import Attempt, IngestedEvent, Job, Run
from pipeguard.ingestion.service import TERMINAL
from pipeguard.ingestion.contracts import ExecutionEvent


def _time(value):
    return datetime.fromisoformat(value) if value else None


def reconcile(bind, job_id, snapshots):
    with Session(bind) as session, session.begin():
        job = session.get(Job, job_id)
        events = list(session.scalars(select(IngestedEvent).where(
            IngestedEvent.integration_id == job.integration_id,
            IngestedEvent.payload["job_id"].as_string() == str(job_id))))
        by_attempt = {}
        for event in events:
            try:
                payload = ExecutionEvent.model_validate(event.payload).model_dump(mode="json")
            except ValidationError:
                continue
            by_attempt.setdefault((payload.get("external_run_id"), payload.get("attempt_number")), []).append(payload)
        for _, p in snapshots:
            session.execute(insert(Run).values(job_id=job_id, external_run_id=p["external_run_id"])
                            .on_conflict_do_nothing(index_elements=["job_id", "external_run_id"]))
            run = session.scalar(select(Run).where(Run.job_id == job_id, Run.external_run_id == p["external_run_id"])
                                 .with_for_update())
            attempts = list(session.scalars(select(Attempt).where(Attempt.run_id == run.id)))
            if any(a.attempt_key != "job" for a in attempts):
                run.reconciliation_required = True
                continue
            attempt = next((a for a in attempts if a.attempt_number == p["attempt_number"]), None)
            if attempt is None:
                attempt = Attempt(run_id=run.id, attempt_key="job", attempt_number=p["attempt_number"],
                                  projection_source="airflow", state="unknown", reconciliation_required=False)
                session.add(attempt); attempts.append(attempt)
            producer = by_attempt.get((p["external_run_id"], p["attempt_number"]), [])
            producer_terminal = {e["state"] for e in producer if e.get("state") in TERMINAL}
            if p["state"] in TERMINAL and producer_terminal and producer_terminal != {p["state"]}:
                attempt.reconciliation_required = True
                attempt.state = "unknown"
            elif not producer_terminal and not attempt.reconciliation_required:
                # Scheduler evidence may supply a missing start/terminal, never erase producer terminals.
                if attempt.projection_source == "airflow" or p["state"] in TERMINAL:
                    attempt.projection_source = "airflow"
                    attempt.state = p["state"]
                    attempt.started_at = _time(p["started_at"])
                    attempt.finished_at = _time(p["finished_at"]) if p["state"] in TERMINAL else None
                    attempt.error_code = "unknown" if p["state"] == "failed" else None
            latest = max(attempts, key=lambda a: a.attempt_number)
            run.state = latest.state
            run.reconciliation_required = any(a.reconciliation_required for a in attempts)
            starts = [a.started_at for a in attempts if a.started_at]
            run.started_at = min(starts) if starts else None
            run.finished_at = latest.finished_at if latest.state in TERMINAL else None
