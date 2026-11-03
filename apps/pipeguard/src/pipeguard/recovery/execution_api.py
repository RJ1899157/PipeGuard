"""Scoped executable history and explicit administrator mutations via supervised CLI."""
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select, tuple_

from pipeguard.db.models import Incident, Job, RecoveryAction, RecoveryDispatch
from pipeguard.recovery import bridge, execution
from pipeguard.recovery.api import ConfirmRecovery, ProposeRecovery
from pipeguard.recovery.service import RecoveryRejected, transaction


class DecideAction(ConfirmRecovery):
    decision: Literal["approve", "reject", "cancel"]


def install_routes(app, engine, authenticate, administrator):
    Caller = Annotated[object, Depends(authenticate)]
    Admin = Annotated[object, Depends(administrator)]

    @app.exception_handler(bridge.WorkerUnavailable)
    async def unavailable(request, error):
        return JSONResponse({"error": "recovery_worker_unknown"}, status_code=503)

    def scoped(session, incident_id, principal, action_id=None):
        query = select(Incident).join(Job).where(Incident.id == incident_id)
        if not principal.admin:
            query = query.where(Job.integration_id == principal.integration_id)
        if session.scalar(query) is None:
            raise HTTPException(404, "incident_not_found")
        if action_id:
            action = session.get(RecoveryAction, action_id)
            if not action or action.incident_id != incident_id:
                raise HTTPException(404, "recovery_action_not_found")

    @app.get("/v1/incidents/{incident_id}/recovery-actions")
    def history(incident_id: UUID, principal: Caller,
                limit: Annotated[int, Query(ge=1, le=5)] = 5, before: UUID | None = None):
        # Scope before starting any worker; an untrusted incident ID cannot probe
        # the local configuration or another integration's executable records.
        with transaction(engine) as session:
            scoped(session, incident_id, principal)
        try:
            status = bridge.call("status")
            available = type(status.get("execution_enabled")) is bool
            enabled = status["execution_enabled"] if available else None
        except (bridge.WorkerUnavailable, RecoveryRejected):
            available, enabled = False, None
        with transaction(engine) as session:
            scoped(session, incident_id, principal)
            query = select(RecoveryAction).where(RecoveryAction.incident_id == incident_id)
            if before:
                cursor = session.get(RecoveryAction, before)
                if not cursor or cursor.incident_id != incident_id:
                    raise HTTPException(404, "recovery_action_not_found")
                query = query.where(tuple_(RecoveryAction.created_at, RecoveryAction.id) < (cursor.created_at, cursor.id))
            rows = list(session.scalars(query.order_by(RecoveryAction.created_at.desc(), RecoveryAction.id.desc()).limit(limit + 1)))
            items = []
            for action in rows[:limit]:
                execution.valid_action(action, action.payload_hash)
                intent = session.scalar(select(RecoveryDispatch).where(RecoveryDispatch.action_id == action.id))
                if intent:execution.valid_intent(session, intent)
                items.append(execution.action_view(session, action) | {"dispatch": execution.dispatch_view(session, intent) if intent else None})
            try:
                execution.current(session, incident_id)
                reason = "ready" if enabled else "recovery_execution_disabled" if available else "recovery_worker_unknown"
            except RecoveryRejected as error:
                reason = str(error)
            return {"items": items, "has_more": len(rows) > limit,
                "next_before": str(rows[limit - 1].id) if len(rows) > limit else None,
                "execution_enabled": enabled, "worker_available": available,
                "eligibility": {"can_propose": reason == "ready" and enabled is True, "reason": reason},
                "notice": "Approval and starting a run are separate actions. Source permissions and pause state are rechecked at dispatch."}

    @app.post("/v1/incidents/{incident_id}/recovery-actions")
    def propose(incident_id: UUID, body: ProposeRecovery, principal: Admin):
        with transaction(engine) as session:scoped(session, incident_id, principal)
        return bridge.call("propose", incident_id=incident_id, request_key=body.request_key)

    @app.post("/v1/incidents/{incident_id}/recovery-actions/{action_id}/decisions")
    def decide(incident_id: UUID, action_id: UUID, body: DecideAction, principal: Admin):
        with transaction(engine) as session:scoped(session, incident_id, principal, action_id)
        return bridge.call("decide", action_id=action_id, request_key=body.request_key,
                           proposal_hash=body.proposal_hash, decision=body.decision)

    @app.post("/v1/incidents/{incident_id}/recovery-actions/{action_id}/dispatch")
    def dispatch(incident_id: UUID, action_id: UUID, body: ConfirmRecovery, principal: Admin):
        with transaction(engine) as session:scoped(session, incident_id, principal, action_id)
        return bridge.call("dispatch", action_id=action_id, request_key=body.request_key, proposal_hash=body.proposal_hash)

    @app.post("/v1/incidents/{incident_id}/recovery-actions/{action_id}/reconcile")
    def reconcile(incident_id: UUID, action_id: UUID, body: ProposeRecovery, principal: Admin):
        with transaction(engine) as session:
            scoped(session, incident_id, principal, action_id)
            intent = session.scalar(select(RecoveryDispatch).where(RecoveryDispatch.action_id == action_id))
            if not intent:raise HTTPException(404, "recovery_dispatch_not_found")
            dispatch_id = intent.id
        return bridge.call("reconcile", dispatch_id=dispatch_id, request_key=body.request_key)
