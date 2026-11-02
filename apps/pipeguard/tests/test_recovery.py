from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from test_api import api, producer
from pipeguard.db.models import (Incident, IncidentHistory, MonitorHeartbeat,
    RecoveryDecision, RecoveryProposal, Run)
from pipeguard.detection.service import evaluate_job, observe
from pipeguard.recovery import service


@pytest.fixture
def eligible(api, monkeypatch):
    client, admin, engine, _ = api
    headers, event, _ = producer(api, 'recovery-sample')
    client.post('/v1/monitor-policies', headers=admin, json={'job_id':event['job_id'],
        'quality_required':False, 'airflow_dag_id':'pipeguard_orders', 'airflow_task_id':'orders'})
    now = datetime.now(timezone.utc)
    event |= {'state':'failed','error_code':'source_unavailable','occurred_at':(now-timedelta(seconds=5)).isoformat()}
    assert client.post('/v1/events', headers=headers, json=event).status_code == 202
    with Session(engine) as session, session.begin():
        for name in ('detector', 'job:'+event['job_id']):
            session.add(MonitorHeartbeat(name=name, completed_at=now))
        for kind,payload in [('source_scan',{'status':'complete'}), ('source_configuration',{'is_paused':False}),
            ('airflow_run',{'external_run_id':event['external_run_id'],'dag_id':'pipeguard_orders','state':'failed'})]:
            observe(session,UUID(event['job_id']),'airflow',kind,payload,now)
    evaluate_job(engine,event['job_id'])
    incident = next(row for row in client.get('/v1/incidents',headers=headers).json()
        if row['condition']=='execution_failure')
    monkeypatch.setenv('PIPEGUARD_RECOVERY_JOB_ID',event['job_id'])
    return headers,event,incident


def create(api, eligible, key=None):
    return api[0].post(f"/v1/incidents/{eligible[2]['id']}/recovery-proposals",headers=api[1],
                       json={'request_key':str(key or uuid4())})


def decide(api, eligible, proposal, key=None, **changes):
    body={'request_key':str(key or uuid4()),'proposal_hash':proposal['payload_hash'],
          'decision':'approve','confirmed':True,**changes}
    return api[0].post(f"/v1/incidents/{eligible[2]['id']}/recovery-proposals/{proposal['id']}/decisions",
                       headers=api[1],json=body)


def test_review_lifecycle_replay_and_immutable_history(api,eligible):
    key=uuid4();response=create(api,eligible,key)
    assert response.status_code==200,response.text
    row=response.json()
    assert row['state']=='proposed' and row['integrity_valid'] and not row['can_execute']
    assert row['payload']['mode']=='review_only' and row['payload']['policy']=='recovery_review_v1'
    assert row['payload']['parameters']['dag_run_id'].startswith('pipeguard-recovery-')
    assert create(api,eligible,key).json()==row
    decision_key=uuid4();approved=decide(api,eligible,row,decision_key)
    assert approved.status_code==200,approved.text
    approved=approved.json()
    assert approved['state']=='review_approved' and not approved['can_execute']
    assert decide(api,eligible,row,decision_key).json()==approved
    assert decide(api,eligible,row).json()['error']=='recovery_already_decided'
    assert decide(api,eligible,row,decision_key,decision='reject').status_code==409
    path=f"/v1/incidents/{eligible[2]['id']}/recovery-proposals"
    assert api[0].get(path,headers=eligible[0]).json()['items'][0]==approved
    assert api[0].post(path,headers=eligible[0],json={'request_key':str(uuid4())}).status_code==403
    assert api[0].get(path).status_code==401
    with Session(api[2]) as s:
        assert len(list(s.scalars(select(RecoveryProposal))))==len(list(s.scalars(select(RecoveryDecision))))==1
    for table in ('recovery_proposals','recovery_decisions'):
        for statement in (f'DELETE FROM {table}',f'UPDATE {table} SET actor=actor',f'TRUNCATE {table} CASCADE'):
            with pytest.raises(DBAPIError),api[3].begin_nested():api[3].execute(text(statement))


@pytest.mark.parametrize('confirmation',[False,1,'true',None])
def test_confirmation_must_be_literal_boolean(api,eligible,confirmation):
    proposal=create(api,eligible).json()
    assert decide(api,eligible,proposal,confirmed=confirmation).status_code==422


def test_hash_expiry_rejection_and_historical_approval_replay(api,eligible,monkeypatch):
    row=create(api,eligible).json()
    assert decide(api,eligible,row,proposal_hash='0'*64).json()['error']=='recovery_hash_mismatch'
    original=service.clock
    monkeypatch.setattr(service,'clock',lambda s:original(s)+timedelta(minutes=6))
    assert decide(api,eligible,row).json()['error']=='recovery_expired'
    assert decide(api,eligible,row,decision='reject').json()['state']=='rejected'


@pytest.mark.parametrize('change', ['resolved','new_history','new_run','new_receipt','paused','scan_failed','monitor_stale','target_changed'])
def test_changes_prevent_approval(api,eligible,monkeypatch,change):
    row=create(api,eligible).json();job_id=UUID(eligible[1]['job_id']);now=datetime.now(timezone.utc)
    with Session(api[2]) as s,s.begin():
        if change=='resolved':s.get(Incident,UUID(eligible[2]['id'])).state='resolved'
        elif change=='new_history':s.add(IncidentHistory(incident_id=UUID(eligible[2]['id']),action='acknowledged',
            evidence_key=str(uuid4()),evidence={},actor='local_administrator',occurred_at=now))
        elif change=='new_run':s.add(Run(job_id=job_id,external_run_id='newer',state='running'))
        elif change=='paused':observe(s,job_id,'airflow','source_configuration',{'is_paused':True},now)
        elif change=='scan_failed':observe(s,job_id,'airflow','source_scan',{'status':'incomplete'},now)
        elif change=='monitor_stale':
            heartbeat=s.scalar(select(MonitorHeartbeat).where(MonitorHeartbeat.name=='detector'))
            heartbeat.completed_at=now-timedelta(minutes=3)
    if change=='target_changed':monkeypatch.setenv('PIPEGUARD_RECOVERY_JOB_ID',str(uuid4()))
    if change=='new_receipt':
        event=eligible[1]|{'event_id':'late','attempt_number':2,'state':'running','error_code':None}
        assert api[0].post('/v1/events',headers=eligible[0],json=event).status_code==202
    response=decide(api,eligible,row)
    assert response.status_code==409,response.text
    with Session(api[2]) as s:assert not list(s.scalars(select(RecoveryDecision)))


def test_polling_freshness_is_checked_without_invalidating_unchanged_complete_scan(api,eligible):
    row=create(api,eligible).json()
    with Session(api[2]) as s,s.begin():
        observe(s,UUID(eligible[1]['job_id']),'airflow','source_scan',{'status':'complete'},datetime.now(timezone.utc),'new-scan')
    assert decide(api,eligible,row).json()['state']=='review_approved'


def test_scope_pagination_and_no_dispatch_route(api,eligible):
    one=create(api,eligible).json();two=create(api,eligible).json()
    path=f"/v1/incidents/{eligible[2]['id']}/recovery-proposals"
    page=api[0].get(path+'?limit=1',headers=api[1]).json()
    assert page['items'][0]['id']==two['id'] and page['has_more']
    assert api[0].get(path+'?before='+page['next_before'],headers=api[1]).json()['items'][0]['id']==one['id']
    other,_,_=producer(api,'other')
    assert api[0].get(path,headers=other).status_code==404
    assert api[0].post(path+'/'+one['id']+'/execute',headers=api[1],json={}).status_code==404
    assert api[0].post(path,headers=api[1],json={'request_key':str(uuid4()),'command':'unsafe'}).status_code==422


def test_parallel_mutation_is_denied_and_interrupted_proposal_rolls_back(api,eligible,monkeypatch):
    with api[2].connect().execution_options(isolation_level='AUTOCOMMIT') as lock:
        lock.execute(text('SELECT pg_advisory_lock(:key)'),{'key':service.LOCK})
        try:assert create(api,eligible).json()['error']=='recovery_busy'
        finally:lock.execute(text('SELECT pg_advisory_unlock(:key)'),{'key':service.LOCK})
    original=service.view
    def stop(*args,**kwargs):raise SystemExit('simulated stop before commit')
    monkeypatch.setattr(service,'view',stop)
    key=uuid4()
    with pytest.raises(SystemExit):service.propose(api[2],UUID(eligible[2]['id']),key)
    monkeypatch.setattr(service,'view',original)
    with Session(api[2]) as s:assert not list(s.scalars(select(RecoveryProposal)))
    assert create(api,eligible,key).status_code==200


@pytest.mark.parametrize('fault',['stale_scan','future_scan','pending_receipt','disabled','hash','truncated','changed_during_capture'])
def test_proposal_guards_do_not_leave_proposals(api,eligible,monkeypatch,fault):
    from pipeguard.detection.service import digest
    from pipeguard.ingestion.service import _receive
    from pipeguard.db.models import Integration
    if fault in {'stale_scan','future_scan'}:
        now=datetime.now(timezone.utc)
        with Session(api[2]) as s,s.begin():
            observe(s,UUID(eligible[1]['job_id']),'airflow','source_scan',{'status':'complete'},
                    now+timedelta(minutes=1) if fault=='future_scan' else now-timedelta(minutes=3),str(uuid4()))
    elif fault=='pending_receipt':
        _receive(api[2],eligible[1]|{'event_id':'pending-receipt'})
    elif fault=='disabled':
        with Session(api[2]) as s,s.begin():s.get(Integration,UUID(eligible[1]['integration_id'])).enabled=False
    else:
        original=service.capture
        def capture(*args):
            result=original(*args)
            if fault=='hash':result['payload_hash']='0'*64
            elif fault=='truncated':
                result['payload']['truncated']=True;result['payload_hash']=digest(result['payload'])
            else:
                with Session(api[2]) as s,s.begin():
                    observe(s,UUID(eligible[1]['job_id']),'airflow','delivery_conflict',{},datetime.now(timezone.utc))
            return result
        monkeypatch.setattr(service,'capture',capture)
    response=create(api,eligible)
    assert response.status_code==409,response.text
    with Session(api[2]) as s:assert not list(s.scalars(select(RecoveryProposal)))


def test_decision_interruption_rollback_and_replay_after_expiry(api,eligible,monkeypatch):
    row=create(api,eligible).json();key=uuid4();original=service.view
    def stop(*args,**kwargs):raise SystemExit('simulated stop before decision commit')
    monkeypatch.setattr(service,'view',stop)
    with pytest.raises(SystemExit):
        service.decide(api[2],UUID(eligible[2]['id']),UUID(row['id']),key,row['payload_hash'],'approve')
    with Session(api[2]) as s:assert not list(s.scalars(select(RecoveryDecision)))
    monkeypatch.setattr(service,'view',original)
    approved=decide(api,eligible,row,key).json()
    clock=service.clock;monkeypatch.setattr(service,'clock',lambda s:clock(s)+timedelta(minutes=6))
    replay=decide(api,eligible,row,key).json()
    assert replay['decision']==approved['decision'] and replay['expired'] and not replay['can_execute']


def test_proposal_keys_and_cursors_cannot_cross_incidents(api,eligible):
    key=uuid4();row=create(api,eligible,key).json()
    other=Incident(job_id=UUID(eligible[1]['job_id']),condition='quality_missing',subject='other',policy_version='v1',
        severity='warning',state='open',last_evaluated_at=datetime.now(timezone.utc))
    with Session(api[2]) as s,s.begin():s.add(other);s.flush();other_id=str(other.id)
    path=f'/v1/incidents/{other_id}/recovery-proposals'
    assert api[0].post(path,headers=api[1],json={'request_key':str(key)}).json()['error']=='recovery_key_scope_conflict'
    assert api[0].get(path+'?before='+row['id'],headers=api[1]).status_code==404
    denied=api[0].post(f"/v1/incidents/{eligible[2]['id']}/recovery-proposals/{row['id']}/decisions",
        headers=eligible[0],json={'request_key':str(uuid4()),'proposal_hash':row['payload_hash'],
                               'decision':'approve','confirmed':True})
    assert denied.status_code==403


def test_expiry_is_rechecked_after_evidence_validation(api,eligible,monkeypatch):
    row=create(api,eligible).json();original=service.clock;calls=[]
    def advancing_clock(session):
        calls.append(1)
        return original(session)+(timedelta(minutes=6) if len(calls)==3 else timedelta(0))
    monkeypatch.setattr(service,'clock',advancing_clock)
    assert decide(api,eligible,row).json()['error']=='recovery_expired'
    with Session(api[2]) as s:assert not list(s.scalars(select(RecoveryDecision)))
