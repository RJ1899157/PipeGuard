"""Authenticated, scoped incident reads; policy creation and acknowledgement are admin-only."""
from datetime import datetime
import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import column, func, select, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from pipeguard.db.models import Job, MonitorPolicy, Incident, IncidentHistory, Observation
from pipeguard.detection.contracts import PolicyCreate, QualityReport
from pipeguard.detection.service import receive_quality, coverage, now_utc, _history
from pipeguard.api.schemas import Page
from pipeguard.ingestion.contracts import Identifier


class View(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class IncidentView(View):
    id: UUID
    job_id: UUID
    condition: str
    subject: str
    policy_version: str
    severity: str
    state: str
    created_at: datetime
    last_evaluated_at: datetime


class HistoryView(View):
    id: UUID
    action: str
    evidence_key: str
    evidence: dict
    actor: str
    occurred_at: datetime
    created_at: datetime


class ObservationView(View):
    id: UUID
    job_id: UUID
    source: str
    kind: str
    occurred_at: datetime
    created_at: datetime
    payload: dict


class QualityReportView(View):
    id: UUID
    job_id: UUID
    occurred_at: datetime
    received_at: datetime
    payload: QualityReport


class QualitySummary(View):
    report_count: int
    conflicting_rule_count: int
    has_conflicts: bool
    scope: Literal["filtered_history"] = "filtered_history"


class QualityReportPage(Page[QualityReportView]):
    summary: QualitySummary


def quality_summary(session, filters):
    """Count contradictory same-rule/version/attempt outcomes across every scoped receipt."""
    checks = func.jsonb_array_elements(Observation.payload["checks"]).table_valued(column("value", JSONB)).alias("quality_check")
    value = checks.c.value
    identity = (Observation.payload["external_run_id"].as_string(), Observation.payload["attempt_number"].as_integer(),
                value["rule_id"].as_string(), value["rule_version"].as_string())
    conflicts = select(*identity).select_from(Observation).join(checks, true()).where(*filters).group_by(*identity).having(
                func.count(func.distinct(value["status"].as_string())) > 1)
    count = session.scalar(select(func.count()).select_from(conflicts.subquery()))
    return {"report_count": session.scalar(select(func.count()).select_from(Observation).where(*filters)),
            "conflicting_rule_count": count, "has_conflicts": count > 0, "scope": "filtered_history"}


class PolicyView(View):
    id: UUID
    job_id: UUID
    version: str
    timeout_seconds: int
    expected_interval_seconds: int | None
    quality_required: bool
    airflow_dag_id: str | None
    airflow_task_id: str | None
    created_at: datetime


def install_routes(app, engine, authenticate, administrator, snapshots):
    Caller = Annotated[object, Depends(authenticate)]
    Admin = Annotated[object, Depends(administrator)]
    Limit = Annotated[int, Query(ge=1, le=100)]
    Offset = Annotated[int, Query(ge=0, le=100000)]
    Snapshot = Annotated[str | None, Query(max_length=128)]

    def job_scope(statement, principal):
        return statement if principal.admin else statement.where(Job.integration_id == principal.integration_id)

    def scoped_incident(session, incident_id, principal):
        row = session.scalar(job_scope(select(Incident).join(Job).where(Incident.id == incident_id), principal))
        if row is None:
            raise HTTPException(404, "incident_not_found")
        return row

    @app.post("/v1/quality-reports", status_code=202)
    def quality(body: QualityReport, principal: Caller):
        if not principal.admin and body.integration_id != principal.integration_id:
            raise HTTPException(403, "integration_scope_mismatch")
        return receive_quality(engine, body)

    @app.post("/v1/monitor-policies", status_code=201, response_model=PolicyView)
    def policy(body: PolicyCreate, principal: Admin):
        with Session(engine) as session, session.begin():
            if session.get(Job, body.job_id) is None:
                raise HTTPException(404, "job_not_found")
            row = MonitorPolicy(**body.model_dump())
            session.add(row)
            session.flush()
            return PolicyView.model_validate(row)

    @app.get("/v1/monitor-policies", response_model=list[PolicyView] | Page[PolicyView])
    def policies(principal: Caller, limit: Limit = 50, offset: Offset = 0, snapshot: Snapshot = None):
        if snapshot is not None:
            def load(cap):
                with Session(engine) as session:
                    return ([PolicyView.model_validate(x) for x in session.scalars(job_scope(
                        select(MonitorPolicy).join(Job), principal).order_by(MonitorPolicy.created_at, MonitorPolicy.id).limit(cap))], {})
            return snapshots.page(principal, ("policies",), snapshot, load, limit=limit, offset=offset)
        with Session(engine) as session:
            rows = session.scalars(job_scope(select(MonitorPolicy).join(Job), principal)
                                   .order_by(MonitorPolicy.created_at, MonitorPolicy.id).limit(limit).offset(offset))
            return [PolicyView.model_validate(row) for row in rows]

    @app.get("/v1/monitoring/coverage")
    def monitor_coverage(principal: Admin):
        return coverage(engine)

    @app.get("/v1/jobs/{job_id}/quality-reports", response_model=QualityReportPage)
    def quality_reports(job_id: UUID, principal: Caller, limit: Limit = 50, offset: Offset = 0,
                        external_run_id: Identifier | None = None,
                        attempt_number: Annotated[int | None, Query(ge=1, le=2147483647)] = None,
                        snapshot: Snapshot = None):
        filters = [Observation.job_id == job_id, Observation.source == "quality", Observation.kind == "quality_report"]
        if external_run_id is not None:
            filters.append(Observation.payload["external_run_id"].as_string() == external_run_id)
        if attempt_number is not None:
            filters.append(Observation.payload["attempt_number"].as_integer() == attempt_number)
        def load(cap):
            with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection, Session(connection) as session:
                check_scope(session)
                views, size = [], 0
                rows = session.scalars(select(Observation).where(*filters)
                    .order_by(Observation.created_at.desc(), Observation.id.desc()).limit(cap)
                    .execution_options(yield_per=50))
                for row in rows:
                    view = QualityReportView(id=row.id, job_id=row.job_id, occurred_at=row.occurred_at,
                        received_at=row.created_at, payload=row.payload)
                    size += len(json.dumps(view.model_dump(mode="json"), separators=(",", ":")).encode())
                    if size > snapshots.max_bytes:
                        raise HTTPException(413, "snapshot_capacity_exceeded")
                    views.append(view)
                return views, {"summary": quality_summary(session, filters)}
        def check_scope(session):
            scoped_job = session.scalar(job_scope(select(Job).where(Job.id == job_id), principal))
            if scoped_job is None:
                raise HTTPException(404, "job_not_found")
        if snapshot is not None:
            return snapshots.page(principal, ("quality", str(job_id), external_run_id, attempt_number),
                                  snapshot, load, limit=limit, offset=offset)
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection, Session(connection) as session:
            check_scope(session)
            query = select(Observation).where(*filters)
            rows = list(session.scalars(query.order_by(Observation.created_at.desc(), Observation.id.desc())
                                       .limit(limit + 1).offset(offset)))
            return QualityReportPage(items=[QualityReportView(id=row.id, job_id=row.job_id,
                occurred_at=row.occurred_at, received_at=row.created_at, payload=row.payload)
                for row in rows[:limit]], limit=limit, offset=offset, has_more=len(rows) > limit,
                summary=quality_summary(session, filters))

    @app.get("/v1/incidents", response_model=list[IncidentView] | Page[IncidentView])
    def incidents(principal: Caller, limit: Limit = 50, offset: Offset = 0, state: str | None = None,
                  snapshot: Snapshot = None):
        if state is not None and state not in ("open", "resolved"):
            raise HTTPException(422, "invalid_request")
        query = job_scope(select(Incident).join(Job), principal)
        if state:
            query = query.where(Incident.state == state)
        if snapshot is not None:
            def load(cap):
                with Session(engine) as session:
                    return ([IncidentView.model_validate(x) for x in session.scalars(query
                        .order_by(Incident.created_at.desc(), Incident.id).limit(cap))], {})
            return snapshots.page(principal, ("incidents", state), snapshot, load, limit=limit, offset=offset)
        with Session(engine) as session:
            return [IncidentView.model_validate(row) for row in session.scalars(query.order_by(
                Incident.created_at.desc(), Incident.id).limit(limit).offset(offset))]

    @app.get("/v1/incidents/{incident_id}", response_model=IncidentView)
    def detail(incident_id: UUID, principal: Caller):
        with Session(engine) as session:
            return IncidentView.model_validate(scoped_incident(session, incident_id, principal))

    @app.get("/v1/incidents/{incident_id}/history", response_model=list[HistoryView] | Page[HistoryView])
    def history(incident_id: UUID, principal: Caller, limit: Limit = 50, offset: Offset = 0,
                snapshot: Snapshot = None):
        if snapshot is not None:
            def load(cap):
                with Session(engine) as session:
                    scoped_incident(session, incident_id, principal)
                    return ([HistoryView.model_validate(x) for x in session.scalars(select(IncidentHistory)
                        .where(IncidentHistory.incident_id == incident_id)
                        .order_by(IncidentHistory.created_at, IncidentHistory.id).limit(cap))], {})
            return snapshots.page(principal, ("history", str(incident_id)), snapshot, load, limit=limit, offset=offset)
        with Session(engine) as session:
            scoped_incident(session, incident_id, principal)
            return [HistoryView.model_validate(row) for row in session.scalars(select(IncidentHistory).where(
                IncidentHistory.incident_id == incident_id).order_by(IncidentHistory.created_at, IncidentHistory.id)
                .limit(limit).offset(offset))]

    @app.post("/v1/incidents/{incident_id}/acknowledge")
    def acknowledge(incident_id: UUID, principal: Admin):
        with Session(engine) as session, session.begin():
            row = scoped_incident(session, incident_id, principal)
            # Acknowledgement never resolves an incident and is not recovery authorization.
            _history(session, row, "acknowledged", "local-admin-token", {}, now_utc(), actor="local_admin_token")
        return {"status": "acknowledged"}

    @app.get("/v1/observations/{observation_id}", response_model=ObservationView)
    def observation(observation_id: UUID, principal: Caller):
        with Session(engine) as session:
            row = session.scalar(job_scope(select(Observation).join(Job).where(Observation.id == observation_id), principal))
            if row is None:
                raise HTTPException(404, "observation_not_found")
            return ObservationView.model_validate(row)
