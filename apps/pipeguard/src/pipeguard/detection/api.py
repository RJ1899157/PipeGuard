"""Authenticated, scoped incident reads; policy creation and acknowledgement are admin-only."""
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from pipeguard.db.models import Job, MonitorPolicy, Incident, IncidentHistory, Observation
from pipeguard.detection.contracts import PolicyCreate, QualityReport
from pipeguard.detection.service import receive_quality, coverage, now_utc, _history


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


def install_routes(app, engine, authenticate, administrator):
    Caller = Annotated[object, Depends(authenticate)]
    Admin = Annotated[object, Depends(administrator)]
    Limit = Annotated[int, Query(ge=1, le=100)]
    Offset = Annotated[int, Query(ge=0, le=100000)]

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

    @app.get("/v1/monitor-policies", response_model=list[PolicyView])
    def policies(principal: Caller, limit: Limit = 50, offset: Offset = 0):
        with Session(engine) as session:
            rows = session.scalars(job_scope(select(MonitorPolicy).join(Job), principal)
                                   .order_by(MonitorPolicy.created_at, MonitorPolicy.id).limit(limit).offset(offset))
            return [PolicyView.model_validate(row) for row in rows]

    @app.get("/v1/monitoring/coverage")
    def monitor_coverage(principal: Admin):
        return coverage(engine)

    @app.get("/v1/incidents", response_model=list[IncidentView])
    def incidents(principal: Caller, limit: Limit = 50, offset: Offset = 0, state: str | None = None):
        if state is not None and state not in ("open", "resolved"):
            raise HTTPException(422, "invalid_request")
        query = job_scope(select(Incident).join(Job), principal)
        if state:
            query = query.where(Incident.state == state)
        with Session(engine) as session:
            return [IncidentView.model_validate(row) for row in session.scalars(query.order_by(
                Incident.created_at.desc(), Incident.id).limit(limit).offset(offset))]

    @app.get("/v1/incidents/{incident_id}", response_model=IncidentView)
    def detail(incident_id: UUID, principal: Caller):
        with Session(engine) as session:
            return IncidentView.model_validate(scoped_incident(session, incident_id, principal))

    @app.get("/v1/incidents/{incident_id}/history", response_model=list[HistoryView])
    def history(incident_id: UUID, principal: Caller, limit: Limit = 50, offset: Offset = 0):
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
