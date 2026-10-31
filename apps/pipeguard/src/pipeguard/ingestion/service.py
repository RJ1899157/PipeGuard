"""Durable receipt followed by transactional, serialized execution projection."""
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from pipeguard.db.models import Attempt, IngestedEvent, Integration, Job, Run
from pipeguard.ingestion.contracts import ExecutionEvent


class IngestionRejected(ValueError):
    """Safe machine-readable rejection code; never include submitted payloads."""


@dataclass(frozen=True)
class Receipt:
    event_id: UUID
    replayed: bool


@dataclass(frozen=True)
class ProcessingResult:
    event_id: UUID
    processing_state: str
    error: str | None


def receive(bind, data: dict) -> Receipt:
    """Owns its transaction. Caller must provide a dedicated engine/connection."""
    event = ExecutionEvent.model_validate(data)
    payload = event.model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = sha256(encoded.encode("utf-8")).hexdigest()
    with Session(bind) as session, session.begin():
        integration = session.scalar(select(Integration).where(
            Integration.id == event.integration_id).with_for_update(read=True))
        if integration is None or not integration.enabled:
            raise IngestionRejected("integration_unavailable")
        job = session.get(Job, event.job_id)
        if job is None or job.integration_id != event.integration_id:
            raise IngestionRejected("job_integration_mismatch")
        event_id = session.scalar(insert(IngestedEvent).values(
            integration_id=event.integration_id, deduplication_key=event.event_id,
            event_type=f"attempt.{event.state}", schema_version=1,
            occurred_at=event.occurred_at, payload=payload, payload_hash=digest,
            canonicalization_version="execution-json-v1", redaction_version="allowlisted-fields-v1",
        ).on_conflict_do_nothing(index_elements=["integration_id", "deduplication_key"])
          .returning(IngestedEvent.id))
        if event_id is not None:
            return Receipt(event_id, False)
        existing = session.scalar(select(IngestedEvent).where(
            IngestedEvent.integration_id == event.integration_id,
            IngestedEvent.deduplication_key == event.event_id,
        ))
        if (existing.payload_hash != digest or existing.payload != payload
                or existing.canonicalization_version != "execution-json-v1"):
            raise IngestionRejected("event_id_content_conflict")
        return Receipt(existing.id, True)


def process(bind, event_id: UUID) -> ProcessingResult:
    """Retry pending/failed observations; commit domain writes and processing state together.

    Unexpected/database failures roll back this transaction and leave receipt durable.
    Known configuration failures are recorded without retaining exception text.
    """
    with Session(bind) as session, session.begin():
        stored = session.scalar(select(IngestedEvent).where(
            IngestedEvent.id == event_id).with_for_update())
        if stored is None:
            raise IngestionRejected("event_not_found")
        if stored.processing_state == "processed":
            return ProcessingResult(stored.id, "processed", stored.processing_error)
        if stored.canonicalization_version != "execution-json-v1":
            stored.processing_state = "failed"
            stored.processing_error = "unsupported_event_contract"
            return ProcessingResult(stored.id, "failed", stored.processing_error)
        event = ExecutionEvent.model_validate(stored.payload)
        integration = session.scalar(select(Integration).where(
            Integration.id == event.integration_id).with_for_update(read=True))
        job = session.get(Job, event.job_id)
        if integration is None or not integration.enabled:
            stored.processing_state, stored.processing_error = "failed", "integration_unavailable"
        elif job is None or job.integration_id != event.integration_id:
            stored.processing_state, stored.processing_error = "failed", "job_integration_mismatch"
        else:
            # Upsert + row lock serializes concurrent deliveries for this logical run.
            session.execute(insert(Run).values(job_id=event.job_id, external_run_id=event.external_run_id)
                            .on_conflict_do_nothing(index_elements=["job_id", "external_run_id"]))
            run = session.scalar(select(Run).where(
                Run.job_id == event.job_id, Run.external_run_id == event.external_run_id,
            ).with_for_update())
            attempts = list(session.scalars(select(Attempt).where(Attempt.run_id == run.id)))
            if any(a.attempt_key != "job" for a in attempts):
                stored.processing_state, stored.processing_error = "failed", "unsupported_attempt_scope"
            else:
                attempt = next((a for a in attempts if a.attempt_number == event.attempt_number), None)
                if attempt is None:
                    attempt = Attempt(run_id=run.id, attempt_key="job", attempt_number=event.attempt_number,
                                      state="unknown", reconciliation_required=False)
                    session.add(attempt)
                    attempts.append(attempt)
                _apply(attempt, event)
                latest = max(attempts, key=lambda a: a.attempt_number)
                run.state = latest.state
                run.reconciliation_required = any(a.reconciliation_required for a in attempts)
                starts = [a.started_at for a in attempts if a.started_at is not None]
                run.started_at = min(starts) if starts else None
                run.finished_at = latest.finished_at if latest.state in TERMINAL else None
                stored.processing_state = "processed"
                stored.processing_error = "reconciliation_required" if attempt.reconciliation_required else None
                stored.processed_at = datetime.now(timezone.utc)
        session.flush()
        return ProcessingResult(stored.id, stored.processing_state, stored.processing_error)


TERMINAL = {"succeeded", "failed", "cancelled"}


def _apply(attempt: Attempt, event: ExecutionEvent) -> None:
    if event.state == "running":
        if attempt.started_at is not None and attempt.started_at != event.occurred_at:
            attempt.reconciliation_required = True
        attempt.started_at = min(attempt.started_at, event.occurred_at) if attempt.started_at else event.occurred_at
        if attempt.state not in TERMINAL and not attempt.reconciliation_required:
            attempt.state = "running"
    else:
        if attempt.state in TERMINAL and attempt.state != event.state:
            attempt.reconciliation_required = True
        if attempt.finished_at is not None and attempt.finished_at != event.occurred_at:
            attempt.reconciliation_required = True
        if attempt.finished_at is None or event.occurred_at < attempt.finished_at:
            attempt.finished_at = event.occurred_at
        if event.state == "failed":
            code = event.error_code or "unknown"
            if attempt.error_code is not None and attempt.error_code != code:
                attempt.reconciliation_required = True
                attempt.error_code = "unknown"
            elif attempt.error_code is None:
                attempt.error_code = code
        if not attempt.reconciliation_required:
            attempt.state = event.state
    if (attempt.started_at is not None and attempt.finished_at is not None
            and attempt.started_at > attempt.finished_at):
        attempt.reconciliation_required = True
    if attempt.reconciliation_required:
        attempt.state = "unknown"
