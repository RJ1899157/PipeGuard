from datetime import datetime
from typing import Generic, TypeVar
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from pipeguard.ingestion.contracts import Identifier


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, hide_input_in_errors=True)


class ErrorResponse(Contract):
    error: str


class IntegrationCreate(Contract):
    name: Identifier
    environment: Identifier
    kind: Identifier


class IntegrationView(IntegrationCreate):
    id: UUID
    enabled: bool


class JobCreate(Contract):
    integration_id: UUID
    namespace: Identifier
    name: Identifier
    kind: Identifier


class JobView(JobCreate):
    id: UUID


class RunView(Contract):
    id: UUID
    job_id: UUID
    external_run_id: str
    state: str
    reconciliation_required: bool
    started_at: datetime | None
    finished_at: datetime | None


class AttemptView(Contract):
    id: UUID
    run_id: UUID
    attempt_key: str
    attempt_number: int
    state: str
    reconciliation_required: bool
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None


class EventView(Contract):
    id: UUID
    integration_id: UUID
    event_type: str
    occurred_at: datetime
    received_at: datetime
    processing_state: str
    processing_error: str | None


class CredentialIssued(Contract):
    id: UUID
    integration_id: UUID
    token: str = Field(repr=False)


class EventAccepted(Contract):
    event_id: UUID
    replayed: bool
    processing_state: str
    warning: str | None


T = TypeVar("T")


class Page(Contract, Generic[T]):
    items: list[T]
    limit: int
    offset: int
    has_more: bool
