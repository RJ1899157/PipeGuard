"""Bounded, deterministic review-only proposals. Never contacts Airflow or AI.

An approval here is a review decision, not executable authority. A future dispatch
policy must require a fresh proposal and fresh explicit approval under that policy.
"""
from datetime import timedelta
from contextlib import contextmanager
import os
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from pipeguard.db.models import (Attempt, EvidenceBundle, Incident, IncidentHistory, IngestedEvent,
    Integration, Job, LineageEvent, LineageRun, MonitorHeartbeat, MonitorPolicy, Observation,
    RecoveryDecision, RecoveryProposal, Run)
from pipeguard.detection.service import digest
from pipeguard.lineage.evidence import capture

POLICY = "recovery_review_v1"
DAG = "pipeguard_orders"
TTL_SECONDS = 300
LOCK = 714092036179


class RecoveryRejected(ValueError):
    """Fixed public rejection code, without raw evidence or credentials."""


def clock(session):
    return session.scalar(text("SELECT clock_timestamp()"))


@contextmanager
def transaction(engine):
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with Session(connection) as session, session.begin():
            yield session


def fresh(when, now):
    return when is not None and timedelta(0) <= now - when < timedelta(seconds=90)


def latest(session, job_id, kind):
    return session.scalar(select(Observation).where(Observation.job_id == job_id,
        Observation.source == "airflow", Observation.kind == kind)
        .order_by(Observation.created_at.desc(), Observation.occurred_at.desc(), Observation.id.desc()).limit(1))


def bounded(session, statement):
    rows = list(session.execute(statement.limit(101)).all())
    if len(rows) > 100:
        raise RecoveryRejected("recovery_evidence_limit")
    # Native UUID/timestamp values are encoded explicitly; arbitrary source text
    # contributes only to hashes and never becomes an action parameter.
    return [[str(value) if value is not None else None for value in row] for row in rows]


def snapshot(session, incident_id):
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise RecoveryRejected("incident_not_found")
    if incident.state != "open":
        raise RecoveryRejected("recovery_incident_resolved")
    if incident.condition != "execution_failure":
        raise RecoveryRejected("recovery_condition_unsupported")
    job = session.get(Job, incident.job_id)
    integration = session.get(Integration, job.integration_id)
    policy = session.scalar(select(MonitorPolicy).where(MonitorPolicy.job_id == job.id))
    if not integration.enabled:
        raise RecoveryRejected("recovery_integration_disabled")
    if os.environ.get("PIPEGUARD_RECOVERY_JOB_ID") != str(job.id) or not policy or policy.airflow_dag_id != DAG or not policy.airflow_task_id:
        raise RecoveryRejected("recovery_target_not_configured")
    now = clock(session)
    for name in ("detector", "job:" + str(job.id)):
        heartbeat = session.scalar(select(MonitorHeartbeat).where(MonitorHeartbeat.name == name))
        if not heartbeat or not fresh(heartbeat.completed_at, now):
            raise RecoveryRejected("recovery_monitor_stale")
    scan, configuration = latest(session, job.id, "source_scan"), latest(session, job.id, "source_configuration")
    if not scan or scan.payload != {"status": "complete"} or not fresh(scan.occurred_at, now) or not fresh(scan.created_at, now):
        raise RecoveryRejected("recovery_source_incomplete_or_stale")
    if (not configuration or configuration.payload.get("is_paused") is not False
            or configuration.created_at > now or configuration.occurred_at > now):
        raise RecoveryRejected("recovery_dag_paused_or_unknown")
    runs = list(session.scalars(select(Run).where(Run.job_id == job.id)
        .order_by(Run.created_at.desc(), Run.id.desc()).limit(101)))
    if len(runs) > 100:
        raise RecoveryRejected("recovery_evidence_limit")
    if not runs or runs[0].external_run_id != incident.subject:
        raise RecoveryRejected("recovery_not_latest_run")
    run = runs[0]
    if (run.state != "failed" or run.reconciliation_required or not run.finished_at or run.finished_at > now
            or (run.started_at is not None and run.started_at > now)
            or any(r.state not in {"succeeded", "failed", "cancelled", "skipped", "blocked"} or r.reconciliation_required for r in runs)):
        raise RecoveryRejected("recovery_run_unsettled")
    attempts = list(session.scalars(select(Attempt).where(Attempt.run_id == run.id)
        .order_by(Attempt.attempt_number.desc(), Attempt.id.desc()).limit(101)))
    if not attempts or len(attempts) > 100:
        raise RecoveryRejected("recovery_attempt_unavailable")
    highest = [a for a in attempts if a.attempt_number == attempts[0].attempt_number]
    if len(highest) != 1 or highest[0].state != "failed" or any(a.reconciliation_required or a.state not in {
            "succeeded", "failed", "cancelled", "skipped", "blocked"} for a in attempts):
        raise RecoveryRejected("recovery_attempt_unsettled")
    source_run = session.scalar(select(Observation).where(Observation.job_id == job.id,
        Observation.source == "airflow", Observation.kind == "airflow_run",
        Observation.payload["external_run_id"].astext == run.external_run_id)
        .order_by(Observation.created_at.desc(), Observation.occurred_at.desc(), Observation.id.desc()).limit(1))
    if (not source_run or source_run.payload.get("state") != "failed" or source_run.payload.get("dag_id") != DAG
            or source_run.occurred_at > now):
        raise RecoveryRejected("recovery_independent_failure_missing")
    events = bounded(session, select(IngestedEvent.id, IngestedEvent.payload_hash, IngestedEvent.processing_state)
        .where(IngestedEvent.integration_id == job.integration_id, IngestedEvent.payload["job_id"].astext == str(job.id))
        .order_by(IngestedEvent.id))
    if any(row[2] != "processed" for row in events):
        raise RecoveryRejected("recovery_ingestion_unsettled")
    history = bounded(session, select(IncidentHistory.id, IncidentHistory.action).where(IncidentHistory.incident_id == incident.id).order_by(IncidentHistory.id))
    observations = bounded(session, select(Observation.id).where(Observation.job_id == job.id, Observation.kind != "source_scan").order_by(Observation.id))
    lineage = bounded(session, select(LineageEvent.id, LineageEvent.payload_hash).join(LineageRun)
        .where(LineageRun.job_id == job.id).order_by(LineageEvent.id))
    fingerprint = {"policy": POLICY, "incident": [str(incident.id), incident.state, incident.condition, incident.policy_version],
        "job": str(job.id), "integration": str(integration.id), "target": [DAG, policy.airflow_task_id],
        "monitor_policy": [str(policy.id), policy.version, policy.timeout_seconds, policy.quality_required, policy.expected_interval_seconds],
        "runs": [[str(r.id), r.state, r.reconciliation_required, str(r.started_at), str(r.finished_at),
                  str(r.parent_run_id), str(r.data_interval_start), str(r.data_interval_end)] for r in runs],
        "attempts": [[str(a.id), a.state, a.reconciliation_required, a.attempt_number, a.attempt_key,
                      a.projection_source, a.error_code, str(a.started_at), str(a.finished_at)] for a in attempts],
        "events": events, "history": history, "observations": observations, "lineage": lineage,
        "source_status": scan.payload}
    return {"fingerprint": digest(fingerprint), "job_id": str(job.id), "integration_id": str(integration.id),
        "run_id": str(run.id), "attempt_id": str(highest[0].id), "attempt_number": highest[0].attempt_number,
        "dag_id": DAG, "task_id": policy.airflow_task_id}


def view(proposal, decision=None, *, now):
    valid = digest(proposal.payload) == proposal.payload_hash and (decision is None or decision.proposal_hash == proposal.payload_hash)
    state = "integrity_invalid" if not valid else "expired" if now >= proposal.expires_at else "proposed"
    if decision and valid:
        state = "review_approved" if decision.decision == "approve" else "rejected"
    return {"id": str(proposal.id), "incident_id": str(proposal.incident_id), "bundle_id": str(proposal.bundle_id),
        "request_key": str(proposal.request_key), "created_at": proposal.created_at, "expires_at": proposal.expires_at,
        "actor": proposal.actor, "payload": proposal.payload, "payload_hash": proposal.payload_hash,
        "integrity_valid": valid, "state": state, "expired": now >= proposal.expires_at,
        "can_execute": False, "decision": {"id": str(decision.id), "request_key": str(decision.request_key),
            "decision": decision.decision, "proposal_hash": decision.proposal_hash,
            "actor": decision.actor, "created_at": decision.created_at} if decision else None}


def lock(session):
    if not session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": LOCK}):
        raise RecoveryRejected("recovery_busy")


def propose(engine, incident_id, request_key):
    # A global transaction lock serializes review mutations across jobs and keys.
    # It never spans an external API call, and it confers no dispatch authority.
    with transaction(engine) as session:
        lock(session)
        previous = session.scalar(select(RecoveryProposal).where(RecoveryProposal.request_key == request_key))
        if previous:
            if previous.incident_id != incident_id:
                raise RecoveryRejected("recovery_key_scope_conflict")
            decision = session.scalar(select(RecoveryDecision).where(RecoveryDecision.proposal_id == previous.id))
            return view(previous, decision, now=clock(session))
        before = snapshot(session, incident_id)
    bundle = capture(engine, incident_id)
    payload = bundle["payload"]
    fatal_gaps = set(payload["missing_evidence"]) - {"partial_lineage", "no_lineage_observed"}
    if digest(payload) != bundle["payload_hash"] or payload.get("truncated") is not False or fatal_gaps:
        raise RecoveryRejected("recovery_evidence_incomplete")
    with transaction(engine) as session:
        lock(session)
        previous = session.scalar(select(RecoveryProposal).where(RecoveryProposal.request_key == request_key))
        if previous:
            if previous.incident_id != incident_id:
                raise RecoveryRejected("recovery_key_scope_conflict")
            decision = session.scalar(select(RecoveryDecision).where(RecoveryDecision.proposal_id == previous.id))
            return view(previous, decision, now=clock(session))
        current = snapshot(session, incident_id)
        if before != current:
            raise RecoveryRejected("recovery_evidence_changed")
        identity, now = uuid4(), clock(session)
        expires = now + timedelta(seconds=TTL_SECONDS)
        contents = {"schema_version": 1, "policy": POLICY, "mode": "review_only", "can_execute": False,
            "action": "request_sample_orders_run", "incident_id": str(incident_id), **current,
            "bundle_hash": bundle["payload_hash"], "expires_at": expires.isoformat(),
            "parameters": {"dag_id": DAG, "dag_run_id": "pipeguard-recovery-" + identity.hex},
            "impact": "A future new sample run may change the local sample warehouse. Earlier failures remain retained. This review cannot start a run."}
        proposal = RecoveryProposal(id=identity, incident_id=incident_id, bundle_id=UUID(bundle["id"]),
            request_key=request_key, actor="local_administrator", payload=contents, payload_hash=digest(contents),
            created_at=now, expires_at=expires)
        session.add(proposal)
        session.flush()
        return view(proposal, now=now)


def decide(engine, incident_id, proposal_id, request_key, proposal_hash, decision):
    with transaction(engine) as session:
        lock(session)
        proposal = session.get(RecoveryProposal, proposal_id)
        if not proposal or proposal.incident_id != incident_id:
            raise RecoveryRejected("recovery_proposal_not_found")
        existing = session.scalar(select(RecoveryDecision).where(RecoveryDecision.request_key == request_key))
        if existing:
            if existing.proposal_id != proposal_id or existing.decision != decision or existing.proposal_hash != proposal_hash:
                raise RecoveryRejected("recovery_key_scope_conflict")
            return view(proposal, existing, now=clock(session))
        if session.scalar(select(RecoveryDecision.id).where(RecoveryDecision.proposal_id == proposal_id)):
            raise RecoveryRejected("recovery_already_decided")
        if digest(proposal.payload) != proposal.payload_hash or proposal_hash != proposal.payload_hash:
            raise RecoveryRejected("recovery_hash_mismatch")
        now = clock(session)
        if decision == "approve":
            if now >= proposal.expires_at or now < proposal.created_at:
                raise RecoveryRejected("recovery_expired")
            if proposal.payload.get("policy") != POLICY or proposal.payload.get("mode") != "review_only":
                raise RecoveryRejected("recovery_policy_changed")
            if snapshot(session, incident_id)["fingerprint"] != proposal.payload["fingerprint"]:
                raise RecoveryRejected("recovery_evidence_changed")
            bundle = session.get(EvidenceBundle, proposal.bundle_id)
            if (not bundle or bundle.incident_id != incident_id or bundle.payload_hash != proposal.payload["bundle_hash"]
                    or digest(bundle.payload) != proposal.payload["bundle_hash"]):
                raise RecoveryRejected("recovery_hash_mismatch")
            now = clock(session)
            if now >= proposal.expires_at:
                raise RecoveryRejected("recovery_expired")
        row = RecoveryDecision(proposal_id=proposal_id, request_key=request_key, proposal_hash=proposal_hash,
            decision=decision, actor="local_administrator", created_at=now)
        session.add(row)
        session.flush()
        return view(proposal, row, now=now)
