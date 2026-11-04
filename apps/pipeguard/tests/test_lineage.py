from copy import deepcopy
from datetime import datetime, timedelta, timezone
from itertools import permutations
from uuid import uuid4

import pytest
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from test_api import api,producer
from pipeguard.db.models import Dataset, DatasetMention, LineageRun, LineageEvent
from pipeguard.lineage.contracts import LineageReport,SCHEMA_URL,PRODUCER
from pipeguard.detection.service import evaluate_job, digest
from pipeguard.lineage.service import receive

T=datetime(2026,10,31,10,tzinfo=timezone.utc)


def report(execution,key='lineage',run_uuid=None,step='staging',inputs=('raw.orders',),outputs=('staging.orders',),state='COMPLETE',seconds=1):
    return {'schema_version':1,'event_id':key,'integration_id':execution['integration_id'],'job_id':execution['job_id'],
        'external_run_id':execution['external_run_id'],'attempt_number':execution['attempt_number'],
        'expected_steps':[{'namespace':'local-orders','name':step}], 'basis':'declared_dbt','coverage':'complete','missing_metadata':[], 'artifact_hashes':{},
        'event':{'eventTime':(T+timedelta(seconds=seconds)).isoformat(),'producer':PRODUCER,'schemaURL':SCHEMA_URL,
            'eventType':state,'run':{'runId':str(run_uuid or uuid4())},'job':{'namespace':'local-orders','name':step},
            'inputs':[{'namespace':'postgresql://local/sample_warehouse','name':n} for n in inputs],
            'outputs':[{'namespace':'postgresql://local/sample_warehouse','name':n} for n in outputs]}}


def post(client,headers,body):
    result=client.post('/v1/lineage-events',headers=headers,json=body)
    assert result.status_code==202,result.text
    return result.json()


def graph(client,headers,execution,query=''):
    return client.get('/v1/jobs/'+execution['job_id']+'/lineage'+query,headers=headers)


def test_replay_preserves_event_hash_mentions_and_binding(api):
    client,_,_,connection=api;headers,execution,_=producer(api)
    body=report(execution)
    first=post(client,headers,body);second=post(client,headers,body)
    assert first['event_id']==second['event_id'] and second['replayed']
    detail=client.get('/v1/lineage-events/'+first['event_id'],headers=headers).json()
    assert detail['payload_hash']==digest(LineageReport.model_validate(body).model_dump(mode='json'))
    with Session(connection) as s:
        assert s.scalar(select(func.count()).select_from(LineageRun))==1
        assert s.scalar(select(func.count()).select_from(DatasetMention))==2
    b=graph(client,headers,execution).json()
    assert len(b['nodes'])==3 and len(b['edges'])==2
    assert all(edge['evidence'][0]['event_id']==first['event_id'] for edge in b['edges'])


def test_start_complete_and_late_metadata_are_additive_in_every_order(api):
    client,_,_,_=api
    for order in permutations(range(3)):
        headers,execution,_=producer(api,uuid4().hex);run_uuid=uuid4()
        values=[report(execution,'start',run_uuid,inputs=('raw.one',),outputs=(),state='START',seconds=0),
                report(execution,'complete',run_uuid,inputs=(),outputs=('mart.one',),seconds=2),
                report(execution,'extra',run_uuid,inputs=('raw.two',),outputs=(),state='OTHER',seconds=1)]
        for index in order:post(client,headers,values[index])
        b=graph(client,headers,execution).json()
        assert {n['name'] for n in b['nodes'] if n['kind']=='dataset'}=={'raw.one','raw.two','mart.one'}
        assert len(b['edges'])==3


def test_event_and_openlineage_run_identity_collisions_are_durable(api):
    client,_,engine,_=api;headers,e,_=producer(api)
    assert client.post('/v1/monitor-policies',headers=api[1],json={'job_id':e['job_id'],'quality_required':False}).status_code==201
    body=report(e);post(client,headers,body)
    changed=deepcopy(body);changed['event']['outputs'][0]['name']='different'
    assert client.post('/v1/lineage-events',headers=headers,json=changed).status_code==409
    changed=deepcopy(body);changed['event_id']='new';changed['external_run_id']='different-run'
    assert client.post('/v1/lineage-events',headers=headers,json=changed).status_code==409
    changed=deepcopy(body);changed['event_id']='other';changed['event']['run']['runId']=str(uuid4())
    assert client.post('/v1/lineage-events',headers=headers,json=changed).status_code==409
    evaluate_job(engine,e['job_id'])
    assert any(i['condition']=='delivery_conflict' for i in client.get('/v1/incidents',headers=headers).json())


def test_scopes_and_shared_dataset_identity_do_not_merge_tenants(api):
    client,_,_,_=api;one,e1,_=producer(api,'one');two,e2,_=producer(api,'two')
    body=report(e1);accepted=post(client,one,body)
    assert client.post('/v1/lineage-events',headers=two,json=body).status_code==403
    assert client.get('/v1/lineage-events/'+accepted['event_id'],headers=two).status_code==404
    assert graph(client,two,e1).status_code==404
    post(client,two,report(e2,outputs=('private.output',)))
    b=graph(client,one,e1).json()
    assert all(n['name']!='private.output' for n in b['nodes'])
    dataset=next(n for n in b['nodes'] if n['kind']=='dataset')
    assert graph(client,two,e2,'?root_dataset_id='+dataset['id'].split(':',1)[1]).status_code in (200,404)
    # One shared input grants no visibility of the other integration's output or logical step.
    assert all(n['name']!='private.output' for n in graph(client,one,e1).json()['nodes'])


@pytest.mark.parametrize('fault',['sql','facet','credentials','query','extra','duplicate','too_many','version_bool','inconsistent_gap'])
def test_unsafe_unsupported_and_ambiguous_metadata_is_rejected_without_echo(api,fault):
    client,_,_,_=api;headers,e,_=producer(api);body=report(e)
    if fault=='sql':body['event']['job']['facets']={'sql':{'query':'SECRET_SQL'}}
    if fault=='facet':body['event']['inputs'][0]['facets']={'secret':'SECRET_SQL'}
    if fault=='credentials':body['event']['inputs'][0]['namespace']='postgresql://user:SECRET_SQL@local/db'
    if fault=='query':body['event']['inputs'][0]['namespace']='postgresql://local/db?token=SECRET_SQL'
    if fault=='extra':body['password']='SECRET_SQL'
    if fault=='duplicate':body['event']['inputs']*=2
    if fault=='too_many':body['event']['inputs']=[{'namespace':'file://local','name':f'file{i}'} for i in range(33)]
    if fault=='version_bool':body['schema_version']=True
    if fault=='inconsistent_gap':body['coverage']='partial'
    r=client.post('/v1/lineage-events',headers=headers,json=body)
    assert r.status_code==422 and 'SECRET_SQL' not in r.text


def test_historical_event_time_and_received_time_cutoffs(api):
    client,_,_,_=api;headers,e,_=producer(api)
    first=post(client,headers,report(e,'early',state='START',seconds=0))
    known=client.get('/v1/lineage-events/'+first['event_id'],headers=headers).json()['received_at']
    post(client,headers,report(e,'late',step='different',inputs=('hidden.input',),seconds=-1))
    old=graph(client,headers,e,'?known_at='+known.replace('+','%2B')).json()
    assert all(n['name']!='hidden.input' for n in old['nodes'])
    new=graph(client,headers,e).json()
    assert any(n['name']=='hidden.input' for n in new['nodes'])
    very_old=graph(client,headers,e,'?as_of=2026-10-30T00:00:00Z').json()
    assert very_old['coverage']=='partial' and very_old['nodes']==[]


def test_traversal_cycles_depth_and_size_limits_are_explicit(api):
    client,_,_,_=api;headers,e,_=producer(api)
    post(client,headers,report(e,'a',inputs=('raw.a',),outputs=('raw.b',),step='a'))
    post(client,headers,report(e,'b',inputs=('raw.b',),outputs=('raw.a',),step='b'))
    all_graph=graph(client,headers,e).json()
    root=next(n['id'].split(':',1)[1] for n in all_graph['nodes'] if n['name']=='raw.a')
    full=graph(client,headers,e,'?root_dataset_id='+root+'&direction=both').json()
    assert len(full['nodes'])==4 and not full['truncated']
    bounded=graph(client,headers,e,'?root_dataset_id='+root+'&max_nodes=1').json()
    assert len(bounded['nodes'])==1 and bounded['truncated'] and 'graph_limit' in bounded['missing_metadata']
    shallow=graph(client,headers,e,'?root_dataset_id='+root+'&depth=1').json()
    assert shallow['truncated']
    assert graph(client,headers,e,'?direction=invalid').status_code==422
    assert graph(client,headers,e,'?as_of=2026-10-31T10:00:00').status_code==422


def test_partial_lineage_and_later_retry_recovery_preserve_history(api):
    client,admin,engine,_=api;headers,e,_=producer(api)
    client.post('/v1/monitor-policies',headers=admin,json={'job_id':e['job_id'],'quality_required':False})
    body=report(e);body.update(coverage='partial',missing_metadata=['unresolved_dependency'])
    post(client,headers,body);evaluate_job(engine,e['job_id'])
    assert graph(client,headers,e).json()['coverage']=='partial'
    incident=next(i for i in client.get('/v1/incidents',headers=headers).json() if i['condition']=='lineage_partial')
    assert incident['state']=='open'
    post(client,headers,report(e|{'attempt_number':2},key='retry',seconds=2))
    evaluate_job(engine,e['job_id'])
    assert client.get('/v1/incidents/'+incident['id'],headers=headers).json()['state']=='resolved'
    # The union still says historical partial evidence existed.
    assert graph(client,headers,e).json()['coverage']=='partial'
    assert graph(client,headers,e,'?attempt_number=2').json()['coverage']=='reported_complete'


def test_receipt_rolls_back_all_catalog_and_edge_writes_on_failure(api,monkeypatch):
    import pipeguard.lineage.service as service
    client,_,engine,connection=api;headers,e,_=producer(api)
    def crash(*args,**kwargs):raise RuntimeError('controlled_write_failure')
    monkeypatch.setattr(service,'DatasetMention',crash)
    with pytest.raises(RuntimeError):receive(engine,LineageReport.model_validate(report(e)))
    with Session(connection) as s:
        for model in (LineageRun,LineageEvent,DatasetMention,Dataset):
            assert s.scalar(select(func.count()).select_from(model))==0


def test_contradictory_lineage_terminal_states_are_not_silently_reconciled(api):
    client,admin,engine,_=api;headers,e,_=producer(api)
    client.post('/v1/monitor-policies',headers=admin,json={'job_id':e['job_id'],'quality_required':False})
    identity=uuid4()
    post(client,headers,report(e,'complete',identity))
    post(client,headers,report(e,'failure',identity,state='FAIL',seconds=2))
    evaluate_job(engine,e['job_id'])
    assert any(i['condition']=='lineage_conflict' and i['state']=='open' for i in client.get('/v1/incidents',headers=headers).json())
    assert 'contradictory_run_outcomes' in graph(client,headers,e).json()['missing_metadata']


def test_namespace_is_metadata_never_a_network_fetch(api,monkeypatch):
    client,_,_,_=api;headers,e,_=producer(api)
    def no_fetch(*args,**kwargs):raise AssertionError('metadata must never be fetched')
    monkeypatch.setattr('urllib.request.urlopen',no_fetch)
    body=report(e);body['event']['inputs'][0]['namespace']='http://169.254.169.254/latest/meta-data'
    post(client,headers,body)
    assert graph(client,headers,e).status_code==200


def test_graph_checks_indexed_edges_against_original_payload(api):
    client,_,engine,_=api;headers,e,_=producer(api)
    accepted=post(client,headers,report(e))
    with Session(engine) as s,s.begin():
        dataset=Dataset(namespace='file://local',name='not.in.source',kind='reported');s.add(dataset);s.flush()
        s.add(DatasetMention(event_id=accepted['event_id'],dataset_id=dataset.id,role='output'))
    b=graph(client,headers,e).json()
    assert 'projection_payload_mismatch' in b['missing_metadata']
    assert all(n['name']!='not.in.source' for n in b['nodes'])


@pytest.mark.parametrize('keep_input', [False, True])
def test_graph_missing_indexed_edges_cannot_claim_complete_lineage(api, keep_input):
    client, _, engine, _ = api
    headers, execution, _ = producer(api)
    accepted = post(client, headers, report(execution))
    # Simulate an incomplete imported projection without mutating immutable evidence.
    payload = LineageReport.model_validate(report(execution, key='unindexed')).model_dump(mode='json')
    with Session(engine) as session, session.begin():
        original = session.get(LineageEvent, accepted['event_id'])
        payload['event']['run']['runId'] = str(session.get(LineageRun, original.lineage_run_id).run_uuid)
        incomplete = LineageEvent(integration_id=original.integration_id, lineage_run_id=original.lineage_run_id,
            event_key='unindexed', event_type='COMPLETE', occurred_at=original.occurred_at,
            payload=payload, payload_hash=digest(payload))
        session.add(incomplete)
        session.flush()
        if keep_input:
            dataset = session.scalar(select(Dataset).where(Dataset.name == 'raw.orders'))
            session.add(DatasetMention(event_id=incomplete.id, dataset_id=dataset.id, role='input'))
    body = graph(client, headers, execution).json()
    assert body['coverage'] == 'partial'
    assert 'projection_payload_mismatch' in body['missing_metadata']


def test_invalid_stored_source_hash_never_claims_complete_lineage(api):
    client,_,engine,_=api;headers,e,_=producer(api)
    accepted=post(client,headers,report(e))
    with Session(engine) as s,s.begin():
        original=s.get(LineageEvent,accepted['event_id'])
        s.add(LineageEvent(integration_id=original.integration_id,lineage_run_id=original.lineage_run_id,
            event_key='bad-hash',event_type='COMPLETE',occurred_at=original.occurred_at,payload=original.payload,payload_hash='b'*64))
    assert 'source_hash_mismatch' in graph(client,headers,e).json()['missing_metadata']


def test_declared_inventory_prevents_false_completion_on_partial_delivery(api):
    client,admin,engine,_=api;headers,e,_=producer(api)
    client.post('/v1/monitor-policies',headers=admin,json={'job_id':e['job_id'],'quality_required':False})
    inventory=[{'namespace':'local-orders','name':name} for name in ('stage','mart')]
    first=report(e,key='stage',step='stage');first['expected_steps']=inventory
    post(client,headers,first);evaluate_job(engine,e['job_id'])
    b=graph(client,headers,e).json()
    assert 'missing_expected_steps' in b['missing_metadata'] and b['coverage']=='partial'
    i=next(i for i in client.get('/v1/incidents',headers=headers).json() if i['condition']=='lineage_partial')
    assert i['state']=='open'
    last=report(e,key='mart',step='mart');last['expected_steps']=inventory
    post(client,headers,last);evaluate_job(engine,e['job_id'])
    assert graph(client,headers,e).json()['coverage']=='reported_complete'
    assert client.get('/v1/incidents/'+i['id'],headers=headers).json()['state']=='resolved'


def test_unknown_inventory_and_start_only_remain_partial(api):
    client,_,_,_=api;headers,e,_=producer(api)
    first=report(e,state='START');post(client,headers,first)
    assert 'missing_terminal_lineage' in graph(client,headers,e).json()['missing_metadata']
    missing=report(e|{'attempt_number':2},key='unknown');missing['expected_steps']=[]
    post(client,headers,missing)
    assert 'lineage_inventory_unknown' in graph(client,headers,e,'?attempt_number=2').json()['missing_metadata']


def test_explicit_expectation_catches_total_absence_and_recovers_from_complete_inventory(api):
    client,admin,engine,_=api;headers,e,_=producer(api)
    client.post('/v1/monitor-policies',headers=admin,json={'job_id':e['job_id'],'quality_required':False})
    config={'job_id':e['job_id'],'grace_seconds':60}
    assert client.post('/v1/lineage-expectations',headers=headers,json=config).status_code==403
    assert client.post('/v1/lineage-expectations',headers=admin,json=config).status_code==201
    assert client.post('/v1/lineage-expectations',headers=admin,json=config).status_code==409
    assert client.post('/v1/events',headers=headers,json=e|{'state':'succeeded'}).status_code==202
    evaluate_job(engine,e['job_id'],at=T+timedelta(seconds=59))
    assert not any(i['condition']=='lineage_missing' for i in client.get('/v1/incidents',headers=headers).json())
    evaluate_job(engine,e['job_id'],at=T+timedelta(seconds=60))
    i=next(i for i in client.get('/v1/incidents',headers=headers).json() if i['condition']=='lineage_missing')
    assert i['state']=='open'
    post(client,headers,report(e))
    evaluate_job(engine,e['job_id'],at=T+timedelta(seconds=61))
    assert client.get('/v1/incidents/'+i['id'],headers=headers).json()['state']=='resolved'
    other,other_event,_=producer(api,'other')
    assert client.get('/v1/jobs/'+e['job_id']+'/lineage-expectation',headers=other).status_code==404
    coverage=client.get('/v1/monitoring/coverage',headers=admin).json()
    assert next(j for j in coverage['jobs'] if j['job_id']==e['job_id'])['lineage_expected'] is True


def test_later_complete_metadata_can_resolve_earlier_partial_report_in_same_attempt(api):
    client,admin,engine,_=api;headers,e,_=producer(api)
    client.post('/v1/monitor-policies',headers=admin,json={'job_id':e['job_id'],'quality_required':False})
    identity=uuid4();first=report(e,'first',identity,state='START',seconds=0)
    first.update(coverage='partial',missing_metadata=['unresolved_dependency'])
    post(client,headers,first);evaluate_job(engine,e['job_id'])
    i=next(i for i in client.get('/v1/incidents',headers=headers).json() if i['condition']=='lineage_partial')
    assert i['state']=='open'
    post(client,headers,report(e,'resolved',identity,seconds=2))
    evaluate_job(engine,e['job_id'])
    assert client.get('/v1/incidents/'+i['id'],headers=headers).json()['state']=='resolved'
