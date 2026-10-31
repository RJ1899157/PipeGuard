"""Serialized, replay-safe incident evaluation. Silence is never recovery evidence."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from pipeguard.db.models import (
    IngestedEvent, Integration, Job, Run, MonitorPolicy, Observation, Incident,
    IncidentHistory, MonitorHeartbeat, LineageEvent, LineageRun, LineageExpectation,
)
from pipeguard.ingestion.service import IngestionRejected
from pipeguard.ingestion.contracts import ExecutionEvent


def _lock_job(session, job_id):
    # Transaction-scoped lock permits serialization without granting UPDATE on job identity.
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": "pipeguard-detector:" + str(job_id)})


def now_utc():
    return datetime.now(timezone.utc)


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def observe(session, job_id, source, kind, payload, occurred_at, key=None):
    key = key or digest({"kind": kind, "payload": payload})
    record_id = session.scalar(insert(Observation).values(
        job_id=job_id, source=source, kind=kind, payload=payload, occurred_at=occurred_at,
        deduplication_key=key).on_conflict_do_nothing(
            index_elements=["job_id", "source", "deduplication_key"]).returning(Observation.id))
    previous = session.scalar(select(Observation).where(
        Observation.job_id == job_id, Observation.source == source, Observation.deduplication_key == key))
    if previous.payload != payload or previous.kind != kind:
        raise IngestionRejected("event_id_content_conflict")
    return previous, record_id is None


def receive_quality(bind, report):
    conflict = False
    with Session(bind) as session, session.begin():
        job = session.get(Job, report.job_id)
        integration = session.get(Integration, report.integration_id)
        if not job or job.integration_id != report.integration_id or not integration or not integration.enabled:
            raise IngestionRejected("job_integration_mismatch")
        payload = report.model_dump(mode="json")
        previous = session.scalar(select(Observation).where(
            Observation.job_id == job.id, Observation.source == "quality",
            Observation.deduplication_key == report.event_id))
        # Serialize receipt with other quality deliveries and detector work.
        _lock_job(session, job.id)
        try:
            row, replayed = observe(session, job.id, "quality", "quality_report", payload,
                                    report.occurred_at, report.event_id)
        except IngestionRejected:
            conflict = True
            observe(session, job.id, "receipt", "delivery_conflict",
                    {"existing_observation_id": str(previous.id) if previous else "unknown",
                     "submitted_hash": digest(payload)}, now_utc())
        if not conflict:
            result = {"event_id": str(row.id), "replayed": replayed,
                      "processing_state": "received", "warning": None}
    if conflict:
        raise IngestionRejected("event_id_content_conflict")
    return result


def _history(session, incident, action, key, evidence, occurred_at, actor="detector-v1"):
    session.execute(insert(IncidentHistory).values(
        incident_id=incident.id, action=action, evidence_key=key, evidence=evidence,
        occurred_at=occurred_at, actor=actor).on_conflict_do_nothing(
            index_elements=["incident_id", "evidence_key", "action"]))


def _condition(session, policy, condition, subject, bad, recovery, at, severity="critical"):
    """bad/recovery contain stable evidence keys + provenance. Recovery must be explicit."""
    cached = session.info.get("job_incidents")
    incident = cached.get((condition, subject)) if cached is not None else session.scalar(select(Incident).where(
        Incident.job_id == policy.job_id, Incident.condition == condition, Incident.subject == subject))
    if not bad and incident is None:
        return
    if incident is None:
        incident = Incident(job_id=policy.job_id, condition=condition, subject=subject,
                            policy_version=policy.version, severity=severity, state="open", last_evaluated_at=at)
        session.add(incident)
        session.flush()
        if cached is not None:
            cached[(condition, subject)] = incident
        _history(session, incident, "opened", bad[0][0], bad[0][1], at)
    for key, evidence in bad:
        _history(session, incident, "observed", key, evidence, at)
    desired = "resolved" if recovery else "open"
    # No evidence is not sufficient to reopen an old issue or resolve a current one.
    if desired == "open" and not bad:
        return
    if incident.state != desired:
        evidence = recovery if recovery else bad[-1]
        # State comparison is serialized by the per-job transaction lock. Replay cannot
        # add transitions; a genuinely later reopening needs a distinct immutable history row.
        transition_key = "transition:" + str(uuid4())
        _history(session, incident, desired, transition_key, evidence[1], at)
        incident.state = desired
    incident.last_evaluated_at = at


def _ref(row, table):
    return (f"{table}:{row.id}", {"table": table, "id": str(row.id)})


def evaluate_job(bind, job_id, *, at=None):
    at = at or now_utc()
    with Session(bind) as session, session.begin():
        _lock_job(session, job_id)
        policy = session.scalar(select(MonitorPolicy).where(MonitorPolicy.job_id == job_id))
        if policy is None:
            return
        job = session.get(Job, job_id)
        integration = session.get(Integration, job.integration_id)
        session.info["job_incidents"] = {(i.condition, i.subject): i for i in session.scalars(
            select(Incident).where(Incident.job_id == job_id))}
        if not integration.enabled:
            # Disabling the producer must never silently close existing incidents.
            _condition(session, policy, "monitoring_disabled", "job",
                       [("integration-disabled", {"integration_id": str(integration.id)})], None, at)
            return
        # Scan receipts grow every polling cycle. Evaluation only uses the latest scan;
        # older immutable receipts remain available to history references and snapshots.
        latest_scan = select(Observation.id).where(Observation.job_id == job_id,
            Observation.kind == "source_scan").order_by(Observation.created_at.desc(),
                Observation.occurred_at.desc(), Observation.id.desc()).limit(1).correlate(None).scalar_subquery()
        observations = list(session.scalars(select(Observation).where(Observation.job_id == job_id,
            or_(Observation.kind != "source_scan", Observation.id == latest_scan))
                                           .order_by(Observation.created_at, Observation.occurred_at, Observation.id)))
        events = list(session.scalars(select(IngestedEvent).where(
            IngestedEvent.integration_id == job.integration_id,
            IngestedEvent.payload["job_id"].as_string() == str(job_id))))
        runs = {run.external_run_id: run for run in session.scalars(select(Run).where(Run.job_id == job_id))}
        # Detect failures from source evidence too, including events that failed projection.
        facts = {}
        for event in events:
            try:
                p = ExecutionEvent.model_validate(event.payload).model_dump(mode="json")
            except ValidationError:
                # Retain processing failure/backlog provenance without interpreting invalid source fields.
                continue
            if p.get("external_run_id") and p.get("attempt_number"):
                facts.setdefault(p["external_run_id"], []).append({
                    "attempt": p["attempt_number"], "state": p["state"], "time": event.occurred_at,
                    "ref": _ref(event, "ingested_events"), "source": "producer", "error_code": p.get("error_code")})
        for row in observations:
            if row.kind == "airflow_attempt":
                p = row.payload
                facts.setdefault(p["external_run_id"], []).append({
                    "attempt": p["attempt_number"], "state": p["state"], "time": row.occurred_at,
                    "ref": _ref(row, "observations"), "source": "airflow", "error_code": None})
        reports_by_run = {}
        for report in observations:
            if report.kind == "quality_report":
                reports_by_run.setdefault(report.payload["external_run_id"], []).append(report)
        for run_id, reports in reports_by_run.items():
            execution = facts.get(run_id, [])
            attempts_with_execution = {e["attempt"] for e in execution}
            missing = [r for r in reports if r.payload["attempt_number"] not in attempts_with_execution]
            recovery_refs = {e["attempt"]: e["ref"][1] for e in execution}
            _condition(session, policy, "execution_evidence_missing", run_id,
                       [_ref(report, "observations") for report in missing],
                       ("execution:" + run_id, {"evidence": list(recovery_refs.values())}) if not missing else None, at)
            # A report for a later attempt does not borrow an earlier attempt's execution.
            # Keep its uncertainty visible until that exact attempt's source evidence arrives.
            for report in missing:
                facts.setdefault(run_id, []).append({"attempt": report.payload["attempt_number"], "state": "unknown",
                    "time": report.occurred_at, "ref": _ref(report, "observations"),
                    "source": "quality_only", "error_code": None})
        dag_facts = {}
        for row in observations:
            if row.kind == "airflow_run":
                dag_facts.setdefault(row.payload["external_run_id"], []).append(row)
        for run_id, rows in dag_facts.items():
            bad = [_ref(r, "observations") for r in rows if r.payload["state"] == "failed"]
            latest_dag = rows[-1]
            _condition(session, policy, "orchestrator_run_failure", run_id, bad,
                       _ref(latest_dag, "observations") if latest_dag.payload["state"] == "succeeded" else None, at)
        configurations = [o for o in observations if o.kind == "source_configuration"]
        if configurations and policy.expected_interval_seconds:
            current = configurations[-1]
            _condition(session, policy, "scheduled_source_paused", "job",
                       [_ref(o, "observations") for o in configurations if o.payload["is_paused"]],
                       _ref(current, "observations") if not current.payload["is_paused"] else None, at)
        inventories = [o for o in observations if o.kind == "quality_report" and o.payload["inventory_complete"]]
        if inventories:
            baseline = {c["rule_id"] for c in inventories[0].payload["checks"]}
            changed = [o for o in inventories if {c["rule_id"] for c in o.payload["checks"]} != baseline]
            current = inventories[-1]
            _condition(session, policy, "quality_inventory_changed", "job", [_ref(o, "observations") for o in changed],
                       _ref(current, "observations") if {c["rule_id"] for c in current.payload["checks"]} == baseline else None, at, "warning")
        source_status = [o for o in observations if o.kind == "source_scan"]
        current_scan = source_status[-1] if source_status else None
        source_good = bool(current_scan and current_scan.payload["status"] == "complete"
                           and at - current_scan.occurred_at <= timedelta(seconds=90))
        if policy.airflow_dag_id:
            bad = [] if source_good else [(_ref(current_scan, "observations") if current_scan else
                                          ("no-source-scan", {"policy_id": str(policy.id)}))]
            _condition(session, policy, "source_coverage", "job", bad,
                       _ref(current_scan, "observations") if source_good else None, at)
        for run_id, entries in sorted(facts.items()):
            future = [e["ref"] for e in entries if e["time"] > at + timedelta(seconds=60)]
            _condition(session, policy, "clock_skew", run_id, future, None, at, "warning")
            entries_by_attempt = {}
            for entry in entries:
                entries_by_attempt.setdefault(entry["attempt"], []).append(entry)
            max_attempt = max(entries_by_attempt)
            numbers = set(entries_by_attempt)
            missing_count = max_attempt - len(numbers)
            _condition(session, policy, "attempt_history_gap", run_id,
                       [(f"attempt-gap:{run_id}:{max_attempt}:{len(numbers)}",
                         {"highest_attempt": max_attempt, "observed_attempts": len(numbers), "missing_count": missing_count})]
                       if missing_count else [],
                       (f"attempt-history:{run_id}:{max_attempt}", {"highest_attempt": max_attempt}) if not missing_count else None, at, "warning")
            latest = entries_by_attempt[max_attempt]
            terminals = {e["state"] for e in latest if e["state"] in {"succeeded", "failed", "cancelled", "blocked", "skipped"}}
            all_conflicts = []
            for values in entries_by_attempt.values():
                outcomes = {e["state"] for e in values if e["state"] in {"succeeded", "failed", "cancelled", "blocked", "skipped"}}
                if len(outcomes) > 1:
                    all_conflicts.extend(e["ref"] for e in values)
            # Timestamp conflicts within the producer are also projection uncertainty.
            run = runs.get(run_id)
            if run and run.reconciliation_required:
                all_conflicts.append(_ref(run, "runs"))
            _condition(session, policy, "conflicting_evidence", run_id, all_conflicts, None, at)
            failures = [(e["ref"][0], e["ref"][1] | {"state": e["state"], "error_code": e["error_code"],
                        "attempt": e["attempt"], "source": e["source"]})
                        for e in entries if e["state"] in {"failed", "cancelled", "blocked"}]
            successes = [e for e in latest if e["state"] == "succeeded"]
            recovery = successes[-1]["ref"] if successes and terminals == {"succeeded"} and not all_conflicts and not future else None
            _condition(session, policy, "execution_failure", run_id, failures, recovery, at)
            unknown = [e["ref"] for e in latest if e["state"] == "unknown"]
            _condition(session, policy, "unknown_execution_state", run_id, unknown,
                       recovery if recovery else None, at, "warning")
            # Last evidence does not renew the timeout: use earliest observation of the current try.
            start = min(e["time"] for e in latest)
            stale = not terminals and at >= start + timedelta(seconds=policy.timeout_seconds)
            _condition(session, policy, "missing_terminal", run_id,
                       [(f"timeout:{run_id}:{max_attempt}", {"attempt": max_attempt, "basis": latest[0]["ref"][1],
                         "deadline": (start + timedelta(seconds=policy.timeout_seconds)).isoformat()})] if stale else [],
                       latest[-1]["ref"] if terminals and not all_conflicts and not future else None, at)
            reports = reports_by_run.get(run_id, [])
            checks = {}
            for report in reports:
                for check in report.payload["checks"]:
                    checks.setdefault((check["rule_id"], check["rule_version"]), []).append((report, check))
            for (rule, version), values in checks.items():
                # An older failed try delivered late must not reopen a recovered incident.
                values.sort(key=lambda rc: (rc[0].payload["attempt_number"], rc[0].occurred_at, str(rc[0].id)))
                last_report, last_check = values[-1]
                contradictory = len({c["status"] for r, c in values
                                     if r.payload["attempt_number"] == last_report.payload["attempt_number"]}) > 1
                bad_checks = [_ref(r, "observations") for r, c in values if c["status"] != "pass"]
                recovered = _ref(last_report, "observations") if last_check["status"] == "pass" and not contradictory and last_report.occurred_at <= at + timedelta(seconds=60) else None
                _condition(session, policy, "quality_failure", run_id + ":" + digest([rule, version]),
                           bad_checks, recovered, at)
                if contradictory:
                    _condition(session, policy, "quality_conflict", run_id + ":" + digest([rule, version]),
                               [_ref(r, "observations") for r, _ in values], None, at)
            latest_reports = [o for o in reports if o.payload["attempt_number"] == max_attempt]
            complete = [o for o in latest_reports if o.payload["inventory_complete"]]
            quality_due = bool(terminals) and at >= max(e["time"] for e in latest) + timedelta(seconds=policy.timeout_seconds)
            if policy.quality_required:
                _condition(session, policy, "quality_missing", run_id,
                           [(f"quality-due:{run_id}:{max_attempt}", {"attempt": max_attempt})]
                           if quality_due and not complete else [],
                           _ref(complete[-1], "observations") if complete else None, at)
        lineage_rows = list(session.execute(select(LineageEvent, LineageRun).join(LineageRun).where(LineageRun.job_id == job_id)
                                            .order_by(LineageEvent.occurred_at, LineageEvent.created_at, LineageEvent.id)))
        lineage_by_run = {}
        for event, binding in lineage_rows:
            lineage_by_run.setdefault(binding.external_run_id, []).append((event, binding))
        for run_id, values in lineage_by_run.items():
            highest = max([b.attempt_number for _, b in values] + [e["attempt"] for e in facts.get(run_id, [])])
            latest_steps = {}
            for event, binding in values:
                if binding.attempt_number == highest:
                    latest_steps[binding.id] = event
            failures = [("lineage_events:" + str(e.id), {"table": "lineage_events", "id": str(e.id)})
                        for e, _ in values if e.payload["coverage"] == "partial"]
            outcomes = {}
            for event, binding in values:
                if event.event_type in {"COMPLETE", "FAIL", "ABORT"}:
                    outcomes.setdefault(binding.id, []).append(event)
            for binding_id, terminal_events in outcomes.items():
                contradictory = len({e.event_type for e in terminal_events}) > 1
                _condition(session, policy, "lineage_conflict", run_id + ":" + str(binding_id),
                           [("lineage_events:" + str(e.id), {"table": "lineage_events", "id": str(e.id)}) for e in terminal_events]
                           if contradictory else [], None, at)
            from pipeguard.lineage.completeness import missing_metadata
            latest_payloads = [e.payload for e,b in values if b.attempt_number == highest]
            completeness_gaps = missing_metadata(latest_payloads)
            if any(digest(e.payload) != e.payload_hash for e,b in values if b.attempt_number == highest):
                completeness_gaps.add("source_hash_mismatch")
            if completeness_gaps and not failures:
                basis_event = values[-1][0]
                failures = [("lineage-inventory:" + digest([str(basis_event.id), highest, sorted(completeness_gaps)]), {"table":"lineage_events", "id":str(basis_event.id),
                                                                         "missing_metadata":sorted(completeness_gaps)})]
            complete = bool(latest_steps) and not completeness_gaps
            recovery_event = list(latest_steps.values())[-1] if complete else None
            _condition(session, policy, "lineage_partial", run_id, failures,
                       ("lineage_events:" + str(recovery_event.id), {"table": "lineage_events", "id": str(recovery_event.id)})
                       if recovery_event else None, at, "warning")
        expectation = session.scalar(select(LineageExpectation).where(LineageExpectation.job_id == job_id))
        if expectation:
            new_runs = [run for run in runs.values() if run.created_at >= expectation.created_at]
            for execution in new_runs:
                entries = facts.get(execution.external_run_id, [])
                highest = max([e["attempt"] for e in entries] or [1])
                terminal_entries = [e for e in entries if e["attempt"] == highest and
                                    e["state"] in {"succeeded","failed","cancelled","blocked","skipped"}]
                values = [(e,b) for e,b in lineage_by_run.get(execution.external_run_id, []) if b.attempt_number == highest]
                from pipeguard.lineage.completeness import missing_metadata
                complete = bool(values) and not missing_metadata([e.payload for e,b in values]) and all(
                    digest(e.payload) == e.payload_hash for e,b in values)
                deadline = (max(e["time"] for e in terminal_entries) + timedelta(seconds=expectation.grace_seconds)) if terminal_entries else None
                due = bool(deadline and at >= deadline)
                _condition(session, policy, "lineage_missing", execution.external_run_id,
                           [("lineage-due:" + str(execution.id) + ":" + str(highest),
                             {"table":"runs", "id":str(execution.id), "expectation_id":str(expectation.id),
                              "deadline":deadline.isoformat()})] if due and not complete else [],
                           ("lineage_events:" + str(values[-1][0].id), {"table":"lineage_events", "id":str(values[-1][0].id)})
                           if complete else None, at, "warning")
        for row in observations:
            if row.kind == "delivery_conflict":
                _condition(session, policy, "delivery_conflict", str(row.id), [_ref(row, "observations")], None, at)
        backlog = [e for e in events if e.processing_state != "processed" and
                   (e.processing_state == "failed" or at - e.received_at >= timedelta(seconds=60))]
        processed = [e for e in events if e.processing_state == "processed"]
        _condition(session, policy, "ingestion_backlog", "job", [_ref(e, "ingested_events") for e in backlog],
                   _ref(processed[-1], "ingested_events") if not backlog and processed else None, at)
        if policy.expected_interval_seconds:
            # Watches start at creation; historical runs cannot pretend to be fresh activity.
            times = [policy.created_at] + [e["time"] for entries in facts.values() for e in entries
                                            if e["state"] in {"running", "succeeded"} and e["time"] <= at]
            last = max(times)
            missed = at >= last + timedelta(seconds=policy.expected_interval_seconds + policy.timeout_seconds)
            _condition(session, policy, "expected_run_missing", "job",
                       [("schedule:" + last.isoformat(), {"last_activity": last.isoformat()})] if missed else [],
                       ("activity:" + last.isoformat(), {"observed_activity": last.isoformat()})
                       if not missed and last > policy.created_at else None, at)


def coverage(bind, at=None):
    at = at or now_utc()
    with Session(bind) as session:
        heartbeat = session.scalar(select(MonitorHeartbeat).where(MonitorHeartbeat.name == "detector"))
        policies = {p.job_id: p for p in session.scalars(select(MonitorPolicy))}
        jobs = list(session.scalars(select(Job)))
        lineage_expected = set(session.scalars(select(LineageExpectation.job_id)))
        heartbeats = {h.name: h.completed_at for h in session.scalars(select(MonitorHeartbeat))}
        return {"detector": "fresh" if heartbeat and timedelta(0) <= at-heartbeat.completed_at < timedelta(seconds=90) else "stale",
                "last_completed_at": heartbeat.completed_at if heartbeat else None,
                "jobs": [{"job_id": str(j.id),
                    "mode": "unmonitored" if j.id not in policies else "airflow_reconciled" if policies[j.id].airflow_dag_id else "event_only",
                    "lineage_expected": j.id in lineage_expected,
                    "quality_expected": policies[j.id].quality_required if j.id in policies else None,
                    "activity_interval_seconds": policies[j.id].expected_interval_seconds if j.id in policies else None,
                    "detector_status": (
                    "unmonitored" if j.id not in policies else
                    "fresh" if "job:" + str(j.id) in heartbeats and
                    timedelta(0) <= at-heartbeats["job:" + str(j.id)] < timedelta(seconds=90) else "stale")}
                    for j in jobs],
                "unmonitored_job_ids": [str(j.id) for j in jobs if j.id not in policies],
                "notice": "Use the independent local watcher for service outages. Total host loss requires a watcher on another device."}
