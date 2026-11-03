"""Scoped review history and administrator-only proposal/decision mutations."""
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from pipeguard.db.models import Incident, Job, RecoveryDecision, RecoveryProposal
from pipeguard.recovery.service import RecoveryRejected, clock, decide, propose, snapshot, view


class ProposeRecovery(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    request_key: UUID


class ConfirmRecovery(ProposeRecovery):
    proposal_hash: str = Field(pattern="^[0-9a-f]{64}$")
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("explicit_confirmation_required")
        return value


class DecideRecovery(ConfirmRecovery):
    decision: Literal["approve", "reject"]


def install_routes(app, engine, authenticate, administrator):
    Caller = Annotated[object, Depends(authenticate)]
    Admin = Annotated[object, Depends(administrator)]

    def scoped(session, incident_id, principal):
        query = select(Incident).join(Job).where(Incident.id == incident_id)
        if not principal.admin:
            query = query.where(Job.integration_id == principal.integration_id)
        if session.scalar(query) is None:
            raise HTTPException(404, "incident_not_found")

    @app.exception_handler(RecoveryRejected)
    async def rejection(request, error):
        code = str(error)
        return JSONResponse({"error": code}, status_code=404 if code in {
            "incident_not_found", "recovery_proposal_not_found", "recovery_action_not_found", "recovery_dispatch_not_found"} else 503 if code == "recovery_busy" else 409)

    @app.get("/v1/incidents/{incident_id}/recovery-proposals")
    def history(incident_id: UUID, principal: Caller,
                limit: Annotated[int, Query(ge=1, le=20)] = 20, before: UUID | None = None):
        # One database snapshot for history and the point-in-time eligibility view.
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
            with Session(connection) as session, session.begin():
                scoped(session, incident_id, principal)
                query = select(RecoveryProposal, RecoveryDecision).outerjoin(RecoveryDecision,
                    RecoveryDecision.proposal_id == RecoveryProposal.id).where(RecoveryProposal.incident_id == incident_id)
                if before:
                    cursor = session.get(RecoveryProposal, before)
                    if cursor is None or cursor.incident_id != incident_id:
                        raise RecoveryRejected("recovery_proposal_not_found")
                    query = query.where(tuple_(RecoveryProposal.created_at, RecoveryProposal.id) < (cursor.created_at, cursor.id))
                rows = session.execute(query.order_by(RecoveryProposal.created_at.desc(), RecoveryProposal.id.desc()).limit(limit + 1)).all()
                now = clock(session)
                try:
                    snapshot(session, incident_id)
                    eligibility = {"can_propose": True, "reason": "review_only"}
                except RecoveryRejected as error:
                    eligibility = {"can_propose": False, "reason": str(error)}
                return {"items": [view(proposal, decision, now=now) for proposal, decision in rows[:limit]],
                    "has_more": len(rows) > limit, "next_before": str(rows[limit - 1][0].id) if len(rows) > limit else None,
                    "eligibility": eligibility, "can_execute": False,
                    "notice": "Review only. Approval cannot execute recovery now or under a future execution policy."}

    @app.post("/v1/incidents/{incident_id}/recovery-proposals")
    def create(incident_id: UUID, body: ProposeRecovery, principal: Admin):
        with Session(engine) as session:
            scoped(session, incident_id, principal)
        return propose(engine, incident_id, body.request_key)

    @app.post("/v1/incidents/{incident_id}/recovery-proposals/{proposal_id}/decisions")
    def decision(incident_id: UUID, proposal_id: UUID, body: DecideRecovery, principal: Admin):
        with Session(engine) as session:
            scoped(session, incident_id, principal)
        return decide(engine, incident_id, proposal_id, body.request_key, body.proposal_hash, body.decision)
