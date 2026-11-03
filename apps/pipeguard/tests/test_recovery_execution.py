"""Synthetic dispatch faults in disposable schemas; never contacts real Airflow."""
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from test_api import api, producer
from pipeguard.db.models import (Incident, MonitorHeartbeat, RecoveryActionDecision, RecoveryDispatchEvent, Run)
from pipeguard.detection.airflow import external_id
from pipeguard.detection.service import evaluate_job, observe
from pipeguard.recovery import execution, service as review
from pipeguard.recovery.airflow import DAG, TASK
from pipeguard.recovery.service import RecoveryRejected


@pytest.fixture
def target(api, monkeypatch):
    client, admin, engine, _ = api
    headers, event, _ = producer(api, 'executable-sample')
    assert client.post('/v1/monitor-policies', headers=admin, json={'job_id': event['job_id'],
        'quality_required': False, 'airflow_dag_id': DAG, 'airflow_task_id': TASK}).status_code == 201
    with engine.connect() as connection:
        now = connection.scalar(text('SELECT clock_timestamp()'))
    event |= {'state': 'failed', 'error_code': 'source_unavailable',
        'external_run_id': external_id(DAG, 'failed-original', TASK), 'occurred_at': (now-timedelta(seconds=5)).isoformat()}
    assert client.post('/v1/events', headers=headers, json=event).status_code == 202
    with Session(engine) as session, session.begin():
        for name in ('detector', 'job:'+event['job_id']):
            session.add(MonitorHeartbeat(name=name, completed_at=now))
        for kind, payload in [('source_scan', {'status': 'complete'}), ('source_configuration', {'is_paused': False}),
            ('airflow_run', {'external_run_id': event['external_run_id'], 'dag_id': DAG,
                             'dag_run_id': 'failed-original', 'state': 'failed'})]:
            observe(session, UUID(event['job_id']), 'airflow', kind, payload, now)
    evaluate_job(engine, event['job_id'])
    incident = next(row for row in client.get('/v1/incidents', headers=admin).json() if row['condition']=='execution_failure')
    monkeypatch.setenv('PIPEGUARD_RECOVERY_JOB_ID', event['job_id'])
    monkeypatch.setenv('PIPEGUARD_RECOVERY_EXECUTION_ENABLED', '1')
    return UUID(incident['id']), UUID(event['job_id'])


class Source:
    def __init__(self, *, stop=None, outcome='queued'):
        self.stop, self.outcome = stop, outcome
        self.reads = self.posts = self.lookups = 0
        self.exists = False
        self.hook = lambda: None

    def preflight(self, source_run):
        assert source_run == 'failed-original'
        self.reads += 1
        if self.stop == 'before_intent' or self.stop == 'after_intent' and self.reads == 2:
            raise SystemExit('synthetic interruption')
        if self.reads == 2:
            self.hook()

    def submit(self, action_id):
        self.posts += 1
        self.exists = True
        if self.stop == 'after_post':
            raise SystemExit('synthetic lost response')
        return {'state': self.outcome, 'code': 'synthetic_source_result', 'facts': {}}

    def lookup(self, action_id):
        self.lookups += 1
        return {'state': self.outcome if self.exists else 'unknown',
                'code': 'synthetic_source_result' if self.exists else 'recovery_external_not_found', 'facts': {}}


def proposal(api, target, key=None):
    return execution.propose(api[2], target[0], key or uuid4())


def approved(api, target):
    row = proposal(api, target)
    execution.decide(api[2], UUID(row['id']), uuid4(), row['payload_hash'], 'approve', confirmed=True)
    return row


def dispatch(api, row, source, key=None, **options):
    return execution.dispatch(api[2], UUID(row['id']), key or uuid4(), row['payload_hash'], source, confirmed=True, **options)


def test_default_disabled_and_literal_confirmation(api, target, monkeypatch):
    for flag in ('0', 'true', ''):
        monkeypatch.setenv('PIPEGUARD_RECOVERY_EXECUTION_ENABLED', flag)
        with pytest.raises(RecoveryRejected, match='execution_disabled'):
            proposal(api, target)
    monkeypatch.setenv('PIPEGUARD_RECOVERY_EXECUTION_ENABLED', '1')
    row = proposal(api, target)
    for value in (False, 1, 'true', None):
        with pytest.raises(RecoveryRejected, match='explicit_confirmation'):
            execution.decide(api[2], UUID(row['id']), uuid4(), row['payload_hash'], 'approve', confirmed=value)
        with pytest.raises(RecoveryRejected, match='explicit_confirmation'):
            execution.dispatch(api[2], UUID(row['id']), uuid4(), row['payload_hash'], Source(), confirmed=value)


def test_proposal_approval_replay_scope_and_review_separation(api, target):
    key = uuid4(); row = proposal(api, target, key)
    assert proposal(api, target, key) == row
    assert row['payload']['policy'] == 'recovery_execute_v1'
    assert row['payload']['mode'] == 'executable'
    assert 'sample warehouse' in row['payload']['impact']
    with pytest.raises(RecoveryRejected, match='key_scope_conflict'):
        execution.propose(api[2], uuid4(), key)
    with pytest.raises(RecoveryRejected, match='hash_mismatch'):
        execution.decide(api[2], UUID(row['id']), uuid4(), '0'*64, 'approve', confirmed=True)
    key = uuid4()
    first = execution.decide(api[2], UUID(row['id']), key, row['payload_hash'], 'approve', confirmed=True)
    assert execution.decide(api[2], UUID(row['id']), key, row['payload_hash'], 'approve', confirmed=True) == first
    with pytest.raises(RecoveryRejected, match='key_scope_conflict'):
        execution.decide(api[2], UUID(row['id']), key, row['payload_hash'], 'reject', confirmed=True)
    # Even a real review-only approval has no matching executable action record.
    old = review.propose(api[2], target[0], uuid4())
    review.decide(api[2], target[0], UUID(old['id']), uuid4(), old['payload_hash'], 'approve')
    with pytest.raises(RecoveryRejected, match='action_not_found'):
        dispatch(api, old, Source())


def test_approval_does_not_dispatch_and_cancel_can_withdraw_while_disabled(api, target, monkeypatch):
    row = approved(api, target)
    source = Source()
    assert execution.inspect(api[2], UUID(row['id']))['dispatch'] is None
    monkeypatch.setenv('PIPEGUARD_RECOVERY_EXECUTION_ENABLED', '0')
    execution.decide(api[2], UUID(row['id']), uuid4(), row['payload_hash'], 'cancel', confirmed=True)
    monkeypatch.setenv('PIPEGUARD_RECOVERY_EXECUTION_ENABLED', '1')
    with pytest.raises(RecoveryRejected, match='execution_not_approved'):
        dispatch(api, row, source)
    assert source.posts == source.reads == 0


@pytest.mark.parametrize('change', ['expired', 'resolved', 'paused', 'monitor_stale', 'target_changed', 'new_history'])
def test_approval_is_revalidated_before_dispatch(api, target, monkeypatch, change):
    row = approved(api, target); now = datetime.now(timezone.utc)
    if change == 'expired':
        original = review.clock
        monkeypatch.setattr(review, 'clock', lambda s: original(s)+timedelta(minutes=6))
    elif change == 'target_changed':
        monkeypatch.setenv('PIPEGUARD_RECOVERY_JOB_ID', str(uuid4()))
    else:
        with Session(api[2]) as session, session.begin():
            if change == 'resolved':session.get(Incident, target[0]).state = 'resolved'
            elif change == 'paused':observe(session, target[1], 'airflow', 'source_configuration', {'is_paused': True}, now)
            elif change == 'monitor_stale':
                heartbeat = session.scalar(select(MonitorHeartbeat).where(MonitorHeartbeat.name=='detector'))
                heartbeat.completed_at = now-timedelta(minutes=3)
            else:
                from pipeguard.db.models import IncidentHistory
                session.add(IncidentHistory(incident_id=target[0], action='acknowledged', evidence_key=str(uuid4()),
                    evidence={}, actor='local_administrator', occurred_at=now))
    source = Source()
    with pytest.raises(RecoveryRejected):dispatch(api, row, source)
    assert source.reads == source.posts == 0
    assert execution.inspect(api[2], UUID(row['id']))['dispatch'] is None


@pytest.mark.parametrize('point', ['before_intent', 'after_intent', 'after_post'])
def test_interruption_boundaries_never_resend_an_intent(api, target, monkeypatch, point):
    row = approved(api, target); source = Source(stop=point)
    with pytest.raises(SystemExit):dispatch(api, row, source)
    recorded = execution.inspect(api[2], UUID(row['id']))['dispatch']
    if point == 'before_intent':
        assert recorded is None and source.posts == 0
        return
    assert recorded['state']=='unknown' and recorded['events']==[]
    monkeypatch.setenv('PIPEGUARD_RECOVERY_EXECUTION_ENABLED', '0')
    original = review.clock
    monkeypatch.setattr(review, 'clock', lambda s: original(s)+timedelta(minutes=6))
    assert dispatch(api, row, source)['id'] == recorded['id']
    assert source.posts == (1 if point=='after_post' else 0)
    result = execution.reconcile(api[2], UUID(recorded['id']), uuid4(), source)
    assert result['state'] == ('queued' if point=='after_post' else 'unknown')


def test_lost_response_absent_lookup_and_success_preserve_failure(api, target):
    row = approved(api, target); source = Source(outcome='unknown')
    result = dispatch(api, row, source)
    source.exists = False
    result = execution.reconcile(api[2], UUID(result['id']), uuid4(), source)
    assert result['state']=='unknown' and result['events'][-1]['code']=='recovery_external_not_found'
    dispatch(api, row, source)
    assert source.posts==1
    source.exists = True; source.outcome = 'succeeded'; key = uuid4()
    result = execution.reconcile(api[2], UUID(result['id']), key, source)
    assert result['state']=='succeeded' and len(result['events'])==3
    assert execution.reconcile(api[2], UUID(result['id']), key, source)==result
    assert source.lookups==2
    with Session(api[2]) as session:
        runs = list(session.scalars(select(Run)))
        assert len(runs)==1 and runs[0].state=='failed'  # Worker never fabricates monitoring outcomes.
        assert session.get(Incident, target[0]).state=='open'
    with pytest.raises(RecoveryRejected, match='already_dispatched'):
        execution.decide(api[2], UUID(row['id']), uuid4(), row['payload_hash'], 'cancel', confirmed=True)


def test_database_failure_after_post_leaves_durable_unknown(api, target, monkeypatch):
    row = approved(api, target); source = Source()
    original = execution.append_event
    def unavailable(*args):raise RuntimeError('synthetic DB unavailable')
    monkeypatch.setattr(execution, 'append_event', unavailable)
    with pytest.raises(RuntimeError):dispatch(api, row, source)
    monkeypatch.setattr(execution, 'append_event', original)
    result = dispatch(api, row, source)
    assert result['state']=='unknown' and source.posts==1
    result = execution.reconcile(api[2], UUID(result['id']), uuid4(), source)
    assert result['state']=='queued' and source.posts==1


def test_parallel_dispatch_during_external_exchange_fails_without_second_post(api, target):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    row = approved(api, target); source = Source(); entered = Event(); resume = Event()
    def wait():
        entered.set()
        assert resume.wait(5)
    source.hook = wait
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(dispatch, api, row, source)
        try:
            assert entered.wait(5)
            with pytest.raises(RecoveryRejected, match='recovery_busy'):
                dispatch(api, row, Source())
        finally:resume.set()
        assert running.result(timeout=5)['state']=='queued'
    assert source.posts==1


def test_unapproved_and_rejected_proposals_never_contact_source(api, target):
    row = proposal(api, target); source = Source()
    with pytest.raises(RecoveryRejected, match='execution_not_approved'):dispatch(api, row, source)
    execution.decide(api[2], UUID(row['id']), uuid4(), row['payload_hash'], 'reject', confirmed=True)
    with pytest.raises(RecoveryRejected, match='execution_not_approved'):dispatch(api, row, source)
    assert source.posts==source.reads==0


def test_new_approval_cannot_accept_expired_evidence(api, target, monkeypatch):
    row = proposal(api, target); original = review.clock
    monkeypatch.setattr(review, 'clock', lambda s: original(s)+timedelta(minutes=6))
    with pytest.raises(RecoveryRejected, match='recovery_expired'):
        execution.decide(api[2], UUID(row['id']), uuid4(), row['payload_hash'], 'approve', confirmed=True)
    with Session(api[2]) as session:
        assert not list(session.scalars(select(RecoveryActionDecision)))


def test_second_preflight_change_blocks_post_after_intent(api, target):
    row = approved(api, target); source = Source()
    def paused():
        with Session(api[2]) as session, session.begin():
            observe(session, target[1], 'airflow', 'source_configuration', {'is_paused': True}, datetime.now(timezone.utc))
    source.hook = paused
    result = dispatch(api, row, source)
    assert result['state']=='rejected' and source.posts==0
    assert result['events'][0]['code']=='recovery_dag_paused_or_unknown'
    assert dispatch(api, row, source)['id']==result['id'] and source.posts==0


def test_different_proposals_cannot_repeat_a_failed_run_action(api, target):
    first = approved(api, target); second = approved(api, target)
    source = Source(outcome='rejected')
    dispatch(api, first, source)
    with pytest.raises(RecoveryRejected, match='failed_run_already_reserved'):
        dispatch(api, second, source)
    assert source.posts==1


def test_parallel_lock_and_append_only_permissions(api, target):
    row = approved(api, target)
    with api[2].connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
        connection.execute(text('SELECT pg_advisory_lock(:key)'), {'key': execution.LOCK})
        try:
            with pytest.raises(RecoveryRejected, match='recovery_busy'):dispatch(api, row, Source())
        finally:connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': execution.LOCK})
    dispatch(api, row, Source())
    for table in ('recovery_actions', 'recovery_action_decisions', 'recovery_dispatches', 'recovery_dispatch_events'):
        for statement in (f'UPDATE {table} SET id=id', f'DELETE FROM {table}', f'TRUNCATE {table} CASCADE'):
            with pytest.raises(DBAPIError), api[3].begin_nested():api[3].execute(text(statement))
        with api[2].connect() as connection:
            assert connection.scalar(text('SELECT has_table_privilege(current_user,:table,\'INSERT\')'), {'table': table})
            assert not connection.scalar(text('SELECT has_table_privilege(current_user,:table,\'DELETE\')'), {'table': table})


def test_contradictory_terminal_or_regressing_source_state_is_retained(api, target):
    row = approved(api, target); source = Source(outcome='succeeded')
    result = dispatch(api, row, source)
    source.outcome='failed'
    result = execution.reconcile(api[2], UUID(result['id']), uuid4(), source)
    assert result['state']=='conflict'
    assert [event['state'] for event in result['events']]==['succeeded', 'conflict']
    source.outcome='succeeded'
    assert execution.reconcile(api[2], UUID(result['id']), uuid4(), source)['state']=='conflict'


def test_history_cap_prevents_more_source_requests(api, target):
    row = approved(api, target); source = Source(stop='after_intent')
    with pytest.raises(SystemExit):dispatch(api, row, source)
    result = execution.inspect(api[2], UUID(row['id']))['dispatch']
    with Session(api[2]) as session, session.begin():
        session.add_all([RecoveryDispatchEvent(dispatch_id=UUID(result['id']), request_key=uuid4(), sequence=i,
            source='reconcile', state='unknown', code='synthetic_absent', facts={}) for i in range(1, 101)])
    with pytest.raises(RecoveryRejected, match='history_limit'):
        execution.reconcile(api[2], UUID(result['id']), uuid4(), source)
    assert source.lookups==source.posts==0


@pytest.mark.parametrize('phase,signal_name', [('after_intent', 'SIGKILL'), ('after_simulated_post', 'SIGTERM')])
def test_real_process_termination_keeps_intent_and_does_not_resubmit(api, target, tmp_path, phase, signal_name):
    import json
    import os
    from pathlib import Path
    import signal
    import subprocess
    import sys
    import time
    row = approved(api, target)
    schema = api[3].scalar(text('SELECT current_schema()'))
    marker = tmp_path/'external-marker'
    environment = {key: value for key, value in os.environ.items() if key in {'PATH','HOME','LANG','TMPDIR'}}
    environment |= {'PYTHONPATH': str(Path(__file__).resolve().parents[1]/'src'),
        'PIPEGUARD_API_DATABASE_URL': os.environ['PIPEGUARD_API_DATABASE_URL'],
        'PIPEGUARD_RECOVERY_JOB_ID': str(target[1]), 'PIPEGUARD_RECOVERY_EXECUTION_ENABLED': '1',
        'SYNTHETIC_RECOVERY': json.dumps({'schema':schema, 'action':row['id'], 'hash':row['payload_hash'],
            'phase':phase, 'signal':signal_name, 'marker':str(marker)})}
    code = '''
import json,os,signal
from pathlib import Path
from uuid import UUID,uuid4
from sqlalchemy import create_engine
from pipeguard.recovery import execution
values=json.loads(os.environ['SYNTHETIC_RECOVERY'])
engine=create_engine(os.environ['PIPEGUARD_API_DATABASE_URL'],hide_parameters=True,
    connect_args={'options':'-csearch_path='+values['schema']})
def terminate():
    os.kill(os.getpid(),getattr(signal,values['signal']))
class Source:
    reads=0
    def preflight(self,target):
        self.reads+=1
        if self.reads==2 and values['phase']=='after_intent':terminate()
    def submit(self,action):
        Path(values['marker']).write_text('synthetic external request accepted')
        terminate()
execution.dispatch(engine,UUID(values['action']),uuid4(),values['hash'],Source(),confirmed=True)
'''
    process = subprocess.run([sys.executable,'-c',code], env=environment,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
    assert process.returncode == -getattr(signal,signal_name)
    assert marker.exists() == (phase=='after_simulated_post')
    # Wait briefly for PostgreSQL to observe the dead child's closed socket.
    with api[2].connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
        until=time.monotonic()+5
        while not connection.scalar(text('SELECT pg_try_advisory_lock(:key)'),{'key':execution.LOCK}):
            assert time.monotonic()<until
            time.sleep(0.02)
        connection.execute(text('SELECT pg_advisory_unlock(:key)'),{'key':execution.LOCK})
    source=Source()
    result=dispatch(api,row,source)
    assert result['state']=='unknown' and result['events']==[] and source.posts==source.reads==0
