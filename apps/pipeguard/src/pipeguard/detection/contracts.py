"""Bounded, versioned quality reports. No SQL, result rows, or free-form errors."""
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator, field_validator
from pipeguard.ingestion.contracts import Identifier


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class QualityCheck(StrictModel):
    rule_id: Identifier
    rule_version: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    status: Literal["pass", "fail", "error", "skipped", "unknown"]
    failures: Annotated[int | None, Field(strict=True, ge=0, le=2147483647)] = None


class QualityReport(StrictModel):
    schema_version: Literal[1]
    event_id: Identifier
    integration_id: UUID
    job_id: UUID
    external_run_id: Identifier
    attempt_number: Annotated[int, Field(strict=True, ge=1, le=2147483647)]
    occurred_at: AwareDatetime
    inventory_complete: bool = Field(strict=True)
    checks: Annotated[list[QualityCheck], Field(max_length=100)]

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("integer required")
        return value

    @field_validator("occurred_at")
    @classmethod
    def utc(cls, value):
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def unique_rules(self):
        if len({c.rule_id for c in self.checks}) != len(self.checks):
            raise ValueError("duplicate rule")
        if self.inventory_complete and not self.checks:
            raise ValueError("empty inventory is not complete")
        return self


class PolicyCreate(StrictModel):
    job_id: UUID
    timeout_seconds: Annotated[int, Field(strict=True, ge=1, le=604800)] = 600
    expected_interval_seconds: Annotated[int | None, Field(strict=True, ge=60, le=31536000)] = None
    quality_required: bool = Field(default=True, strict=True)
    airflow_dag_id: Identifier | None = None
    airflow_task_id: Identifier | None = None

    @model_validator(mode="after")
    def paired_source(self):
        if bool(self.airflow_dag_id) != bool(self.airflow_task_id):
            raise ValueError("source identity requires DAG and task")
        return self
