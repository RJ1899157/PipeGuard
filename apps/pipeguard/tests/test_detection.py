from datetime import datetime, timedelta, timezone
from itertools import permutations
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import select, func, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pipeguard.db.models import (Integration, Job, Incident, IncidentHistory, Observation,
                                MonitorPolicy, IngestedEvent, MonitorHeartbeat)
from pipeguard.detection.contracts import QualityReport
from pipeguard.detection.service import evaluate_job, receive_quality, observe, coverage
from pipeguard.detection.worker import cycle
from pipeguard.ingestion.service import receive, process, IngestionRejected

T = datetime(2026, 10, 31, 10, tzinfo=timezone.utc)


def setup(connection, **policy):
    with Session(connection) as s, s.begin():
        i = Integration(name=uuid4().hex, environment="test", kind="synthetic")
        s.add(i); s.flush()
        j = Job(integration_id=i.id, namespace="test", name="orders", kind="job")
        s.add(j); s.flush()
        p = MonitorPolicy(job_id=j.id, timeout_seconds=60, quality_required=False, **policy)
        s.add(p); s.flush()
        return i.id, j.id


def event(ids, key="start", run="run", attempt=1, state="running", seconds=0):
    return dict(schema_version=1, event_id=key, integration_id=str(ids[0]), job_id=str(ids[1]),
                external_run_id=run, attempt_number=attempt, state=state,
                occurred_at=(T+timedelta(seconds=seconds)).isoformat())


def send(connection, data):
    r = receive(connection, data)
    process(connection, r.event_id)
    return r


def incidents(connection, job_id):
    with Session(connection) as s:
        return list(s.scalars(select(Incident).where(Incident.job_id == job_id)))


def report(ids, key, attempt, status, version="a"*64, complete=True):
    return QualityReport.model_validate(dict(
        schema_version=1, event_id=key, integration_id=str(ids[0]), job_id=str(ids[1]),
        external_run_id="run", attempt_number=attempt, occurred_at=(T+timedelta(seconds=attempt)).isoformat(),
        inventory_complete=complete, checks=[dict(rule_id="orders.unique", rule_version=version, status=status)]))


def test_delivery_permutations_duplicates_and_late_failure(migrated_database):
    connection, _ = migrated_database
    # All six orders, with detector runs after every delivery and exact duplicate.
    for order in permutations(range(3)):
        ids = setup(connection)
        values = [event(ids), event(ids, "failed", state="failed", seconds=1),
                  event(ids, "recovered", attempt=2, state="succeeded", seconds=2)]
        for index in order:
            for _ in range(2):
                send(connection, values[index])
                evaluate_job(connection, ids[1], at=T+timedelta(seconds=3))
        rows = incidents(connection, ids[1])
        failure = next(r for r in rows if r.condition == "execution_failure")
        assert failure.state == "resolved"
        with Session(connection) as s:
            history = list(s.scalars(select(IncidentHistory).where(IncidentHistory.incident_id == failure.id)))
            assert sorted(h.action for h in history) == ["observed", "opened", "resolved"]
            assert s.scalar(select(func.count()).select_from(IngestedEvent).where(IngestedEvent.integration_id == ids[0])) == 3


@pytest.mark.parametrize("a,b", [(a,b) for a in ("failed","succeeded","cancelled") for b in ("failed","succeeded","cancelled") if a!=b])
def test_all_contradictory_terminal_pairs_stay_open(migrated_database, a, b):
    c,_=migrated_database; ids=setup(c)
    send(c,event(ids,"one",state=a,seconds=1)); send(c,event(ids,"two",state=b,seconds=2))
    evaluate_job(c,ids[1],at=T+timedelta(seconds=10))
    assert next(r for r in incidents(c,ids[1]) if r.condition=="conflicting_evidence").state=="open"


def test_missing_terminal_exact_boundary_and_explicit_recovery(migrated_database):
    c,_=migrated_database; ids=setup(c)
    send(c,event(ids))
    evaluate_job(c,ids[1],at=T+timedelta(seconds=59))
    assert incidents(c,ids[1])==[]
    evaluate_job(c,ids[1],at=T+timedelta(seconds=60))
    assert incidents(c,ids[1])[0].state=="open"
    evaluate_job(c,ids[1],at=T+timedelta(days=1))
    assert incidents(c,ids[1])[0].state=="open"
    send(c,event(ids,"finish",state="succeeded",seconds=61))
    evaluate_job(c,ids[1],at=T+timedelta(seconds=62))
    assert incidents(c,ids[1])[0].state=="resolved"


def test_quality_fail_replay_late_delivery_version_and_conflict(migrated_database):
    c,_=migrated_database; ids=setup(c)
    send(c,event(ids,"success",attempt=2,state="succeeded",seconds=2))
    receive_quality(c,report(ids,"pass",2,"pass"))
    receive_quality(c,report(ids,"fail",1,"fail"))
    receive_quality(c,report(ids,"fail",1,"fail"))
    evaluate_job(c,ids[1],at=T+timedelta(seconds=5))
    assert next(r for r in incidents(c,ids[1]) if r.condition=="quality_failure").state=="resolved"
    receive_quality(c,report(ids,"new-version-fail",2,"fail",version="b"*64))
    evaluate_job(c,ids[1],at=T+timedelta(seconds=5))
    assert len([r for r in incidents(c,ids[1]) if r.condition=="quality_failure" and r.state=="open"])==1
    receive_quality(c,report(ids,"contradiction",2,"fail"))
    evaluate_job(c,ids[1],at=T+timedelta(seconds=5))
    assert any(r.condition=="quality_conflict" and r.state=="open" for r in incidents(c,ids[1]))


@pytest.mark.parametrize("state",["fail","error","skipped","unknown"])
def test_every_nonpass_quality_outcome_is_visible(migrated_database,state):
    c,_=migrated_database; ids=setup(c)
    send(c,event(ids,"ok",state="succeeded"))
    receive_quality(c,report(ids,"quality",1,state))
    evaluate_job(c,ids[1],at=T+timedelta(seconds=2))
    assert any(r.condition=="quality_failure" and r.state=="open" for r in incidents(c,ids[1]))


def test_quality_collision_is_durable_and_does_not_overwrite(migrated_database):
    c,_=migrated_database; ids=setup(c)
    receive_quality(c,report(ids,"quality",1,"fail"))
    with pytest.raises(IngestionRejected): receive_quality(c,report(ids,"quality",1,"pass"))
    evaluate_job(c,ids[1],at=T+timedelta(seconds=2))
    assert any(r.condition=="delivery_conflict" for r in incidents(c,ids[1]))
    assert any(r.condition=="execution_evidence_missing" for r in incidents(c,ids[1]))


def test_execution_collision_is_durable(migrated_database):
    c,_=migrated_database; ids=setup(c)
    send(c,event(ids))
    with pytest.raises(IngestionRejected): receive(c,event(ids,state="failed"))
    evaluate_job(c,ids[1],at=T+timedelta(seconds=2))
    assert any(r.condition=="delivery_conflict" for r in incidents(c,ids[1]))


def test_source_detects_failure_without_a_single_producer_event(migrated_database):
    c,_=migrated_database; ids=setup(c,airflow_dag_id="dag",airflow_task_id="task")
    with Session(c) as s,s.begin():
        observe(s,ids[1],"airflow","airflow_attempt",dict(external_run_id="lost",attempt_number=1,state="failed"),T)
    evaluate_job(c,ids[1],at=T+timedelta(seconds=2))
    rows=incidents(c,ids[1])
    assert {r.condition for r in rows} >= {"execution_failure","source_coverage"}


def test_source_outage_does_not_resolve_execution_and_recovery_is_separate(migrated_database):
    c,_=migrated_database; ids=setup(c,airflow_dag_id="dag",airflow_task_id="task")
    send(c,event(ids,state="failed"))
    evaluate_job(c,ids[1],at=T+timedelta(seconds=2))
    with Session(c) as s,s.begin():
        observe(s,ids[1],"airflow","source_scan",{"status":"complete"},T+timedelta(seconds=3),key="good")
    evaluate_job(c,ids[1],at=T+timedelta(seconds=4))
    states={r.condition:r.state for r in incidents(c,ids[1])}
    assert states["source_coverage"]=="resolved" and states["execution_failure"]=="open"
    evaluate_job(c,ids[1],at=T+timedelta(seconds=94))
    assert next(r for r in incidents(c,ids[1]) if r.condition=="source_coverage").state=="open"


def test_quality_missing_after_success_not_healthy(migrated_database):
    c,_=migrated_database; ids=setup(c)
    # Policy is immutable; use owner INSERT with the right expectation from the start.
    with Session(c) as s,s.begin():
        p=s.scalar(select(MonitorPolicy).where(MonitorPolicy.job_id==ids[1]))
        assert p.quality_required is False
    # A separate job demonstrates required quality.
    with Session(c) as s,s.begin():
        j=Job(integration_id=ids[0],namespace="test",name="required",kind="job");s.add(j);s.flush()
        s.add(MonitorPolicy(job_id=j.id,timeout_seconds=60,quality_required=True)); other=(ids[0],j.id)
    send(c,event(other,"ok",state="succeeded"))
    evaluate_job(c,other[1],at=T+timedelta(seconds=60))
    assert any(r.condition=="quality_missing" and r.state=="open" for r in incidents(c,other[1]))
    receive_quality(c,report(other,"quality",1,"pass",complete=False))
    evaluate_job(c,other[1],at=T+timedelta(seconds=62))
    assert next(r for r in incidents(c,other[1]) if r.condition=="quality_missing").state=="open"
    receive_quality(c,report(other,"quality-complete",1,"pass"))
    evaluate_job(c,other[1],at=T+timedelta(seconds=63))
    assert next(r for r in incidents(c,other[1]) if r.condition=="quality_missing").state=="resolved"


def test_history_and_policy_immutable_even_to_owner(migrated_database):
    c,_=migrated_database;ids=setup(c)
    send(c,event(ids,state="failed"));evaluate_job(c,ids[1],at=T+timedelta(seconds=2))
    with Session(c) as s,s.begin(): observe(s,ids[1],"test","safe",{},T)
    for table in ("observations","incident_history","monitor_policies"):
        for command in (f"DELETE FROM {table}",f"UPDATE {table} SET created_at=now()",f"TRUNCATE {table} CASCADE"):
            with pytest.raises(DBAPIError):
                with c.begin_nested(): c.execute(text(command))
        c.rollback()


def test_monitor_staleness_and_unmonitored_jobs(migrated_database):
    c,_=migrated_database;ids=setup(c)
    assert coverage(c,at=T)["detector"]=="stale"
    cycle(c)
    assert coverage(c)["detector"]=="fresh"
    assert coverage(c,at=datetime.now(timezone.utc)+timedelta(seconds=91))["detector"]=="stale"


def test_sigkill_after_durable_receipt_recovers_without_fabricated_success(migrated_database):
    c,_=migrated_database;ids=setup(c);c.commit()
    schema=c.scalar(text("SELECT current_schema()"));c.commit()
    script='''
import json,os,sys,time
from sqlalchemy import create_engine
from pipeguard.ingestion.service import receive
engine=create_engine(os.environ["PIPEGUARD_DATABASE_URL"],connect_args={"options":"-csearch_path="+sys.argv[1]})
receive(engine,json.loads(sys.argv[2]))
print("durable",flush=True)
time.sleep(120)
'''
    env=dict(os.environ,PYTHONPATH=str(Path('apps/pipeguard/src').resolve()))
    child=subprocess.Popen([sys.executable,"-c",script,schema,json.dumps(event(ids))],env=env,stdout=subprocess.PIPE,text=True)
    try:
        assert child.stdout.readline().strip()=="durable"
        child.kill();child.wait(timeout=5)
        assert child.returncode==-signal.SIGKILL
        cycle(c)
        evaluate_job(c,ids[1],at=T+timedelta(seconds=61))
        assert any(r.condition=="missing_terminal" and r.state=="open" for r in incidents(c,ids[1]))
        with Session(c) as s:
            assert s.scalar(select(IngestedEvent.processing_state).where(IngestedEvent.integration_id==ids[0]))=="processed"
    finally:
        if child.poll() is None: child.kill();child.wait(timeout=5)
