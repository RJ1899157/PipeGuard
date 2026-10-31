"""Transactional lineage receipt and explicitly scoped, bounded historical graph reads."""
from collections import deque

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from pipeguard.db.models import Dataset, DatasetMention, Integration, Job, LineageRun, LineageEvent
from pipeguard.detection.service import digest, observe, now_utc, _lock_job
from pipeguard.ingestion.service import IngestionRejected
from pipeguard.lineage.completeness import missing_metadata


class LineageRejected(IngestionRejected):
    pass


def receive(bind, report):
    try:
        return _receive(bind, report)
    except LineageRejected as error:
        if str(error) in {"lineage_content_conflict", "lineage_run_identity_conflict"}:
            with Session(bind) as session, session.begin():
                observe(session, report.job_id, "lineage", "delivery_conflict", {
                    "event_key_hash": digest(report.event_id),
                    "submitted_hash": digest(report.model_dump(mode="json")), "error_code": str(error)}, now_utc())
        raise


def _receive(bind, report):
    payload = report.model_dump(mode="json")
    content_hash = digest(payload)
    with Session(bind) as session, session.begin():
        integration = session.scalar(select(Integration).where(Integration.id == report.integration_id).with_for_update(read=True))
        job = session.get(Job, report.job_id)
        if not integration or not integration.enabled or not job or job.integration_id != report.integration_id:
            raise LineageRejected("job_integration_mismatch")
        _lock_job(session, job.id)
        existing = session.scalar(select(LineageEvent).where(
            LineageEvent.integration_id == report.integration_id, LineageEvent.event_key == report.event_id))
        if existing:
            if existing.payload_hash != content_hash or existing.payload != payload:
                raise LineageRejected("lineage_content_conflict")
            return {"event_id": str(existing.id), "replayed": True, "processing_state": "processed"}
        event = report.event
        identity = dict(integration_id=report.integration_id, job_id=job.id,
                        external_run_id=report.external_run_id, attempt_number=report.attempt_number,
                        run_uuid=event.run.runId, step_namespace=event.job.namespace, step_name=event.job.name)
        session.execute(insert(LineageRun).values(**identity).on_conflict_do_nothing())
        binding = session.scalar(select(LineageRun).where(
            LineageRun.integration_id == report.integration_id, LineageRun.run_uuid == event.run.runId))
        if binding is None or any(getattr(binding, key) != value for key, value in identity.items()):
            raise LineageRejected("lineage_run_identity_conflict")
        event_id = session.scalar(insert(LineageEvent).values(
            integration_id=report.integration_id, lineage_run_id=binding.id, event_key=report.event_id,
            event_type=event.eventType, occurred_at=event.eventTime, payload=payload, payload_hash=content_hash
        ).on_conflict_do_nothing(index_elements=["integration_id", "event_key"]).returning(LineageEvent.id))
        if event_id is None:
            # A different job may concurrently reuse an integration-level event key.
            existing = session.scalar(select(LineageEvent).where(
                LineageEvent.integration_id == report.integration_id, LineageEvent.event_key == report.event_id))
            if existing.payload_hash != content_hash or existing.payload != payload:
                raise LineageRejected("lineage_content_conflict")
            return {"event_id": str(existing.id), "replayed": True, "processing_state": "processed"}
        for role, values in (("input", event.inputs), ("output", event.outputs)):
            for dataset in values:
                session.execute(insert(Dataset).values(namespace=dataset.namespace, name=dataset.name, kind="reported")
                                .on_conflict_do_nothing(index_elements=["namespace", "name"]))
                dataset_id = session.scalar(select(Dataset.id).where(
                    Dataset.namespace == dataset.namespace, Dataset.name == dataset.name))
                session.add(DatasetMention(event_id=event_id, dataset_id=dataset_id, role=role))
        if report.coverage == "partial":
            observe(session, job.id, "lineage", "lineage_gap", {
                "lineage_event_id": str(event_id), "external_run_id": report.external_run_id,
                "attempt_number": report.attempt_number, "reasons": report.missing_metadata}, event.eventTime,
                key=str(event_id))
        return {"event_id": str(event_id), "replayed": False, "processing_state": "processed"}


def graph(session, job_id, *, external_run_id=None, attempt_number=None, as_of=None, known_at=None,
          root=None, direction="downstream", depth=6, max_nodes=200):
    """Observed union, not a current-state overwrite. Both event and receipt cutoffs are explicit."""
    as_of = as_of or now_utc()
    known_at = known_at or now_utc()
    query = select(LineageEvent, LineageRun).join(LineageRun).where(
        LineageRun.job_id == job_id, LineageEvent.occurred_at <= as_of, LineageEvent.created_at <= known_at)
    if external_run_id is not None:
        query = query.where(LineageRun.external_run_id == external_run_id)
    if attempt_number is not None:
        query = query.where(LineageRun.attempt_number == attempt_number)
    rows = list(session.execute(query.order_by(LineageEvent.occurred_at, LineageEvent.created_at, LineageEvent.id).limit(1001)))
    truncated = len(rows) > 1000
    rows = rows[:1000]
    event_map = {}
    nodes, links, gaps = {}, {}, set()
    outcomes = {}
    for event, run in rows:
        if digest(event.payload) != event.payload_hash:
            gaps.add("source_hash_mismatch")
            continue
        event_map[event.id] = (event, run)
        step_id = "step:" + str(run.id)
        nodes[step_id] = {"id": step_id, "kind": "step", "namespace": run.step_namespace,
                          "name": run.step_name, "external_run_id": run.external_run_id,
                          "attempt_number": run.attempt_number, "openlineage_run_id": str(run.run_uuid)}
        outcomes.setdefault(run.id, set()).add(event.event_type)
        if event.payload["coverage"] != "complete":
            gaps.update(event.payload["missing_metadata"])
    attempts = {}
    for event, run in event_map.values():
        attempts.setdefault((run.external_run_id, run.attempt_number), []).append(event.payload)
    for values in attempts.values():
        gaps.update(missing_metadata(values))
    if any(len(states & {"COMPLETE", "FAIL", "ABORT"}) > 1 for states in outcomes.values()):
        gaps.add("contradictory_run_outcomes")
    if event_map:
        mentions = session.execute(select(DatasetMention, Dataset).join(Dataset).where(
            DatasetMention.event_id.in_(list(event_map))).order_by(DatasetMention.id))
        for mention, dataset in mentions:
            event, run = event_map[mention.event_id]
            declared = event.payload["event"]["inputs" if mention.role == "input" else "outputs"]
            if {"namespace": dataset.namespace, "name": dataset.name} not in declared:
                gaps.add("projection_payload_mismatch")
                continue
            dataset_id, step_id = "dataset:" + str(dataset.id), "step:" + str(run.id)
            nodes[dataset_id] = {"id": dataset_id, "kind": "dataset", "namespace": dataset.namespace, "name": dataset.name}
            source, target = (dataset_id, step_id) if mention.role == "input" else (step_id, dataset_id)
            edge = links.setdefault((source, target), {"source": source, "target": target, "evidence": []})
            if len(edge["evidence"]) < 100:
                edge["evidence"].append({"event_id": str(event.id), "payload_hash": event.payload_hash,
                                         "basis": event.payload["basis"], "event_type": event.event_type,
                                         "occurred_at": event.occurred_at.isoformat(), "received_at": event.created_at.isoformat()})
            else:
                truncated = True
    if root is not None:
        root_key = "dataset:" + str(root)
        if root_key not in nodes:
            raise LineageRejected("lineage_scan_limit" if truncated else "dataset_not_found_in_scope")
        adjacent = {}
        for source, target in links:
            if direction in ("downstream", "both"):
                adjacent.setdefault(source, set()).add(target)
            if direction in ("upstream", "both"):
                adjacent.setdefault(target, set()).add(source)
        visited, queue = {root_key}, deque([(root_key, 0)])
        while queue:
            key, distance = queue.popleft()
            children = sorted(adjacent.get(key, ()))
            for child in children:
                if child in visited:
                    continue
                if distance >= depth or len(visited) >= max_nodes:
                    truncated = True
                    continue
                visited.add(child)
                queue.append((child, distance + 1))
        selected = visited
    else:
        selected = set(sorted(nodes)[:max_nodes])
        truncated |= len(selected) < len(nodes)
    result_links = [v for (s, t), v in sorted(links.items()) if s in selected and t in selected]
    if len(result_links) > 1000:
        truncated = True
        result_links = result_links[:1000]
    if truncated:
        gaps.add("graph_limit")
    if not rows:
        gaps.add("no_lineage_observed")
    return {"schema_version": 1, "semantics": "observed_union", "job_id": str(job_id),
            "as_of": as_of.isoformat(), "known_at": known_at.isoformat(),
            "nodes": [nodes[k] for k in sorted(selected)], "edges": result_links,
            "coverage": "partial" if gaps else "reported_complete", "missing_metadata": sorted(gaps),
            "truncated": truncated, "event_count": len(rows)}
