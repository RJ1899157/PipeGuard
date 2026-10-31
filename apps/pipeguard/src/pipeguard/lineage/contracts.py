"""Deliberately narrow OpenLineage 2.0.2 RunEvent profile; unsupported facets are rejected."""
from datetime import timezone
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator
from pipeguard.detection.contracts import StrictModel
from pipeguard.ingestion.contracts import Identifier

SCHEMA_URL = "https://openlineage.io/spec/2-0-2/OpenLineage.json#/$defs/RunEvent"
PRODUCER = "https://github.com/RJ1899157/PipeGuard"
Name = Annotated[str, Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.:/+\-]*$")]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class DatasetRef(StrictModel):
    namespace: Annotated[str, Field(min_length=1, max_length=255)]
    name: Name

    @field_validator("namespace")
    @classmethod
    def safe_namespace(cls, value):
        # Namespace is an identity only. Never follow it or accept connection credentials/query strings.
        import re
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]*://[A-Za-z0-9._:/\-]+", value):
            raise ValueError("unsupported namespace")
        parsed = urlsplit(value)
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("unsafe namespace")
        try:
            parsed.port
        except ValueError:
            raise ValueError("unsafe port") from None
        return value


class StepRef(StrictModel):
    namespace: Name
    name: Name


class OpenLineageRun(StrictModel):
    runId: UUID


class RunEvent(StrictModel):
    eventTime: AwareDatetime
    producer: Literal[PRODUCER]
    schemaURL: Literal[SCHEMA_URL]
    eventType: Literal["START", "RUNNING", "COMPLETE", "FAIL", "ABORT", "OTHER"]
    run: OpenLineageRun
    job: StepRef
    inputs: Annotated[list[DatasetRef], Field(max_length=32)]
    outputs: Annotated[list[DatasetRef], Field(max_length=32)]

    @field_validator("eventTime")
    @classmethod
    def utc(cls, value):
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def unique_datasets(self):
        for values in (self.inputs, self.outputs):
            if len({(v.namespace, v.name) for v in values}) != len(values):
                raise ValueError("duplicate dataset")
        return self


class ArtifactHashes(StrictModel):
    manifest: Hash | None = None
    run_results: Hash | None = None


class LineageReport(StrictModel):
    schema_version: Literal[1]
    event_id: Identifier
    integration_id: UUID
    job_id: UUID
    external_run_id: Identifier
    attempt_number: Annotated[int, Field(strict=True, ge=1, le=2147483647)]
    expected_steps: Annotated[list[StepRef], Field(max_length=32)] = []
    basis: Literal["declared_dbt", "producer_reported"]
    coverage: Literal["complete", "partial"]
    missing_metadata: Annotated[list[Literal[
        "artifacts_unavailable", "artifact_mismatch", "unresolved_dependency", "unsupported_resource",
        "incomplete_results", "adapter_limit", "invalid_artifacts"]], Field(max_length=7)] = []
    artifact_hashes: ArtifactHashes = ArtifactHashes()
    event: RunEvent

    @field_validator("schema_version", mode="before")
    @classmethod
    def strict_version(cls, value):
        if type(value) is not int:
            raise ValueError("integer required")
        return value

    @model_validator(mode="after")
    def coverage_consistent(self):
        keys = [(s.namespace, s.name) for s in self.expected_steps]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate expected step")
        if keys and (self.event.job.namespace, self.event.job.name) not in keys:
            raise ValueError("step not in declared inventory")
        if (self.coverage == "partial") != bool(self.missing_metadata):
            raise ValueError("partial coverage requires reasons; complete coverage cannot have gaps")
        if len(set(self.missing_metadata)) != len(self.missing_metadata):
            raise ValueError("duplicate gap")
        return self


class ExpectationCreate(StrictModel):
    job_id: UUID
    grace_seconds: Annotated[int, Field(strict=True, ge=1, le=604800)] = 300
