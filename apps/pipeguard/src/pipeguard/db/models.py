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


STATES = "state IN ('unknown', 'queued', 'running', 'succeeded', 'failed', 'cancelled')"


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
        CheckConstraint(STATES, name="state"),
    )
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="RESTRICT"))
    attempt_key: Mapped[str] = mapped_column(String(512))
    attempt_number: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20), server_default="unknown")
    reconciliation_required: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
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
