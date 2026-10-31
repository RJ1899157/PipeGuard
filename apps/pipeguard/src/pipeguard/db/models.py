"""Initial metadata schema. Source events are separate from mutable projections."""
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer,
    MetaData, String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    })
    type_annotation_map = {datetime: DateTime(timezone=True), dict[str, Any]: JSONB}


class Record:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Integration(Record, Base):
    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("environment", "name"),)
    name: Mapped[str] = mapped_column(String(255))
    environment: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(100))
    secret_ref: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class Dataset(Record, Base):
    __tablename__ = "datasets"
    __table_args__ = (UniqueConstraint("namespace", "name"),)
    namespace: Mapped[str] = mapped_column(String(512))
    name: Mapped[str] = mapped_column(String(512))
    kind: Mapped[str] = mapped_column(String(100))


class Job(Record, Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("integration_id", "namespace", "name"),)
    integration_id: Mapped[UUID] = mapped_column(ForeignKey("integrations.id", ondelete="RESTRICT"))
    namespace: Mapped[str] = mapped_column(String(512))
    name: Mapped[str] = mapped_column(String(512))
    kind: Mapped[str] = mapped_column(String(100))


STATES = "state IN ('unknown', 'queued', 'running', 'succeeded', 'failed', 'cancelled', 'blocked', 'skipped', 'waiting')"


class Run(Record, Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("job_id", "external_run_id"),
        CheckConstraint(STATES, name="state"),
        CheckConstraint("parent_run_id IS NULL OR parent_run_id <> id", name="not_own_parent"),
        CheckConstraint("data_interval_end >= data_interval_start", name="interval_order"),
        Index("ix_runs_job_started", "job_id", "started_at"),
        Index("ix_runs_parent", "parent_run_id"),
    )
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="RESTRICT"))
    external_run_id: Mapped[str] = mapped_column(String(512))
    parent_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("runs.id", ondelete="RESTRICT"))
    state: Mapped[str] = mapped_column(String(20), server_default="unknown")
    reconciliation_required: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    data_interval_start: Mapped[datetime | None]
    data_interval_end: Mapped[datetime | None]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class Attempt(Record, Base):
    __tablename__ = "attempts"
    __table_args__ = (
        UniqueConstraint("run_id", "attempt_key", "attempt_number"),
        CheckConstraint("attempt_number >= 1", name="positive_number"),
        CheckConstraint("projection_source IN ('producer', 'airflow')", name="projection_source"),
        CheckConstraint(STATES, name="state"),
    )
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="RESTRICT"))
    attempt_key: Mapped[str] = mapped_column(String(512))
    attempt_number: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20), server_default="unknown")
    reconciliation_required: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    projection_source: Mapped[str] = mapped_column(String(20), server_default="producer")
    # Reported errors are evidence, not a verified root-cause diagnosis.
    error_code: Mapped[str | None] = mapped_column(String(255))
    error_message: Mapped[str | None] = mapped_column(Text)


class IngestedEvent(Record, Base):
    __tablename__ = "ingested_events"
    __table_args__ = (
        UniqueConstraint("integration_id", "deduplication_key"),
        CheckConstraint("schema_version >= 1", name="positive_schema_version"),
        CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_object"),
        CheckConstraint("processing_state IN ('pending', 'processed', 'failed')", name="processing_state"),
        Index("ix_events_processing_received", "processing_state", "received_at"),
    )
    integration_id: Mapped[UUID] = mapped_column(ForeignKey("integrations.id", ondelete="RESTRICT"))
    deduplication_key: Mapped[str] = mapped_column(String(512))
    event_type: Mapped[str] = mapped_column(String(100))
    schema_version: Mapped[int] = mapped_column(Integer)
    occurred_at: Mapped[datetime]
    received_at: Mapped[datetime] = mapped_column(server_default=func.now())
    payload: Mapped[dict[str, Any]]
    payload_hash: Mapped[str] = mapped_column(String(64))
    canonicalization_version: Mapped[str] = mapped_column(String(100))
    redaction_version: Mapped[str] = mapped_column(String(100))
    # Only these processing fields may change after receipt (enforced by migration).
    processing_state: Mapped[str] = mapped_column(String(20), server_default="pending")
    processing_error: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime | None]


class ProducerCredential(Record, Base):
    __tablename__ = "producer_credentials"
    __table_args__ = (
        UniqueConstraint("token_hash"),
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        Index("ix_producer_credentials_integration", "integration_id"),
    )
    integration_id: Mapped[UUID] = mapped_column(ForeignKey("integrations.id", ondelete="RESTRICT"))
    token_hash: Mapped[str] = mapped_column(String(64))
    revoked: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class MonitorPolicy(Record, Base):
    """Explicit expectations; absence of a policy is unmonitored, never healthy."""
    __tablename__ = "monitor_policies"
    __table_args__ = (
        UniqueConstraint("job_id"),
        CheckConstraint("timeout_seconds BETWEEN 1 AND 604800", name="timeout"),
        CheckConstraint("expected_interval_seconds IS NULL OR expected_interval_seconds BETWEEN 60 AND 31536000", name="interval"),
    )
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="RESTRICT"))
    version: Mapped[str] = mapped_column(String(100), server_default="detector-v1")
    timeout_seconds: Mapped[int] = mapped_column(Integer)
    expected_interval_seconds: Mapped[int | None] = mapped_column(Integer)
    quality_required: Mapped[bool] = mapped_column(Boolean)
    airflow_dag_id: Mapped[str | None] = mapped_column(String(255))
    airflow_task_id: Mapped[str | None] = mapped_column(String(255))


class Observation(Record, Base):
    """Immutable, allowlisted evidence from independent monitoring sources."""
    __tablename__ = "observations"
    __table_args__ = (
        UniqueConstraint("job_id", "source", "deduplication_key"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_object"),
        Index("ix_observations_job_time", "job_id", "occurred_at"),
    )
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="RESTRICT"))
    source: Mapped[str] = mapped_column(String(30))
    deduplication_key: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(50))
    occurred_at: Mapped[datetime]
    payload: Mapped[dict[str, Any]]


class Incident(Record, Base):
    __tablename__ = "incidents"
    __table_args__ = (
        UniqueConstraint("job_id", "condition", "subject"),
        CheckConstraint("state IN ('open', 'resolved')", name="state"),
        CheckConstraint("severity IN ('warning', 'critical')", name="severity"),
        Index("ix_incidents_state_job", "state", "job_id"),
    )
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="RESTRICT"))
    condition: Mapped[str] = mapped_column(String(60))
    subject: Mapped[str] = mapped_column(String(512))
    policy_version: Mapped[str] = mapped_column(String(100))
    severity: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(20))
    last_evaluated_at: Mapped[datetime]


class IncidentHistory(Record, Base):
    __tablename__ = "incident_history"
    __table_args__ = (UniqueConstraint("incident_id", "evidence_key", "action"),)
    incident_id: Mapped[UUID] = mapped_column(ForeignKey("incidents.id", ondelete="RESTRICT"))
    action: Mapped[str] = mapped_column(String(30))
    evidence_key: Mapped[str] = mapped_column(String(255))
    evidence: Mapped[dict[str, Any]]
    actor: Mapped[str] = mapped_column(String(50))
    occurred_at: Mapped[datetime]


class MonitorHeartbeat(Record, Base):
    __tablename__ = "monitor_heartbeats"
    __table_args__ = (UniqueConstraint("name"),)
    name: Mapped[str] = mapped_column(String(100))
    completed_at: Mapped[datetime]
