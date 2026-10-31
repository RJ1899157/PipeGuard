from datetime import datetime,timezone
from uuid import uuid4,UUID

import pytest
from sqlalchemy import select,text,func
from sqlalchemy.orm import Session
from sqlalchemy.exc import DBAPIError

from test_api import api,producer
from test_lineage import report,post
from pipeguard.db.models import Incident,IncidentHistory,Observation,LineageEvent,EvidenceBundle
from pipeguard.detection.service import evaluate_job,digest,observe


def failure(api,name='orders'):
    client,admin,engine,_=api;headers,event,_=producer(api,name)
    client.post('/v1/monitor-policies',headers=admin,json={'job_id':event['job_id'],'quality_required':False})
    assert client.post('/v1/events',headers=headers,json=event|{'state':'failed','error_code':'source_unavailable'}).status_code==202
    assert client.post('/v1/events',headers=headers,json=event|{'event_id':'retry','attempt_number':2,'state':'succeeded',
                                                              'occurred_at':'2026-10-31T10:02:00Z'}).status_code==202
    evaluate_job(engine,event['job_id'])
    incident=next(i for i in client.get('/v1/incidents',headers=headers).json() if i['condition']=='execution_failure')
    return headers,event,incident


def test_snapshot_preserves_prior_failure_is_stable_and_scoped(api):
    client,_,engine,_=api;headers,event,incident=failure(api)
    line=post(client,headers,report(event))
    path='/v1/incidents/'+incident['id']+'/evidence-bundles'
    one=client.post(path,headers=headers)
    assert one.status_code==201,one.text
    body=one.json();two=client.post(path,headers=headers)
    assert two.json()['id']==body['id'] and body['payload_hash']==digest(body['payload'])
    attempts=[i['summary'] for i in body['payload']['items'] if i['table']=='attempts']
    assert {a['state'] for a in attempts}=={'failed','succeeded'}
    assert any(i['table']=='lineage_events' and i['id']==line['event_id'] and i['summary']['expected_steps'] for i in body['payload']['items'])
    other,_,_=producer(api,'other')
    assert client.post(path,headers=other).status_code==404
    assert client.get('/v1/evidence-bundles/'+body['id'],headers=other).status_code==404
    assert client.get('/v1/evidence-bundles/'+body['id']).status_code==401
    late=event|{'event_id':'new-failure','attempt_number':3,'state':'failed','occurred_at':'2026-10-31T10:03:00Z'}
    client.post('/v1/events',headers=headers,json=late);evaluate_job(engine,event['job_id'])
    new=client.post(path,headers=headers).json()
    assert new['payload_hash']!=body['payload_hash']
    assert client.get('/v1/evidence-bundles/'+body['id'],headers=headers).json()==body
    assert body['payload']['incident']['state']=='resolved' and new['payload']['incident']['state']=='open'


def test_missing_lineage_and_independent_source_are_explicit(api):
    client,_,_,_=api;headers,event,incident=failure(api)
    body=client.post('/v1/incidents/'+incident['id']+'/evidence-bundles',headers=headers).json()
    assert set(body['payload']['missing_evidence']) >= {'no_lineage_observed','no_independent_orchestrator_source'}


def test_out_of_scope_or_missing_history_reference_never_leaks_payload(api):
    client,_,engine,_=api;headers,event,incident=failure(api)
    other,other_event,_=producer(api,'private')
    accepted=post(client,other,report(other_event,outputs=('private.dataset',)))
    with Session(engine) as s,s.begin():
        s.add(IncidentHistory(incident_id=UUID(incident['id']),action='observed',evidence_key='foreign',
            evidence={'table':'lineage_events','id':accepted['event_id'],'private':'SECRET_MARKER'},
            actor='detector-v1',occurred_at=datetime.now(timezone.utc)))
    r=client.post('/v1/incidents/'+incident['id']+'/evidence-bundles',headers=headers)
    assert r.status_code==201
    assert 'SECRET_MARKER' not in r.text and 'private.dataset' not in r.text
    assert 'history_reference_outside_scope_or_missing' in r.json()['payload']['missing_evidence']


def test_cited_old_observation_survives_more_than_a_window_of_scan_noise(api):
    client,_,engine,_=api;headers,event,incident=failure(api)
    with Session(engine) as s,s.begin():
        old,_=observe(s,UUID(event['job_id']),'airflow','source_scan',{'status':'incomplete'},datetime.now(timezone.utc),'old')
        s.add(IncidentHistory(incident_id=UUID(incident['id']),action='observed',evidence_key='old-source',
            evidence={'table':'observations','id':str(old.id)},actor='detector-v1',occurred_at=datetime.now(timezone.utc)))
        old_id=str(old.id)
    for index in range(110):
        with Session(engine) as s,s.begin():
            observe(s,UUID(event['job_id']),'airflow','source_scan',{'status':'complete'},datetime.now(timezone.utc),'scan'+str(index))
    r=client.post('/v1/incidents/'+incident['id']+'/evidence-bundles',headers=headers)
    assert r.status_code==201,r.text
    body=r.json()['payload']
    assert any(i['id']==old_id and i['table']=='observations' for i in body['items'])
    assert len(body['items'])<=100


def test_append_only_lineage_and_snapshot_rows_enforced_for_runtime_and_owner(api):
    client,_,engine,owner=api;headers,e,incident=failure(api)
    post(client,headers,report(e))
    assert client.post('/v1/lineage-expectations',headers=api[1],json={'job_id':e['job_id']}).status_code==201
    assert client.post('/v1/incidents/'+incident['id']+'/evidence-bundles',headers=headers).status_code==201
    for table in ('lineage_runs','lineage_events','dataset_mentions','evidence_bundles','datasets','lineage_expectations'):
        for sql in (f'DELETE FROM {table}',f'UPDATE {table} SET created_at=now()',f'TRUNCATE {table} CASCADE'):
            with engine.begin() as connection:
                with pytest.raises(DBAPIError):
                    with connection.begin_nested():connection.execute(text(sql))
            with pytest.raises(DBAPIError):
                with owner.begin_nested():owner.execute(text(sql))
            owner.rollback()


def test_bundle_bounds_are_explicit_when_cited_history_exceeds_budget(api):
    client,_,engine,_=api;headers,event,incident=failure(api)
    with Session(engine) as s,s.begin():
        for index in range(110):
            row,_=observe(s,UUID(event['job_id']),'airflow','source_scan',{'status':'complete'},datetime.now(timezone.utc),'ref'+str(index))
            s.add(IncidentHistory(incident_id=UUID(incident['id']),action='observed',evidence_key='ref'+str(index),
                evidence={'table':'observations','id':str(row.id)},actor='detector-v1',occurred_at=datetime.now(timezone.utc)))
    r=client.post('/v1/incidents/'+incident['id']+'/evidence-bundles',headers=headers)
    assert r.status_code==201,r.text
    body=r.json()['payload']
    assert body['truncated'] and 'evidence_limit' in body['missing_evidence'] and len(body['items'])<=100
