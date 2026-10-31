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


def test_quality_failure_without_execution_still_opens_quality_incident(migrated_database):
    c,_=migrated_database;ids=setup(c)
    receive_quality(c,report(ids,'orphan',1,'fail'))
    evaluate_job(c,ids[1],at=T+timedelta(seconds=3))
    conditions={r.condition for r in incidents(c,ids[1]) if r.state=='open'}
    assert conditions >= {'quality_failure','execution_evidence_missing'}


def test_attempt_gap_is_visible_and_late_history_recovers_coverage(migrated_database):
    c,_=migrated_database;ids=setup(c)
    send(c,event(ids,'retry',attempt=2,state='succeeded',seconds=2))
    evaluate_job(c,ids[1],at=T+timedelta(seconds=3))
    assert any(r.condition=='attempt_history_gap' and r.state=='open' for r in incidents(c,ids[1]))
    send(c,event(ids,'late-failure',state='failed',seconds=1))
    evaluate_job(c,ids[1],at=T+timedelta(seconds=4))
    states={r.condition:r.state for r in incidents(c,ids[1])}
    assert states['attempt_history_gap']=='resolved' and states['execution_failure']=='resolved'


def test_changed_inventory_is_visible_even_when_remaining_rules_pass(migrated_database):
    c,_=migrated_database;ids=setup(c)
    receive_quality(c,report(ids,'first',1,'pass'))
    changed=report(ids,'changed',2,'pass').model_dump(mode='json')
    changed['checks'][0]['rule_id']='different.check'
    receive_quality(c,QualityReport.model_validate(changed))
    evaluate_job(c,ids[1],at=T+timedelta(seconds=4))
    assert any(r.condition=='quality_inventory_changed' and r.state=='open' for r in incidents(c,ids[1]))


def test_source_projection_handles_lost_terminal_then_late_producer(migrated_database):
    from pipeguard.detection.projection import reconcile
    from pipeguard.db.models import Run,Attempt
    c,_=migrated_database;ids=setup(c)
    send(c,event(ids))
    snapshots=[(T+timedelta(seconds=2),dict(external_run_id='run',attempt_number=1,state='failed',
                  started_at=T.isoformat(),finished_at=(T+timedelta(seconds=2)).isoformat()))]
    reconcile(c,ids[1],snapshots)
    with Session(c) as s:
        attempt=s.scalar(select(Attempt).join(Run).where(Run.job_id==ids[1]))
        assert attempt.state=='failed' and attempt.projection_source=='airflow' and attempt.error_code=='unknown'
    # A late start with a different workload boundary does not fabricate a timestamp conflict.
    send(c,event(ids,'late-start',seconds=1))
    send(c,event(ids,'late-terminal',state='failed',seconds=3))
    reconcile(c,ids[1],snapshots)
    with Session(c) as s:
        attempt=s.scalar(select(Attempt).join(Run).where(Run.job_id==ids[1]))
        assert attempt.state=='failed' and attempt.projection_source=='producer'
        assert attempt.finished_at==T+timedelta(seconds=3) and not attempt.reconciliation_required


@pytest.mark.parametrize('state',['queued','running','waiting','skipped','blocked','cancelled','unknown'])
def test_source_only_states_create_explicit_execution_history(migrated_database,state):
    from pipeguard.detection.projection import reconcile
    from pipeguard.db.models import Run,Attempt
    c,_=migrated_database;ids=setup(c)
    reconcile(c,ids[1],[(T,dict(external_run_id='source-only',attempt_number=1,state=state,
                                started_at=T.isoformat(),finished_at=None))])
    with Session(c) as s:
        run=s.scalar(select(Run).where(Run.job_id==ids[1]))
        assert run.state==state
        assert s.scalar(select(Attempt).where(Attempt.run_id==run.id)).projection_source=='airflow'


def test_source_disagreement_does_not_erase_producer_evidence(migrated_database):
    from pipeguard.detection.projection import reconcile
    from pipeguard.db.models import Run
    c,_=migrated_database;ids=setup(c)
    receipt=send(c,event(ids,'success',state='succeeded'))
    reconcile(c,ids[1],[(T,dict(external_run_id='run',attempt_number=1,state='failed',started_at=None,finished_at=T.isoformat()))])
    with Session(c) as s:
        run=s.scalar(select(Run).where(Run.job_id==ids[1]))
        assert run.reconciliation_required and run.state=='unknown'
        assert s.get(IngestedEvent,receipt.event_id).payload['state']=='succeeded'


def test_concurrent_evaluators_do_not_duplicate_incident_or_history(migrated_database):
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import create_engine
    c,_=migrated_database;ids=setup(c)
    send(c,event(ids,state='failed'));c.commit()
    schema=c.scalar(text('SELECT current_schema()'));c.commit()
    engine=create_engine(os.environ['PIPEGUARD_DATABASE_URL'],hide_parameters=True,
                         connect_args={'options':f'-csearch_path={schema} -clock_timeout=5000'})
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _:evaluate_job(engine,ids[1],at=T+timedelta(seconds=2)),range(8)))
        with Session(c) as s:
            rows=list(s.scalars(select(Incident).where(Incident.job_id==ids[1])))
            assert len(rows)==1
            assert s.scalar(select(func.count()).select_from(IncidentHistory).where(IncidentHistory.incident_id==rows[0].id))==2
    finally:engine.dispose()


def test_future_clock_and_disabled_integration_are_not_healthy(migrated_database):
    c,_=migrated_database;ids=setup(c)
    send(c,event(ids,seconds=3600))
    evaluate_job(c,ids[1],at=T)
    assert any(r.condition=='clock_skew' for r in incidents(c,ids[1]))
    with Session(c) as s,s.begin():s.get(Integration,ids[0]).enabled=False
    evaluate_job(c,ids[1],at=T+timedelta(seconds=1))
    assert any(r.condition=='monitoring_disabled' and r.state=='open' for r in incidents(c,ids[1]))


def test_expected_run_missing_boundary_and_explicit_activity(migrated_database):
    c,_=migrated_database;ids=setup(c,expected_interval_seconds=60)
    with Session(c) as s:created=s.scalar(select(MonitorPolicy.created_at).where(MonitorPolicy.job_id==ids[1]))
    evaluate_job(c,ids[1],at=created+timedelta(seconds=119))
    assert incidents(c,ids[1])==[]
    evaluate_job(c,ids[1],at=created+timedelta(seconds=120))
    assert any(r.condition=='expected_run_missing' and r.state=='open' for r in incidents(c,ids[1]))
    data=event(ids)|{'occurred_at':(created+timedelta(seconds=121)).isoformat()}
    send(c,data);evaluate_job(c,ids[1],at=created+timedelta(seconds=122))
    assert next(r for r in incidents(c,ids[1]) if r.condition=='expected_run_missing').state=='resolved'


def test_detector_crash_rolls_back_incident_and_heartbeat_does_not_advance(migrated_database,monkeypatch):
    import pipeguard.detection.service as service
    c,_=migrated_database;ids=setup(c)
    send(c,event(ids,state='failed'))
    def crash(*args,**kwargs):raise RuntimeError('injected_detector_crash')
    monkeypatch.setattr(service,'_history',crash)
    with pytest.raises(RuntimeError):cycle(c)
    assert incidents(c,ids[1])==[]
    assert coverage(c)['detector']=='stale'


def test_combined_execution_quality_and_source_failure_matrix(migrated_database):
    from itertools import product
    c,_=migrated_database
    for execution,quality,source,replay in product(('succeeded','failed','running'),('pass','fail','unknown'),('complete','incomplete'),(False,True)):
        ids=setup(c,airflow_dag_id='dag',airflow_task_id='task')
        data=event(ids,state=execution)
        send(c,data)
        if replay:send(c,data)
        receive_quality(c,report(ids,'quality',1,quality))
        with Session(c) as s,s.begin():
            observe(s,ids[1],'airflow','source_scan',{'status':source},T,key='scan')
        evaluate_job(c,ids[1],at=T+timedelta(seconds=2))
        open_conditions={r.condition for r in incidents(c,ids[1]) if r.state=='open'}
        assert ('execution_failure' in open_conditions)==(execution=='failed')
        assert ('quality_failure' in open_conditions)==(quality!='pass')
        assert ('source_coverage' in open_conditions)==(source!='complete')


def test_one_broken_job_does_not_starve_other_jobs(migrated_database,monkeypatch):
    import pipeguard.detection.worker as worker
    c,_=migrated_database;bad=setup(c);good=setup(c)
    send(c,event(good,state='failed'))
    original=worker._job_cycle
    def broken(bind,client,policy):
        if policy.job_id==bad[1]:raise RuntimeError('controlled_broken_job')
        return original(bind,client,policy)
    monkeypatch.setattr(worker,'_job_cycle',broken)
    with pytest.raises(RuntimeError,match='incomplete'):worker.cycle(c)
    assert any(r.condition=='execution_failure' for r in incidents(c,good[1]))
    statuses={row['job_id']:row['detector_status'] for row in coverage(c)['jobs']}
    assert statuses[str(bad[1])]=='stale' and statuses[str(good[1])]=='fresh'
    assert coverage(c)['detector']=='stale'


def test_worker_retains_partial_failure_evidence_when_source_scan_fails(migrated_database):
    from pipeguard.detection.airflow import SourceUnavailable
    c,_=migrated_database;ids=setup(c,airflow_dag_id='dag',airflow_task_id='task')
    class Partial:
        run_facts=[]
        partial=[(T,dict(external_run_id='partial',attempt_number=1,state='failed',started_at=None,finished_at=T.isoformat()))]
        def scan(self,*args):raise SourceUnavailable('source_incomplete_history')
    cycle(c,Partial())
    conditions={r.condition for r in incidents(c,ids[1]) if r.state=='open'}
    assert conditions >= {'source_coverage','execution_failure'}
    assert coverage(c)['detector']=='fresh'


def test_disappearing_previously_seen_source_history_is_a_coverage_fault(migrated_database):
    c,_=migrated_database;ids=setup(c,airflow_dag_id='dag',airflow_task_id='task')
    class Source:
        is_paused=False;run_facts=[]
        values=[(T,dict(external_run_id='seen',attempt_number=1,state='succeeded',started_at=T.isoformat(),finished_at=T.isoformat()))]
        def scan(self,*args):return self.values
    client=Source();cycle(c,client)
    client.values=[];cycle(c,client)
    assert any(r.condition=='source_coverage' and r.state=='open' for r in incidents(c,ids[1]))


def test_invalid_stored_contract_does_not_poison_pending_queue(migrated_database):
    c,_=migrated_database;ids=setup(c)
    with Session(c) as s,s.begin():
        bad=IngestedEvent(integration_id=ids[0],deduplication_key='invalid',event_type='attempt.failed',schema_version=1,
                          occurred_at=T,payload={'job_id':str(ids[1]),'external_run_id':'bad-near-valid','attempt_number':1},payload_hash='a'*64,
                          canonicalization_version='execution-json-v1',redaction_version='allowlisted-fields-v1')
        s.add(bad);s.flush();bad_id=bad.id
    good=receive(c,event(ids))
    cycle(c)
    with Session(c) as s:
        assert s.get(IngestedEvent,bad_id).processing_error=='invalid_stored_event'
        assert s.get(IngestedEvent,good.event_id).processing_state=='processed'
    assert any(r.condition=='ingestion_backlog' for r in incidents(c,ids[1]))


def test_failed_dag_with_skipped_task_is_not_a_success(migrated_database):
    c,_=migrated_database;ids=setup(c)
    with Session(c) as s,s.begin():
        observe(s,ids[1],'airflow','airflow_run',{'external_run_id':'dag-failure','state':'failed'},T)
        observe(s,ids[1],'airflow','airflow_attempt',{'external_run_id':'dag-failure','attempt_number':1,'state':'skipped'},T)
    evaluate_job(c,ids[1],at=T+timedelta(seconds=2))
    assert any(r.condition=='orchestrator_run_failure' and r.state=='open' for r in incidents(c,ids[1]))
    assert not any(r.condition=='execution_failure' for r in incidents(c,ids[1]))


def test_repeated_reopen_and_recovery_preserve_every_lifecycle_transition(migrated_database):
    c,_=migrated_database;ids=setup(c)
    send(c,event(ids,'failure',state='failed',seconds=1))
    evaluate_job(c,ids[1],at=T+timedelta(seconds=2))
    for number in range(2,5):
        send(c,event(ids,'start-'+str(number),attempt=number,state='running',seconds=number*10))
        evaluate_job(c,ids[1],at=T+timedelta(seconds=number*10))
        send(c,event(ids,'success-'+str(number),attempt=number,state='succeeded',seconds=number*10+1))
        evaluate_job(c,ids[1],at=T+timedelta(seconds=number*10+2))
    incident=next(i for i in incidents(c,ids[1]) if i.condition=='execution_failure')
    with Session(c) as s:
        actions=list(s.scalars(select(IncidentHistory.action).where(IncidentHistory.incident_id==incident.id)))
    assert actions.count('opened')==1 and actions.count('open')==2 and actions.count('resolved')==3
    assert actions.count('observed')==1 and incident.state=='resolved'


def test_source_pause_recovery_and_recurrence_keep_each_episode(migrated_database):
    c, _ = migrated_database
    ids = setup(c, airflow_dag_id='dag', airflow_task_id='task', expected_interval_seconds=60)

    class Source:
        is_paused = False
        run_facts = []
        def scan(self, *args):
            return []

    source = Source()
    for paused, expected in [(False, None), (True, 'open'), (False, 'resolved'),
                             (True, 'open'), (False, 'resolved')]:
        source.is_paused = paused
        for _ in range(2):
            cycle(c, source)
        matches = [i for i in incidents(c, ids[1]) if i.condition == 'scheduled_source_paused']
        assert (matches[0].state if matches else None) == expected
    with Session(c) as s:
        configs = list(s.scalars(select(Observation).where(Observation.job_id == ids[1],
            Observation.kind == 'source_configuration').order_by(Observation.created_at)))
        assert [o.payload['is_paused'] for o in configs] == [False, True, False, True, False]
        history = list(s.scalars(select(IncidentHistory.action).where(IncidentHistory.incident_id == matches[0].id)))
        assert history.count('resolved') == 2 and history.count('open') == 1


@pytest.mark.parametrize('partial', [False, True])
def test_source_dag_state_recurrence_is_not_erased_by_poll_deduplication(migrated_database, partial):
    from pipeguard.detection.airflow import SourceUnavailable
    c, _ = migrated_database
    ids = setup(c, airflow_dag_id='dag', airflow_task_id='task')

    class Source:
        is_paused = False
        run_facts = []
        partial = []
        def scan(self, *args):
            if partial:
                raise SourceUnavailable('source_incomplete_history')
            return []

    source = Source()
    for index, (state, expected) in enumerate([('failed', 'open'), ('succeeded', 'resolved'),
                                              ('failed', 'open'), ('succeeded', 'resolved')]):
        source.run_facts = [(T + timedelta(seconds=index), {'external_run_id': 'same-run', 'state': state})]
        for _ in range(2):
            cycle(c, source)
        match = next(i for i in incidents(c, ids[1]) if i.condition == 'orchestrator_run_failure')
        assert match.state == expected
    # Returning to a prior state is a new episode even if the source repeats its old boundary.
    source.run_facts = [(T, {'external_run_id': 'same-run', 'state': 'failed'})]
    cycle(c, source)
    assert next(i for i in incidents(c, ids[1]) if i.condition == 'orchestrator_run_failure').state == 'open'
    with Session(c) as s:
        assert s.scalar(select(func.count()).select_from(Observation).where(
            Observation.job_id == ids[1], Observation.kind == 'airflow_run')) == 5


def test_quality_attempt_needs_its_own_execution_and_explicit_recovery(migrated_database):
    c, _ = migrated_database
    ids = setup(c)
    send(c, event(ids, 'first-success', state='succeeded'))
    receive_quality(c, report(ids, 'first-quality', 1, 'pass'))
    receive_quality(c, report(ids, 'second-quality', 2, 'pass'))
    evaluate_job(c, ids[1], at=T + timedelta(seconds=3))
    missing = next(i for i in incidents(c, ids[1]) if i.condition == 'execution_evidence_missing')
    assert missing.state == 'open'
    assert any(i.condition == 'unknown_execution_state' and i.state == 'open' for i in incidents(c, ids[1]))
    send(c, event(ids, 'second-success', attempt=2, state='succeeded', seconds=4))
    evaluate_job(c, ids[1], at=T + timedelta(seconds=5))
    assert next(i for i in incidents(c, ids[1]) if i.condition == 'execution_evidence_missing').state == 'resolved'
    assert next(i for i in incidents(c, ids[1]) if i.condition == 'unknown_execution_state').state == 'resolved'


def test_source_scan_window_uses_latest_receipt_without_deleting_cited_history(migrated_database):
    c, _ = migrated_database
    ids = setup(c, airflow_dag_id='dag', airflow_task_id='task')
    with Session(c) as s, s.begin():
        failed, _ = observe(s, ids[1], 'airflow', 'source_scan', {'status': 'incomplete'}, T, key='bad')
        failed_id = failed.id
    evaluate_job(c, ids[1], at=T)
    for index in range(100):
        with Session(c) as s, s.begin():
            observe(s, ids[1], 'airflow', 'source_scan', {'status': 'complete'},
                    T + timedelta(seconds=1), key='good-' + str(index))
    evaluate_job(c, ids[1], at=T + timedelta(seconds=2))
    incident = next(i for i in incidents(c, ids[1]) if i.condition == 'source_coverage')
    assert incident.state == 'resolved'
    with Session(c) as s, s.begin():
        observe(s, ids[1], 'airflow', 'source_scan', {'status': 'incomplete'},
                T + timedelta(seconds=3), key='bad-again')
    evaluate_job(c, ids[1], at=T + timedelta(seconds=4))
    assert next(i for i in incidents(c, ids[1]) if i.condition == 'source_coverage').state == 'open'
    with Session(c) as s:
        assert s.scalar(select(func.count()).select_from(Observation).where(Observation.job_id == ids[1])) == 102
        assert s.get(Observation, failed_id).payload == {'status': 'incomplete'}
        assert any(h.evidence.get('id') == str(failed_id) for h in s.scalars(
            select(IncidentHistory).where(IncidentHistory.incident_id == incident.id)))
