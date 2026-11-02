"""Append-only requests/outcomes; a lost response is never automatically regenerated."""
from datetime import datetime, timedelta, timezone
import json
import os
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from pipeguard.db.models import EvidenceBundle, InvestigationOutcome, InvestigationRequest
from pipeguard.detection.service import digest
from pipeguard.investigation.core import Investigation, InvestigationRejected, project_bundle, supported_categories
from pipeguard.investigation.groq import MODEL, PROMPT_VERSION, REQUEST_OPTIONS, SYSTEM, investigate, response_schema
from pipeguard.lineage.evidence import capture

LOCK = 714092036178
DAILY_LIMIT = 20
COOLDOWN_SECONDS = 60


def view(request, outcome):
    age = (datetime.now(timezone.utc) - request.created_at).total_seconds()
    state = outcome.state if outcome else "pending" if -30 <= age <= 120 else "unknown"
    return {"id": str(request.id), "request_key": str(request.request_key), "bundle_id": str(request.bundle_id),
            "created_at": request.created_at, "model": request.model, "prompt_version": request.prompt_version,
            "actor": request.actor, "state": state, "input_payload": request.input_payload,
            "grounding_policy_current": request.prompt_version == PROMPT_VERSION,
            "input_hash": request.input_hash, "input_integrity_valid": digest(request.input_payload) == request.input_hash,
            "outcome": outcome.payload if outcome else None, "finished_at": outcome.created_at if outcome else None,
            "notice": "Advisory, untrusted hypotheses; citations establish membership, not factual correctness. No recovery was executed."}


def existing(engine, request_key, incident_id, bundle_id=None):
    with Session(engine) as session:
        pair = session.execute(select(InvestigationRequest, EvidenceBundle).join(EvidenceBundle)
            .where(InvestigationRequest.request_key == request_key)).first()
        if not pair:
            return None
        request, bundle = pair
        if bundle.incident_id != incident_id or (bundle_id is not None and bundle.id != bundle_id):
            raise InvestigationRejected("request_key_scope_conflict")
        outcome = session.scalar(select(InvestigationOutcome).where(InvestigationOutcome.request_id == request.id))
        return view(request, outcome)


def start(engine, incident_id, request_key, *, bundle_id=None):
    replay = existing(engine, request_key, incident_id, bundle_id)
    if replay:
        return replay
    if os.environ.get("PIPEGUARD_INVESTIGATION_ENABLED") != "true" or not os.environ.get("GROQ_API_KEY"):
        raise InvestigationRejected("investigation_disabled")
    # A session lock survives commits but must never be returned locked to the pool.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as guard:
        if not guard.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK}):
            raise InvestigationRejected("investigation_busy")
        try:
            replay = existing(engine, request_key, incident_id, bundle_id)
            if replay:
                return replay
            with Session(engine) as session:
                unsettled = session.scalar(select(InvestigationRequest.id).outerjoin(InvestigationOutcome,
                    InvestigationOutcome.request_id == InvestigationRequest.id).where(InvestigationOutcome.id.is_(None),
                    InvestigationRequest.created_at >= datetime.now(timezone.utc) - timedelta(seconds=120)).limit(1))
                if unsettled:
                    raise InvestigationRejected("investigation_pending")
                cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                count, latest = session.execute(select(func.count(), func.max(InvestigationRequest.created_at))
                    .where(InvestigationRequest.created_at >= cutoff)).one()
                if count >= DAILY_LIMIT:
                    raise InvestigationRejected("investigation_daily_limit")
                if latest and (datetime.now(timezone.utc) - latest).total_seconds() < COOLDOWN_SECONDS:
                    raise InvestigationRejected("investigation_cooldown")
            if bundle_id is None:
                bundle = capture(engine, incident_id)
            else:
                with Session(engine) as session:
                    row = session.get(EvidenceBundle, bundle_id)
                    if not row or row.incident_id != incident_id:
                        raise InvestigationRejected("evidence_bundle_not_found")
                    bundle = {"id": str(row.id), "payload": row.payload, "payload_hash": row.payload_hash}
            projection_error = None
            try:
                packet, mapping = project_bundle(bundle)
            except ValueError as error:
                projection_error = str(error) if isinstance(error, InvestigationRejected) else "invalid_projection"
                packet, mapping = None, {}
            saved_input = {"bundle_hash": bundle["payload_hash"], "packet": packet, "citation_map": mapping,
                           "projection_error": projection_error, "operator_asserted_free_plan": True,
                           "response_schema_hash": digest(response_schema(packet)) if packet and supported_categories(packet) else None}
            saved_input["provider_contract"] = ({"system": SYSTEM, "response_schema": response_schema(packet),
                "request_options": REQUEST_OPTIONS} if packet and supported_categories(packet) else None)
            if len(json.dumps(saved_input, ensure_ascii=False).encode()) > 30000:
                projection_error = "investigation_audit_input_limit"
                saved_input = {"bundle_hash": bundle["payload_hash"], "packet": None, "citation_map": {},
                               "projection_error": projection_error, "operator_asserted_free_plan": True}
            with Session(engine, expire_on_commit=False) as session, session.begin():
                request = InvestigationRequest(bundle_id=UUID(bundle["id"]), request_key=request_key,
                    actor="local_administrator", model=MODEL, prompt_version=PROMPT_VERSION,
                    input_payload=saved_input, input_hash=digest(saved_input))
                session.add(request)
                session.flush()
                identity = request.id
            # The request is durable before any provider call. No transaction spans inference.
            state = "failed"
            if projection_error:
                payload = {"error": projection_error}
            elif not supported_categories(packet):
                payload, state = {"result": Investigation(abstained=True,
                    abstention_reason="The available machine facts do not support a finding under the current evidence rules.",
                    hypotheses=[], next_checks=["request_missing_evidence"]).model_dump(),
                    "provider_call_attempted": False}, "completed"
            else:
                try:
                    answer = investigate(packet, os.environ["GROQ_API_KEY"])
                    payload, state = {"result": answer.model_dump(), "provider_call_attempted": True}, "completed"
                except InvestigationRejected as error:
                    payload = {"error": str(error), "provider_call_attempted": True,
                               "diagnostic": error.diagnostic}
                except Exception:
                    payload = {"error": "provider_failed", "provider_call_attempted": True}
            with Session(engine) as session, session.begin():
                session.add(InvestigationOutcome(request_id=identity, state=state, payload=payload))
            return existing(engine, request_key, incident_id, bundle_id)
        finally:
            try:
                if not guard.scalar(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK}):
                    guard.invalidate()
            except Exception:
                guard.invalidate()
