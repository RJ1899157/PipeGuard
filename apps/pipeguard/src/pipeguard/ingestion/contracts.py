"""Version 1 job-attempt observations; arbitrary payloads and log text are excluded."""
from datetime import timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/@+\-]*$")]
ErrorCode = Literal["connection_timeout", "source_unavailable", "validation_failed", "execution_error", "unknown"]


class ExecutionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal[1] = 1
    event_id: Identifier
    integration_id: UUID
    job_id: UUID
    external_run_id: Identifier
    attempt_number: Annotated[int, Field(strict=True, ge=1, le=2147483647)]
    state: Literal["running", "succeeded", "failed", "cancelled"]
    occurred_at: AwareDatetime
    error_code: ErrorCode | None = None

    @field_validator("schema_version", mode="before")
    @classmethod
    def exact_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("Only integer schema version 1 is supported")
        return value

    @field_validator("occurred_at")
    @classmethod
    def utc_time(cls, value):
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def error_requires_failure(self):
        if self.error_code is not None and self.state != "failed":
            raise ValueError("error_code is only valid for a failed attempt")
        return self
