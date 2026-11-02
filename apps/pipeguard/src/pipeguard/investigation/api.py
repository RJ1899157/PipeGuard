"""Administrators explicitly submit; producers can only read their scoped records."""
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from pipeguard.db.models import EvidenceBundle, Incident, InvestigationOutcome, InvestigationRequest, Job
from pipeguard.api.schemas import ErrorResponse
from pipeguard.investigation.core import InvestigationRejected
from pipeguard.investigation.service import start, view


class SubmitInvestigation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    request_key: UUID
    free_plan_confirmed: Literal[True]
    bundle_id: UUID | None = None

    @field_validator("free_plan_confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("explicit_free_plan_confirmation_required")
        return value


def install_routes(app, engine, authenticate, administrator):
    Caller = Annotated[object, Depends(authenticate)]
    Admin = Annotated[object, Depends(administrator)]

    def scoped(session, incident_id, principal):
        statement = select(Incident).join(Job).where(Incident.id == incident_id)
        if not principal.admin:
            statement = statement.where(Job.integration_id == principal.integration_id)
        row = session.scalar(statement)
        if row is None:
            raise HTTPException(404, "incident_not_found")
        return row

    @app.exception_handler(InvestigationRejected)
    async def rejection(request, error):
        code = str(error)
        status = (409 if code == "request_key_scope_conflict" else 404 if code == "evidence_bundle_not_found"
                  else 429 if code in {"investigation_daily_limit", "investigation_cooldown"}
                  else 503 if code in {"investigation_disabled", "investigation_busy", "investigation_pending"} else 422)
        return JSONResponse({"error": code}, status_code=status)

    @app.post("/v1/incidents/{incident_id}/investigations", responses={429: {
        "model": ErrorResponse, "description": "Local investigation admission limit"}})
    def submit(incident_id: UUID, body: SubmitInvestigation, principal: Admin):
        with Session(engine) as session:
            scoped(session, incident_id, principal)
        return start(engine, incident_id, body.request_key, bundle_id=body.bundle_id)

    @app.get("/v1/incidents/{incident_id}/investigations")
    def history(incident_id: UUID, principal: Caller,
                limit: Annotated[int, Query(ge=1, le=20)] = 20, before: UUID | None = None):
        with Session(engine) as session:
            scoped(session, incident_id, principal)
            query = select(InvestigationRequest, InvestigationOutcome).select_from(InvestigationRequest).join(EvidenceBundle).outerjoin(
                InvestigationOutcome, InvestigationOutcome.request_id == InvestigationRequest.id
            ).where(EvidenceBundle.incident_id == incident_id)
            if before:
                cursor = session.execute(select(InvestigationRequest).join(EvidenceBundle).where(
                    InvestigationRequest.id == before, EvidenceBundle.incident_id == incident_id)).scalar_one_or_none()
                if cursor is None:
                    raise HTTPException(404, "investigation_cursor_not_found")
                query = query.where(tuple_(InvestigationRequest.created_at, InvestigationRequest.id) <
                                    tuple_(cursor.created_at, cursor.id))
            rows = session.execute(query.order_by(InvestigationRequest.created_at.desc(), InvestigationRequest.id.desc())
                                   .limit(limit + 1)).all()
            return {"items": [view(request, outcome) for request, outcome in rows[:limit]],
                    "has_more": len(rows) > limit,
                    "next_before": str(rows[limit - 1][0].id) if len(rows) > limit else None}
