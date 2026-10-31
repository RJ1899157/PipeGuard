from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from itertools import permutations

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from pipeguard.db.config import database_url
from pipeguard.db.models import Attempt, IngestedEvent, Integration, Job, Run
from pipeguard.ingestion.service import IngestionRejected, process, receive

NOW = datetime(2026, 10, 31, 10, tzinfo=timezone.utc)


@pytest.fixture
def source(migrated_database):
    connection, _ = migrated_database
    with Session(connection) as session, session.begin():
        integration = Integration(name="synthetic", environment="test", kind="synthetic")
        session.add(integration)
        session.flush()
        job = Job(integration_id=integration.id, namespace="test", name="orders", kind="job")
        session.add(job)
        session.flush()
        data = dict(schema_version=1, integration_id=str(integration.id), job_id=str(job.id),
                    external_run_id="run-1", event_id="event-1", attempt_number=1,
                    state="running", occurred_at=NOW.isoformat())
    return connection, data


def deliver(connection, data):
    receipt = receive(connection, data)
    result = process(connection, receipt.event_id)
    assert result.processing_state == "processed"
    return receipt, result


def test_exact_replay_does_not_duplicate_records(source):
    connection, data = source
    first, _ = deliver(connection, data)
    second, _ = deliver(connection, data)
    assert not first.replayed and second.replayed and first.event_id == second.event_id
    with Session(connection) as session:
        for model in (Run, Attempt, IngestedEvent):
            assert session.scalar(select(func.count()).select_from(model)) == 1


def test_reused_event_id_with_changed_content_is_rejected(source):
    connection, data = source
    original, _ = deliver(connection, data)
    with pytest.raises(IngestionRejected, match="event_id_content_conflict"):
        receive(connection, data | {"state": "failed"})
    with Session(connection) as session:
        assert session.get(IngestedEvent, original.event_id).payload["state"] == "running"
        assert session.scalar(select(Run)).state == "running"


def test_replay_normalizes_equivalent_timezone(source):
    connection, data = source
    first = receive(connection, data)
    equivalent = NOW.astimezone(timezone(timedelta(hours=5, minutes=30))).isoformat()
    replay = receive(connection, data | {"occurred_at": equivalent})
    assert replay.event_id == first.event_id and replay.replayed


@pytest.mark.parametrize("order", list(permutations(range(3))))
def test_retry_projection_is_independent_of_delivery_order(source, order):
    connection, data = source
    observations = [
        data,
        data | {"event_id": "failed-1", "state": "failed", "error_code": "connection_timeout",
                "occurred_at": (NOW + timedelta(minutes=1)).isoformat()},
        data | {"event_id": "success-2", "state": "succeeded", "attempt_number": 2,
                "occurred_at": (NOW + timedelta(minutes=2)).isoformat()},
    ]
    for index in order:
        deliver(connection, observations[index])
    with Session(connection) as session:
        run = session.scalar(select(Run))
        attempts = session.scalars(select(Attempt).order_by(Attempt.attempt_number)).all()
        assert run.state == "succeeded" and not run.reconciliation_required
        assert [a.state for a in attempts] == ["failed", "succeeded"]
        assert attempts[0].error_code == "connection_timeout"
        assert attempts[0].started_at == NOW
        assert session.scalar(select(func.count()).select_from(IngestedEvent)) == 3


@pytest.mark.parametrize("order", [("failed", "succeeded"), ("succeeded", "failed")])
def test_conflicting_terminal_states_are_visible_and_sticky(source, order):
    connection, data = source
    for state in order:
        deliver(connection, data | {"event_id": state, "state": state})
    deliver(connection, data | {"event_id": "late-start"})
    with Session(connection) as session:
        run, attempt = session.scalar(select(Run)), session.scalar(select(Attempt))
        assert run.state == attempt.state == "unknown"
        assert run.reconciliation_required and attempt.reconciliation_required
        assert run.finished_at is None


def test_new_attempt_does_not_hide_previous_uncertainty(source):
    connection, data = source
    for state in ("failed", "succeeded"):
        deliver(connection, data | {"event_id": state, "state": state})
    deliver(connection, data | {"event_id": "retry-success", "attempt_number": 2, "state": "succeeded"})
    with Session(connection) as session:
        run = session.scalar(select(Run))
        assert run.state == "succeeded" and run.reconciliation_required


def test_new_running_retry_clears_prior_run_finish(source):
    connection, data = source
    deliver(connection, data | {"state": "failed"})
    deliver(connection, data | {"event_id": "retry", "attempt_number": 2})
    with Session(connection) as session:
        run = session.scalar(select(Run))
        assert run.state == "running" and run.finished_at is None


@pytest.mark.parametrize("changes", [
    {"attempt_number": 0}, {"attempt_number": True}, {"attempt_number": "1"},
    {"occurred_at": "2026-10-31T10:00:00"}, {"state": "made-up"},
    {"schema_version": 2}, {"schema_version": True}, {"schema_version": 1.0},
    {"error_code": "connection_timeout"}, {"error_message": "arbitrary secret text"},
    {"payload": {"password": "synthetic-only"}}, {"external_run_id": ""},
])
def test_invalid_envelopes_rejected_without_storage(source, changes):
    connection, data = source
    with pytest.raises(ValidationError):
        receive(connection, data | changes)
    with Session(connection) as session:
        assert session.scalar(select(func.count()).select_from(IngestedEvent)) == 0


def test_cross_integration_job_rejected(source):
    connection, data = source
    with Session(connection) as session, session.begin():
        other = Integration(name="other", environment="test", kind="synthetic")
        session.add(other)
        session.flush()
        other_id = str(other.id)
    with pytest.raises(IngestionRejected, match="job_integration_mismatch"):
        receive(connection, data | {"integration_id": other_id})


def test_failed_processing_can_resume_after_integration_reenabled(source):
    connection, data = source
    receipt = receive(connection, data)
    with Session(connection) as session, session.begin():
        session.get(Integration, data["integration_id"]).enabled = False
    result = process(connection, receipt.event_id)
    assert result.processing_state == "failed" and result.error == "integration_unavailable"
    with Session(connection) as session, session.begin():
        assert session.scalar(select(func.count()).select_from(Run)) == 0
        session.get(Integration, data["integration_id"]).enabled = True
    assert process(connection, receipt.event_id).processing_state == "processed"


def test_receipt_survives_projection_failure(source, monkeypatch):
    import pipeguard.ingestion.service as service
    connection, data = source
    receipt = receive(connection, data)
    original = service._apply
    def fail(*args):
        raise RuntimeError("synthetic failure")
    monkeypatch.setattr(service, "_apply", fail)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        process(connection, receipt.event_id)
    with Session(connection) as session:
        assert session.get(IngestedEvent, receipt.event_id).processing_state == "pending"
        assert session.scalar(select(func.count()).select_from(Run)) == 0
    monkeypatch.setattr(service, "_apply", original)
    assert process(connection, receipt.event_id).processing_state == "processed"


def test_concurrent_duplicate_and_retry_deliveries(source):
    connection, data = source
    schema = connection.scalar(text("SELECT current_schema()"))
    connection.commit()
    engine = create_engine(database_url(), hide_parameters=True,
                           connect_args={"options": f"-csearch_path={schema} -clock_timeout=5000"})
    try:
        copies = [data] * 4 + [data | {"event_id": "retry", "attempt_number": 2, "state": "succeeded"}] * 4
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda item: deliver(engine, item), copies))
        assert sum(not receipt.replayed for receipt, _ in results) == 2
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(Run)) == 1
            assert session.scalar(select(func.count()).select_from(Attempt)) == 2
            assert session.scalar(select(Run)).state == "succeeded"
    finally:
        engine.dispose()


@pytest.mark.parametrize("order", list(permutations(range(3))))
def test_conflicting_start_timestamps_are_order_independent(source, order):
    connection, data = source
    observations = [data,
        data | {"event_id": "different-start", "occurred_at": (NOW + timedelta(minutes=2)).isoformat()},
        data | {"event_id": "finished", "state": "succeeded", "occurred_at": (NOW + timedelta(minutes=1)).isoformat()},
    ]
    for index in order:
        deliver(connection, observations[index])
    with Session(connection) as session:
        run = session.scalar(select(Run))
        assert run.state == "unknown" and run.reconciliation_required


def test_disabled_integration_rejected_before_receipt(source):
    connection, data = source
    with Session(connection) as session, session.begin():
        session.get(Integration, data["integration_id"]).enabled = False
    with pytest.raises(IngestionRejected, match="integration_unavailable"):
        receive(connection, data)
    with Session(connection) as session:
        assert session.scalar(select(func.count()).select_from(IngestedEvent)) == 0


def test_identical_external_ids_across_producers_are_independent(source):
    connection, data = source
    with Session(connection) as session, session.begin():
        other = Integration(name="other", environment="test", kind="synthetic")
        session.add(other)
        session.flush()
        job = Job(integration_id=other.id, namespace="test", name="orders", kind="job")
        session.add(job)
        session.flush()
        second = data | {"integration_id": str(other.id), "job_id": str(job.id)}
    deliver(connection, data)
    deliver(connection, second)
    with Session(connection) as session:
        assert session.scalar(select(func.count()).select_from(Run)) == 2
        assert session.scalar(select(func.count()).select_from(IngestedEvent)) == 2


def test_legacy_attempt_scope_is_not_silently_aggregated(source):
    connection, data = source
    with Session(connection) as session, session.begin():
        run = Run(job_id=data["job_id"], external_run_id=data["external_run_id"], state="failed")
        session.add(run)
        session.flush()
        session.add(Attempt(run_id=run.id, attempt_key="legacy-task", attempt_number=1, state="failed"))
    receipt = receive(connection, data)
    result = process(connection, receipt.event_id)
    assert result.error == "unsupported_attempt_scope"
    with Session(connection) as session:
        assert session.scalar(select(Run)).state == "failed"
        assert session.scalar(select(func.count()).select_from(Attempt)) == 1


def test_cli_durable_receipt_and_retry(source, tmp_path):
    import json
    import os
    import subprocess
    import sys
    connection, data = source
    schema = connection.scalar(text("SELECT current_schema()"))
    connection.commit()
    event_file = tmp_path / "synthetic-event.json"
    event_file.write_text(json.dumps(data))
    environment = os.environ | {"PGOPTIONS": f"-c search_path={schema}"}
    receipt = subprocess.run([sys.executable, "scripts/ingest_event.py", "--file", str(event_file),
                              "--receive-only"], env=environment, capture_output=True, text=True, check=True)
    event_id = json.loads(receipt.stdout)["event_id"]
    with Session(connection) as session:
        assert session.get(IngestedEvent, event_id).processing_state == "pending"
    processed = subprocess.run([sys.executable, "scripts/ingest_event.py", "--process-event", event_id],
                               env=environment, capture_output=True, text=True, check=True)
    assert json.loads(processed.stdout.splitlines()[-1])["processing_state"] == "processed"
    with Session(connection) as session:
        assert session.scalar(select(Run)).state == "running"


def test_cli_validation_does_not_echo_input(source, tmp_path):
    import json
    import os
    import subprocess
    import sys
    _, data = source
    marker = "SYNTHETIC_PRIVATE_TEXT_FOR_REDACTION_TEST"
    event_file = tmp_path / "invalid.json"
    event_file.write_text(json.dumps(data | {"error_message": marker}))
    result = subprocess.run([sys.executable, "scripts/ingest_event.py", "--file", str(event_file)],
                            env=os.environ, capture_output=True, text=True)
    assert result.returncode == 1
    assert marker not in result.stdout + result.stderr
    assert "invalid_event" in result.stderr


@pytest.mark.parametrize("codes", [("connection_timeout", "source_unavailable"),
                                   ("source_unavailable", "connection_timeout")])
def test_conflicting_error_categories_remain_unknown(source, codes):
    connection, data = source
    for index, code in enumerate(codes):
        deliver(connection, data | {"event_id": f"error-{index}", "state": "failed", "error_code": code})
    with Session(connection) as session:
        attempt = session.scalar(select(Attempt))
        assert attempt.state == "unknown" and attempt.reconciliation_required
        assert attempt.error_code == "unknown"
