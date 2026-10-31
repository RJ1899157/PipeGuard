from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from pipeguard.db.models import Attempt, Base, Dataset, IngestedEvent, Integration, Job, Run


def make_job(db, name="orders", integration=None):
    if integration is None:
        integration = Integration(name=uuid4().hex, environment="test", kind="synthetic")
        db.add(integration)
        db.flush()
    job = Job(integration_id=integration.id, namespace="local", name=name, kind="task")
    db.add(job)
    db.flush()
    return job


def make_run(db):
    job = make_job(db)
    run = Run(job_id=job.id, external_run_id="scheduled-1")
    db.add(run)
    db.flush()
    return run


def make_event(integration_id, **overrides):
    values = dict(
        integration_id=integration_id, deduplication_key="event-1", event_type="run.failed",
        schema_version=1, occurred_at=datetime.now(timezone.utc), payload={},
        payload_hash=sha256(b"{}").hexdigest(), canonicalization_version="json-v1",
        redaction_version="synthetic-v1",
    )
    values.update(overrides)
    return IngestedEvent(**values)


def test_migration_roundtrip_and_metadata(migrated_database):
    connection, config = migrated_database
    assert set(inspect(connection).get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
    command.check(config)
    config.attributes["allow_data_loss"] = True
    command.downgrade(config, "base")
    assert inspect(connection).get_table_names() == ["alembic_version"]
    command.upgrade(config, "head")
    command.check(config)


def test_downgrade_requires_explicit_override(migrated_database):
    _, config = migrated_database
    with pytest.raises(RuntimeError, match="deletes history"):
        command.downgrade(config, "base")


def test_retry_keeps_failed_attempt_and_error(db):
    run = make_run(db)
    failed = Attempt(run_id=run.id, attempt_key="orders", attempt_number=1,
                     state="failed", error_code="CONNECTION_TIMEOUT",
                     error_message="Synthetic connection timeout")
    db.add(failed)
    db.flush()
    db.add(Attempt(run_id=run.id, attempt_key="orders", attempt_number=2, state="succeeded"))
    run.state = "succeeded"
    db.commit()
    attempts = db.scalars(select(Attempt).order_by(Attempt.attempt_number)).all()
    assert [a.state for a in attempts] == ["failed", "succeeded"]
    assert attempts[0].error_code == "CONNECTION_TIMEOUT"
    assert db.get(Run, run.id).state == "succeeded"


def test_duplicate_run_rejected(db):
    run = make_run(db)
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(Run(job_id=run.job_id, external_run_id=run.external_run_id))
            db.flush()


def test_external_run_id_is_scoped_to_job_and_producer(db):
    first = make_job(db)
    integration = db.get(Integration, first.integration_id)
    second = make_job(db, name="daily_revenue", integration=integration)
    third = make_job(db)
    for job in (first, second, third):
        db.add(Run(job_id=job.id, external_run_id="shared-external-id"))
    db.flush()
    assert db.scalar(select(func.count()).select_from(Run)) == 3


def test_unknown_parent_rejected(db):
    job = make_job(db)
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(Run(job_id=job.id, external_run_id="child", parent_run_id=uuid4()))
            db.flush()


def test_rollback_leaves_no_partial_records(db):
    with pytest.raises(IntegrityError):
        with db.begin():
            db.add(Dataset(namespace="local", name="orders", kind="table"))
            db.flush()
            db.add(Job(integration_id=uuid4(), namespace="local", name="bad", kind="task"))
            db.flush()
    assert db.scalar(select(func.count()).select_from(Dataset)) == 0


def test_duplicate_event_rejected_but_independent_producer_allowed(db):
    first, second = make_job(db), make_job(db)
    db.add(make_event(first.integration_id))
    db.flush()
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(make_event(first.integration_id))
            db.flush()
    db.add(make_event(second.integration_id))
    db.flush()
    assert db.scalar(select(func.count()).select_from(IngestedEvent)) == 2


@pytest.mark.parametrize("sql", [
    "UPDATE ingested_events SET payload = jsonb_build_object('changed', true)",
    "DELETE FROM ingested_events",
    "TRUNCATE ingested_events",
])
def test_source_event_history_protected(db, sql):
    db.add(make_event(make_job(db).integration_id))
    db.flush()
    with pytest.raises(DBAPIError, match="Source event"):
        with db.begin_nested():
            db.execute(text(sql))
    assert db.scalar(select(func.count()).select_from(IngestedEvent)) == 1


def test_processing_status_can_change(db):
    event = make_event(make_job(db).integration_id)
    db.add(event)
    db.flush()
    event.processing_state = "processed"
    event.processed_at = datetime.now(timezone.utc)
    db.flush()
    db.refresh(event)
    assert event.processing_state == "processed"


def test_late_start_event_preserves_both_observations(db):
    integration = make_job(db).integration_id
    now = datetime.now(timezone.utc)
    db.add(make_event(integration, occurred_at=now))
    db.flush()
    db.add(make_event(integration, deduplication_key="event-0", event_type="run.started",
                      occurred_at=now - timedelta(minutes=1)))
    db.flush()
    events = db.scalars(select(IngestedEvent).order_by(IngestedEvent.occurred_at)).all()
    assert [e.event_type for e in events] == ["run.started", "run.failed"]
    assert events[0].occurred_at.tzinfo is not None


@pytest.mark.parametrize("number,state", [(0, "running"), (1, "invalid")])
def test_attempt_constraints(db, number, state):
    run = make_run(db)
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(Attempt(run_id=run.id, attempt_key="orders", attempt_number=number, state=state))
            db.flush()


def test_referenced_history_cannot_be_cascade_deleted(db):
    run = make_run(db)
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.delete(db.get(Job, run.job_id))
            db.flush()
