"""Manual executable recovery with committed intent and read-only reconciliation.

No daemon, AI authorization or automatic retry. Old review-only approvals cannot
enter these separate tables. PostgreSQL intent is not atomic with Airflow.
"""
from contextlib import contextmanager
from datetime import timedelta
import os
from uuid import UUID, uuid4

from sqlalchemy import select, text

from pipeguard.db.models import (EvidenceBundle, Observation, RecoveryAction,
    RecoveryActionDecision, RecoveryDispatch, RecoveryDispatchEvent, Run)
from pipeguard.detection.airflow import external_id
from pipeguard.detection.service import digest
from pipeguard.lineage.evidence import capture
from pipeguard.recovery import service as review
from pipeguard.recovery.airflow import DAG, POLICY, TASK, parameters
from pipeguard.recovery.service import RecoveryRejected, transaction

LOCK = 714092036180


def enabled():
    if os.environ.get("PIPEGUARD_RECOVERY_EXECUTION_ENABLED") != "1":
        raise RecoveryRejected("recovery_execution_disabled")


@contextmanager
def serialized(engine):
    # Session lock spans committed intent and the bounded external exchange, but
    # no transaction spans that exchange. An interrupted owner never gets to retry
    # an existing intent, even if its lock/connection disappears during the POST.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as guard:
        if not guard.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK}):
            raise RecoveryRejected("recovery_busy")
        try:
            yield
        finally:
            try:
                if not guard.scalar(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK}):
                    raise RecoveryRejected("recovery_lock_lost")
            except BaseException:
                # Never return a possibly locked connection to the pool.
                guard.invalidate()
                raise


def current(session, incident_id):
    result = review.snapshot(session, incident_id)
    if result["task_id"] != TASK:
        raise RecoveryRejected("recovery_target_not_configured")
    source = session.scalar(select(Observation).where(Observation.job_id == UUID(result["job_id"]),
        Observation.source == "airflow", Observation.kind == "airflow_run",
        Observation.payload["external_run_id"].astext == session.get(Run, UUID(result["run_id"])).external_run_id)
        .order_by(Observation.created_at.desc(), Observation.occurred_at.desc(), Observation.id.desc()).limit(1))
    native = source.payload.get("dag_run_id") if source else None
    if (not isinstance(native, str) or not 1 <= len(native) <= 250
            or external_id(DAG, native, TASK) != source.payload.get("external_run_id")):
        raise RecoveryRejected("recovery_source_identity_missing")
    return result | {"source_run_id": native, "fingerprint": digest({"policy": POLICY, "evidence": result["fingerprint"]})}


def valid_action(action, proposal_hash):
    if action is None:
        raise RecoveryRejected("recovery_action_not_found")
    if action.payload_hash != proposal_hash or digest(action.payload) != proposal_hash:
        raise RecoveryRejected("recovery_hash_mismatch")
    if (action.payload.get("policy") != POLICY or action.payload.get("mode") != "executable"
            or action.payload.get("action") != "request_sample_orders_run"
            or action.payload.get("incident_id") != str(action.incident_id)
            or action.payload.get("parameters") != parameters(action.id)
            or action.payload.get("expires_at") != action.expires_at.isoformat()):
        raise RecoveryRejected("recovery_policy_changed")


def revalidate(session, action):
    valid_action(action, action.payload_hash)
    now = review.clock(session)
    if not action.created_at <= now < action.expires_at:
        raise RecoveryRejected("recovery_expired")
    target = current(session, action.incident_id)
    if any(action.payload.get(key) != value for key, value in target.items()):
        raise RecoveryRejected("recovery_evidence_changed")
    bundle = session.get(EvidenceBundle, action.bundle_id)
    if (not bundle or bundle.incident_id != action.incident_id or bundle.payload_hash != action.payload.get("bundle_hash")
            or digest(bundle.payload) != bundle.payload_hash):
        raise RecoveryRejected("recovery_hash_mismatch")
    if not action.created_at <= review.clock(session) < action.expires_at:
        raise RecoveryRejected("recovery_expired")
    return target


def action_view(session, action):
    decisions = list(session.scalars(select(RecoveryActionDecision).where(RecoveryActionDecision.action_id == action.id)
        .order_by(RecoveryActionDecision.created_at, RecoveryActionDecision.id)))
    return {"id": str(action.id), "incident_id": str(action.incident_id), "payload": action.payload,
        "payload_hash": action.payload_hash, "created_at": action.created_at, "expires_at": action.expires_at,
        "expired": review.clock(session) >= action.expires_at,
        "decisions": [{"id": str(row.id), "decision": row.decision, "created_at": row.created_at,
            "proposal_hash": row.proposal_hash, "actor": row.actor} for row in decisions]}


def propose(engine, incident_id, request_key):
    with serialized(engine):
        with transaction(engine) as session:
            old = session.scalar(select(RecoveryAction).where(RecoveryAction.request_key == request_key))
            if old:
                if old.incident_id != incident_id:
                    raise RecoveryRejected("recovery_key_scope_conflict")
                return action_view(session, old)
            enabled()
            before = current(session, incident_id)
        bundle = capture(engine, incident_id)
        body = bundle["payload"]
        if (digest(body) != bundle["payload_hash"] or body.get("truncated") is not False
                or set(body["missing_evidence"]) - {"partial_lineage", "no_lineage_observed"}):
            raise RecoveryRejected("recovery_evidence_incomplete")
        with transaction(engine) as session:
            target = current(session, incident_id)
            if target != before:
                raise RecoveryRejected("recovery_evidence_changed")
            identity, now = uuid4(), review.clock(session)
            expires = now + timedelta(seconds=review.TTL_SECONDS)
            payload = {"schema_version": 1, "policy": POLICY, "mode": "executable", "action": "request_sample_orders_run",
                "incident_id": str(incident_id), **target, "bundle_hash": bundle["payload_hash"],
                "expires_at": expires.isoformat(), "parameters": parameters(identity),
                "impact": "Starts one new local sample orders run and may change the sample warehouse. Partial changes are possible. Earlier failures remain retained. Does not unpause or clear tasks."}
            action = RecoveryAction(id=identity, incident_id=incident_id, bundle_id=UUID(bundle["id"]), request_key=request_key,
                actor="local_administrator", payload=payload, payload_hash=digest(payload), created_at=now, expires_at=expires)
            session.add(action)
            session.flush()
            return action_view(session, action)


def decide(engine, action_id, request_key, proposal_hash, decision, *, confirmed):
    if confirmed is not True or decision not in {"approve", "reject", "cancel"}:
        raise RecoveryRejected("recovery_explicit_confirmation_required")
    with serialized(engine), transaction(engine) as session:
        action = session.get(RecoveryAction, action_id)
        valid_action(action, proposal_hash)
        replay = session.scalar(select(RecoveryActionDecision).where(RecoveryActionDecision.request_key == request_key))
        if replay:
            if replay.action_id != action_id or replay.decision != decision or replay.proposal_hash != proposal_hash:
                raise RecoveryRejected("recovery_key_scope_conflict")
            return action_view(session, action)
        if session.scalar(select(RecoveryDispatch.id).where(RecoveryDispatch.action_id == action_id)):
            raise RecoveryRejected("recovery_already_dispatched")
        prior = list(session.scalars(select(RecoveryActionDecision).where(RecoveryActionDecision.action_id == action_id)))
        if any(row.decision == "cancel" for row in prior) or (decision != "cancel" and prior):
            raise RecoveryRejected("recovery_already_decided")
        if decision == "approve":
            enabled()
            revalidate(session, action)
        session.add(RecoveryActionDecision(action_id=action_id, request_key=request_key, proposal_hash=proposal_hash,
            decision=decision, actor="local_administrator", created_at=review.clock(session)))
        session.flush()
        return action_view(session, action)


def history(session, dispatch_id):
    events = list(session.scalars(select(RecoveryDispatchEvent).where(RecoveryDispatchEvent.dispatch_id == dispatch_id)
        .order_by(RecoveryDispatchEvent.sequence).limit(101)))
    if len(events) > 100:
        raise RecoveryRejected("recovery_history_limit")
    return events


def dispatch_view(session, intent):
    events = history(session, intent.id)
    return {"id": str(intent.id), "action_id": str(intent.action_id), "approval_id": str(intent.approval_id),
        "request_key": str(intent.request_key), "created_at": intent.created_at, "actor": intent.actor,
        "job_id": str(intent.job_id), "failed_run_id": str(intent.failed_run_id),
        "payload": intent.payload, "payload_hash": intent.payload_hash,
        "external_run_id": intent.external_run_id,
        "monitored_external_run_id": external_id(DAG, intent.external_run_id, TASK),
        "state": events[-1].state if events else "unknown",
        "last_known_state": next((row.state for row in reversed(events) if row.state != "unknown"), "unknown"),
        "events": [{"sequence": row.sequence, "source": row.source, "state": row.state,
            "code": row.code, "facts": row.facts, "created_at": row.created_at} for row in events],
        "notice": "An existing intent is never resubmitted. Not found is uncertain, not permission to retry."}


def intent_payload(action):
    return {"policy": POLICY, "action_id": str(action.id), "proposal_hash": action.payload_hash,
            "parameters": parameters(action.id), "job_id": action.payload["job_id"], "failed_run_id": action.payload["run_id"]}


def valid_intent(session, intent):
    action = session.get(RecoveryAction, intent.action_id)
    valid_action(action, action.payload_hash if action else "")
    approval = session.get(RecoveryActionDecision, intent.approval_id)
    if (digest(intent.payload) != intent.payload_hash or intent.payload != intent_payload(action)
            or str(intent.failed_run_id) != action.payload["run_id"] or str(intent.job_id) != action.payload["job_id"]
            or intent.external_run_id != parameters(action.id)["body"]["dag_run_id"]
            or not approval or approval.action_id != action.id or approval.decision != "approve"
            or approval.proposal_hash != action.payload_hash):
        raise RecoveryRejected("recovery_hash_mismatch")
    return action


def append_event(engine, dispatch_id, request_key, source, result):
    with transaction(engine) as session:
        intent = session.get(RecoveryDispatch, dispatch_id)
        valid_intent(session, intent)
        previous = history(session, dispatch_id)
        if len(previous) >= 100:
            raise RecoveryRejected("recovery_history_limit")
        known = {row.state for row in previous}
        contradiction = ("conflict" in known or result["state"] in {"queued", "running", "succeeded", "failed"} and "rejected" in known
            or result["state"] == "succeeded" and "failed" in known or result["state"] == "failed" and "succeeded" in known
            or result["state"] in {"queued", "running"} and bool(known & {"succeeded", "failed"}))
        if contradiction:
            result = {"state": "conflict", "code": "recovery_external_contradiction", "facts": result["facts"]}
        session.add(RecoveryDispatchEvent(dispatch_id=dispatch_id, request_key=request_key, sequence=len(previous) + 1,
            source=source, state=result["state"], code=result["code"], facts=result["facts"], created_at=review.clock(session)))
        session.flush()
        return dispatch_view(session, intent)


def dispatch(engine, action_id, request_key, proposal_hash, client, *, confirmed):
    if confirmed is not True:
        raise RecoveryRejected("recovery_explicit_confirmation_required")
    with serialized(engine):
        with transaction(engine) as session:
            action = session.get(RecoveryAction, action_id)
            valid_action(action, proposal_hash)
            key = session.scalar(select(RecoveryDispatch).where(RecoveryDispatch.request_key == request_key))
            if key and key.action_id != action_id:
                raise RecoveryRejected("recovery_key_scope_conflict")
            old = session.scalar(select(RecoveryDispatch).where(RecoveryDispatch.action_id == action_id))
            if old:
                valid_intent(session, old)
                return dispatch_view(session, old)
            enabled()
            target = revalidate(session, action)
            decisions = list(session.scalars(select(RecoveryActionDecision).where(RecoveryActionDecision.action_id == action_id)))
            approval = next((row for row in decisions if row.decision == "approve" and row.proposal_hash == proposal_hash), None)
            if not approval or any(row.decision != "approve" for row in decisions):
                raise RecoveryRejected("recovery_execution_not_approved")
            approval_id = approval.id
            prior = list(session.scalars(select(RecoveryDispatch).where(RecoveryDispatch.job_id == UUID(target["job_id"])).limit(101)))
            if len(prior) > 100:
                raise RecoveryRejected("recovery_history_limit")
            for row in prior:
                valid_intent(session, row)
                if row.failed_run_id == UUID(target["run_id"]):
                    raise RecoveryRejected("recovery_failed_run_already_reserved")
                if dispatch_view(session, row)["state"] not in {"rejected", "succeeded", "failed"}:
                    raise RecoveryRejected("recovery_prior_dispatch_unsettled")
            source_run = target["source_run_id"]
        client.preflight(source_run)
        with transaction(engine) as session:
            action = session.get(RecoveryAction, action_id)
            revalidate(session, action)
            payload = intent_payload(action)
            identity = uuid4()
            intent = RecoveryDispatch(id=identity, action_id=action_id, approval_id=approval_id,
                failed_run_id=UUID(target["run_id"]), job_id=UUID(target["job_id"]), request_key=request_key,
                actor="local_administrator", external_run_id=parameters(action_id)["body"]["dag_run_id"],
                payload=payload, payload_hash=digest(payload), created_at=review.clock(session))
            session.add(intent)
            session.flush()
        # Durable intent has committed. Any interruption after here is uncertain;
        # every later dispatch invocation returns that intent without another POST.
        try:
            client.preflight(source_run)
            with transaction(engine) as session:
                action = session.get(RecoveryAction, action_id)
                enabled()
                revalidate(session, action)
        except RecoveryRejected as error:
            return append_event(engine, identity, uuid4(), "dispatch",
                {"state": "rejected", "code": str(error), "facts": {}})
        result = client.submit(action_id)
        return append_event(engine, identity, uuid4(), "dispatch", result)


def reconcile(engine, dispatch_id, request_key, client):
    with serialized(engine):
        with transaction(engine) as session:
            intent = session.get(RecoveryDispatch, dispatch_id)
            if not intent:
                raise RecoveryRejected("recovery_dispatch_not_found")
            valid_intent(session, intent)
            replay = session.scalar(select(RecoveryDispatchEvent).where(RecoveryDispatchEvent.request_key == request_key))
            if replay:
                if replay.dispatch_id != dispatch_id or replay.source != "reconcile":
                    raise RecoveryRejected("recovery_key_scope_conflict")
                return dispatch_view(session, intent)
            if len(history(session, dispatch_id)) >= 100:
                raise RecoveryRejected("recovery_history_limit")
            action_id = intent.action_id
        return append_event(engine, dispatch_id, request_key, "reconcile", client.lookup(action_id))


def inspect(engine, action_id):
    with transaction(engine) as session:
        action = session.get(RecoveryAction, action_id)
        if action is None:
            raise RecoveryRejected("recovery_action_not_found")
        valid_action(action, action.payload_hash)
        intent = session.scalar(select(RecoveryDispatch).where(RecoveryDispatch.action_id == action_id))
        if intent:
            valid_intent(session, intent)
        return action_view(session, action) | {"dispatch": dispatch_view(session, intent) if intent else None}
