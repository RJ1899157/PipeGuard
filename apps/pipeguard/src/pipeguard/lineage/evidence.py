"""Immutable, bounded incident snapshots with scoped references and explicit missing evidence."""
import json
from uuid import UUID
from sqlalchemy import select, func, literal, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from pipeguard.db.models import (Attempt, EvidenceBundle, Incident, IncidentHistory, IngestedEvent,
                                Job, LineageEvent, LineageRun, MonitorPolicy, Observation, Run)
from pipeguard.detection.service import digest
from pipeguard.ingestion.contracts import ExecutionEvent
from pipeguard.detection.contracts import QualityReport
from pydantic import ValidationError


SAFE_SOURCE_ERRORS = {
    "source_authentication_failed", "source_unreachable", "source_invalid_response", "source_http_error",
    "source_response_too_large", "source_unstable_pagination", "source_incomplete_history",
    "source_unsupported_mapping", "source_missing_timestamp", "source_incomplete_pagination",
    "source_scan_limit_exceeded", "source_component_unhealthy", "source_dag_import_error",
    "source_history_disappeared", "source_not_configured"}


def _machine_summary(payload):
    result = {}
    for key, allowed in (("state", {"unknown","queued","running","waiting","succeeded","failed","cancelled","blocked","skipped"}),
                         ("status", {"complete","incomplete"}), ("error_code", SAFE_SOURCE_ERRORS)):
        value = payload.get(key)
        if isinstance(value, str) and value in allowed:
            result[key] = value
    return result


def _lineage_summary(row):
    p = row.payload
    return {"event_type": row.event_type, "lineage_run_id": str(row.lineage_run_id),
            "external_run_id": p["external_run_id"], "attempt_number": p["attempt_number"],
            "occurred_at": row.occurred_at.isoformat(), "received_at": row.created_at.isoformat(),
            "basis": p["basis"], "coverage": p["coverage"], "missing_metadata": p["missing_metadata"],
            "expected_steps": p.get("expected_steps", []), "inputs": p["event"]["inputs"],
            "outputs": p["event"]["outputs"], "artifact_hashes": p["artifact_hashes"]}


def capture(engine, incident_id):
    # Dedicated connection, stable database snapshot. No source or model calls occur here.
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with Session(connection) as session, session.begin():
            incident = session.get(Incident, incident_id)
            if incident is None:
                raise ValueError("incident_not_found")
            job = session.get(Job, incident.job_id)
            policy = session.scalar(select(MonitorPolicy).where(MonitorPolicy.job_id == job.id))
            gaps, items, seen = set(), [], set()
            size = 0

            def add(table, row, value, source_hash=None):
                nonlocal size
                key = (table, str(row.id))
                if key in seen:
                    return
                if table in {"ingested_events", "lineage_events"} and source_hash and digest(row.payload) != source_hash:
                    gaps.add("source_hash_mismatch")
                    value = {"integrity": "hash_mismatch"}
                item = {"table": table, "id": str(row.id), "content_hash": source_hash or digest(value),
                        "hash_basis": "source_content_v1" if source_hash else "summary_v1",
                        "summary": value}
                encoded_size = len(json.dumps(item, sort_keys=True).encode())
                if len(items) >= 100 or size + encoded_size > 524288:
                    gaps.add("evidence_limit")
                    return
                seen.add(key); items.append(item); size += encoded_size

            relevant = list(session.scalars(select(Run).where(Run.job_id == job.id, or_(
                Run.external_run_id == incident.subject, func.starts_with(literal(incident.subject), Run.external_run_id + ":")))
                .order_by(Run.created_at.desc(), Run.id).limit(101)))
            binding_ids = list(session.scalars(select(LineageRun.external_run_id).where(LineageRun.job_id == job.id,
                or_(LineageRun.external_run_id == incident.subject,
                    func.starts_with(literal(incident.subject), LineageRun.external_run_id + ":"))).distinct().limit(101)))
            execution_scoped = bool(relevant or binding_ids)
            external_ids = {r.external_run_id for r in relevant} | set(binding_ids)
            if execution_scoped:
                runs = relevant
            else:
                runs = list(session.scalars(select(Run).where(Run.job_id == job.id)
                            .order_by(Run.created_at.desc(), Run.id).limit(101)))
                external_ids = {r.external_run_id for r in runs[:100]}
            if len(runs) > 100 or len(binding_ids) > 100:
                gaps.add("evidence_limit")
            history = list(session.scalars(select(IncidentHistory).where(IncidentHistory.incident_id == incident.id)
                                           .order_by(IncidentHistory.created_at, IncidentHistory.id).limit(101)))
            if len(history) > 100:
                gaps.add("evidence_limit")
            for h in history[:100]:
                ref = h.evidence
                if isinstance(ref, dict) and "table" in ref and "id" in ref:
                    if ref["table"] not in {"runs", "ingested_events", "observations", "lineage_events"}:
                        gaps.add("unsupported_history_reference")
            # Resolve cited evidence before windowed job context. Old failures must survive noisy recent scans.
            def references(value):
                if isinstance(value, dict):
                    if "table" in value and "id" in value:
                        yield value
                    for nested in value.values():
                        if isinstance(nested, (dict, list)):
                            yield from references(nested)
                elif isinstance(value, list):
                    for nested in value:
                        yield from references(nested)
            for h in history[:100]:
                for ref in references(h.evidence):
                    table = ref["table"]
                    model = {"runs": Run, "ingested_events": IngestedEvent,
                             "observations": Observation, "lineage_events": LineageEvent}.get(table)
                    try:
                        row = session.get(model, UUID(str(ref["id"]))) if model else None
                    except (ValueError, TypeError):
                        row = None
                    belongs = False
                    if isinstance(row, (Run, Observation)):
                        belongs = row.job_id == job.id
                    elif isinstance(row, IngestedEvent):
                        belongs = row.integration_id == job.integration_id and row.payload.get("job_id") == str(job.id)
                    elif isinstance(row, LineageEvent):
                        binding = session.get(LineageRun, row.lineage_run_id)
                        belongs = binding.job_id == job.id
                    if not belongs:
                        gaps.add("history_reference_outside_scope_or_missing")
                        continue
                    if table == "ingested_events":
                        try:
                            value = ExecutionEvent.model_validate(row.payload).model_dump(mode="json")
                        except ValidationError:
                            value = {"contract_valid": False}; gaps.add("invalid_execution_contract")
                        add(table, row, value, row.payload_hash)
                    elif table == "observations":
                        value = {"source": row.source, "kind": row.kind, "occurred_at": row.occurred_at.isoformat(), **_machine_summary(row.payload)}
                        if row.kind == "quality_report":
                            try:
                                value["report"] = QualityReport.model_validate(row.payload).model_dump(mode="json")
                            except ValidationError:
                                gaps.add("invalid_quality_contract")
                        add(table, row, value, digest(row.payload))
                    elif table == "lineage_events":
                        add(table, row, _lineage_summary(row), row.payload_hash)
                    else:
                        add(table, row, {"external_run_id": row.external_run_id, "state": row.state,
                                         "reconciliation_required": row.reconciliation_required})
            # Cited original failures take priority over bounded recent context.
            for run in runs[:100]:
                add("runs", run, {"external_run_id": run.external_run_id, "state": run.state,
                    "reconciliation_required": run.reconciliation_required,
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None})
                attempts = list(session.scalars(select(Attempt).where(Attempt.run_id == run.id)
                                                .order_by(Attempt.attempt_number).limit(101)))
                if len(attempts) > 100:
                    gaps.add("evidence_limit")
                for a in attempts[:100]:
                    add("attempts", a, {"run_id": str(run.id), "attempt_number": a.attempt_number,
                        "state": a.state, "projection_source": a.projection_source,
                        "reconciliation_required": a.reconciliation_required})
            for h in history[:100]:
                # Never echo an arbitrary history JSON body into an AI evidence input.
                add("incident_history", h, {"action": h.action, "actor": h.actor,
                    "occurred_at": h.occurred_at.isoformat()}, digest({"action": h.action, "evidence": h.evidence,
                                                                          "evidence_key": h.evidence_key, "actor": h.actor, "occurred_at": h.occurred_at.isoformat()}))
            event_query = select(IngestedEvent).where(IngestedEvent.integration_id == job.integration_id,
                                                    IngestedEvent.payload["job_id"].astext == str(job.id))
            if execution_scoped:
                event_query = event_query.where(IngestedEvent.payload["external_run_id"].astext.in_(external_ids))
            events = list(session.scalars(event_query.order_by(IngestedEvent.received_at.desc(), IngestedEvent.id).limit(101)))
            if len(events) > 100:
                gaps.add("evidence_limit")
            for event in events[:100]:
                if execution_scoped and event.payload.get("external_run_id") not in external_ids:
                    continue
                try:
                    value = ExecutionEvent.model_validate(event.payload).model_dump(mode="json")
                except ValidationError:
                    gaps.add("invalid_execution_contract")
                    value = {"processing_state": event.processing_state, "contract_valid": False}
                add("ingested_events", event, value, event.payload_hash)
            observation_query = select(Observation).where(Observation.job_id == job.id)
            if execution_scoped:
                observation_query = observation_query.where(Observation.payload["external_run_id"].astext.in_(external_ids))
            observations = list(session.scalars(observation_query.order_by(Observation.created_at.desc(), Observation.id).limit(101)))
            if execution_scoped:
                # Latest coverage context, rather than hundreds of repeated polling receipts.
                for kind in ("source_scan", "source_configuration"):
                    row = session.scalar(select(Observation).where(Observation.job_id == job.id, Observation.kind == kind)
                                         .order_by(Observation.created_at.desc(), Observation.occurred_at.desc(), Observation.id).limit(1))
                    if row:
                        observations.append(row)
            if len(observations) > (102 if execution_scoped else 100):
                gaps.add("evidence_limit")
            for observation in observations[:102 if execution_scoped else 100]:
                p = observation.payload
                if execution_scoped and p.get("external_run_id") and p["external_run_id"] not in external_ids:
                    continue
                value = {"source": observation.source, "kind": observation.kind,
                         "occurred_at": observation.occurred_at.isoformat(), "received_at": observation.created_at.isoformat()}
                if observation.kind == "quality_report":
                    try:
                        value["report"] = QualityReport.model_validate(p).model_dump(mode="json")
                    except ValidationError:
                        gaps.add("invalid_quality_contract")
                else:
                    value.update(_machine_summary(p))
                add("observations", observation, value, digest(p))
            lineage_query = select(LineageEvent).join(LineageRun).where(LineageRun.job_id == job.id)
            if execution_scoped:
                lineage_query = lineage_query.where(LineageRun.external_run_id.in_(external_ids))
            lineage = list(session.scalars(lineage_query.order_by(LineageEvent.created_at.desc(), LineageEvent.id).limit(101)))
            if not lineage:
                gaps.add("no_lineage_observed")
            if len(lineage) > 100:
                gaps.add("evidence_limit")
            for event in lineage[:100]:
                if event.payload.get("coverage") != "complete":
                    gaps.add("partial_lineage")
                add("lineage_events", event, _lineage_summary(event), event.payload_hash)
            if not policy or not policy.airflow_dag_id:
                gaps.add("no_independent_orchestrator_source")
            # Verify every supported direct history reference resolves inside the same job/incident scope.
            for h in history[:100]:
                ref = h.evidence
                if isinstance(ref, dict) and "table" in ref and "id" in ref:
                    if (ref["table"], str(ref["id"])) not in seen:
                        gaps.add("history_reference_not_in_bundle")
            payload = {"schema_version": 1, "context_scope": "execution" if execution_scoped else "job",
                       "external_run_ids": sorted(external_ids), "incident": {"id": str(incident.id), "job_id": str(job.id),
                "condition": incident.condition, "subject": incident.subject, "state": incident.state,
                "policy_version": incident.policy_version}, "items": sorted(items, key=lambda x:(x["table"],x["id"])),
                "missing_evidence": sorted(gaps), "truncated": "evidence_limit" in gaps,
                "notice": "Stored source claims and declared dependencies are evidence, not a verified root-cause diagnosis."}
            content_hash = digest(payload)
            session.execute(insert(EvidenceBundle).values(incident_id=incident.id, payload=payload, payload_hash=content_hash)
                            .on_conflict_do_nothing(index_elements=["incident_id", "payload_hash"]))
            row = session.scalar(select(EvidenceBundle).where(EvidenceBundle.incident_id == incident.id,
                                                             EvidenceBundle.payload_hash == content_hash))
            return {"id": str(row.id), "incident_id": str(incident.id), "payload_hash": content_hash,
                    "created_at": row.created_at, "payload": payload}
