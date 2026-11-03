"""Executable HTTP controls use disposable records and a synthetic worker only."""
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from test_api import api, producer
from test_recovery_execution import target, Source
from pipeguard.db.models import RecoveryAction, RecoveryDispatch
from pipeguard.recovery import execution, execution_api, bridge


@pytest.fixture
def worker(api, target, monkeypatch):
    calls=[]; source=Source()
    def run(command, **args):
        calls.append((command,args))
        if command=='status':return {'execution_enabled':os.environ.get('PIPEGUARD_RECOVERY_EXECUTION_ENABLED')=='1'}
        if command=='propose':return execution.propose(api[2],args['incident_id'],args['request_key'])
        if command=='decide':return execution.decide(api[2],args['action_id'],args['request_key'],args['proposal_hash'],args['decision'],confirmed=True)
        if command=='dispatch':return execution.dispatch(api[2],args['action_id'],args['request_key'],args['proposal_hash'],source,confirmed=True)
        return execution.reconcile(api[2],args['dispatch_id'],args['request_key'],source)
    monkeypatch.setattr(execution_api.bridge,'call',run)
    return calls,source


def create(api, target):
    response=api[0].post(f'/v1/incidents/{target[0]}/recovery-actions',headers=api[1],json={'request_key':str(uuid4())})
    assert response.status_code==200,response.text
    return response.json()


def test_separate_api_lifecycle_and_read_scope(api,target,worker):
    client,admin,_,_=api; root=f'/v1/incidents/{target[0]}/recovery-actions'
    row=create(api,target)
    decision={'request_key':str(uuid4()),'proposal_hash':row['payload_hash'],'confirmed':True,'decision':'approve'}
    assert client.post(root+'/'+row['id']+'/decisions',headers=admin,json=decision).status_code==200
    start={k:v for k,v in decision.items() if k!='decision'}
    result=client.post(root+'/'+row['id']+'/dispatch',headers=admin,json=start)
    assert result.status_code==200,result.text
    assert result.json()['state']=='queued'
    assert client.post(root+'/'+row['id']+'/dispatch',headers=admin,json=start).json()==result.json()
    assert worker[1].posts==1
    worker[1].outcome='succeeded'
    result=client.post(root+'/'+row['id']+'/reconcile',headers=admin,json={'request_key':str(uuid4())})
    assert result.status_code==200 and result.json()['state']=='succeeded'
    page=client.get(root,headers=admin).json()
    assert page['items'][0]['dispatch']['state']=='succeeded'
    other,_,_=producer(api,'other-executable')
    calls=len(worker[0])
    assert client.get(root,headers=other).status_code==404
    assert client.post(root,headers=other,json={'request_key':str(uuid4())}).status_code==403
    assert client.get(root).status_code==401
    assert len(worker[0])==calls
    # Review routes cannot approve an executable action ID.
    assert client.post(f'/v1/incidents/{target[0]}/recovery-proposals/{row["id"]}/decisions',headers=admin,json=decision).status_code==404


@pytest.mark.parametrize('value',[False,1,'true',None])
def test_execution_confirmation_is_literal_and_scoped_before_worker(api,target,worker,value):
    row=create(api,target); root=f'/v1/incidents/{target[0]}/recovery-actions/{row["id"]}'
    calls=len(worker[0])
    for suffix,extra in [('decisions',{'decision':'approve'}),('dispatch',{})]:
        body={'request_key':str(uuid4()),'proposal_hash':row['payload_hash'],'confirmed':value,**extra}
        assert api[0].post(root+'/'+suffix,headers=api[1],json=body).status_code==422
    assert len(worker[0])==calls


def test_pagination_disabled_worker_and_cross_incident_targets(api,target,worker,monkeypatch):
    rows=[create(api,target) for _ in range(6)]
    root=f'/v1/incidents/{target[0]}/recovery-actions'
    first=api[0].get(root,headers=api[1]).json()
    assert len(first['items'])==5 and first['has_more']
    second=api[0].get(root+'?before='+first['next_before'],headers=api[1]).json()
    assert second['items'][0]['id']==rows[0]['id'] and not second['has_more']
    assert api[0].get(root+'?limit=6',headers=api[1]).status_code==422
    assert api[0].get(root+'?before='+str(uuid4()),headers=api[1]).status_code==404
    calls=len(worker[0])
    assert api[0].post(root+'/'+str(uuid4())+'/dispatch',headers=api[1],json={
        'request_key':str(uuid4()),'proposal_hash':'a'*64,'confirmed':True}).status_code==404
    assert len(worker[0])==calls
    monkeypatch.setenv('PIPEGUARD_RECOVERY_EXECUTION_ENABLED','0')
    page=api[0].get(root,headers=api[1]).json()
    assert not page['execution_enabled'] and not page['eligibility']['can_propose']
    def unavailable(*args,**kwargs):raise bridge.WorkerUnavailable('private details')
    monkeypatch.setattr(execution_api.bridge,'call',unavailable)
    page=api[0].get(root,headers=api[1]).json()
    assert page['execution_enabled'] is None and not page['worker_available'] and len(page['items'])==5
    result=api[0].post(root,headers=api[1],json={'request_key':str(uuid4())})
    assert result.status_code==503 and result.json()=={'error':'recovery_worker_unknown'}


def test_unknown_dispatch_reply_replay_preserves_one_intent(api,target,worker,monkeypatch):
    row=create(api,target); root=f'/v1/incidents/{target[0]}/recovery-actions/{row["id"]}'
    body={'request_key':str(uuid4()),'proposal_hash':row['payload_hash'],'confirmed':True}
    assert api[0].post(root+'/decisions',headers=api[1],json=body|{'decision':'approve'}).status_code==200
    original=execution_api.bridge.call; drop=[True]
    def lost(command,**args):
        result=original(command,**args)
        if command=='dispatch' and drop[0]:
            drop[0]=False
            raise bridge.WorkerUnavailable('synthetic lost reply after commit')
        return result
    monkeypatch.setattr(execution_api.bridge,'call',lost)
    assert api[0].post(root+'/dispatch',headers=api[1],json=body).status_code==503
    assert api[0].post(root+'/dispatch',headers=api[1],json=body).status_code==200
    assert worker[1].posts==1
    with Session(api[2]) as session:
        assert len(list(session.scalars(select(RecoveryDispatch))))==1
        assert len(list(session.scalars(select(RecoveryAction))))==1
