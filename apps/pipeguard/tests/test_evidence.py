from datetime import datetime,timezone
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import DBAPIError

from test_api import api,producer
from test_lineage import report,post
from pipeguard.db.models import IncidentHistory
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


def _scope_fixture(api, *, airflow=False):
    client, admin, engine, _ = api
    headers, event, _ = producer(api, 'scope-proof')
    policy = {'job_id': event['job_id'], 'quality_required': False}
    if airflow:
        policy.update(airflow_dag_id='scope-proof', airflow_task_id='task')
    assert client.post('/v1/monitor-policies', headers=admin, json=policy).status_code == 201
    return client, admin, engine, headers, event


def _scope_event(client, headers, event, run, state='succeeded'):
    assert client.post('/v1/events', headers=headers, json=event | {
        'event_id':run, 'external_run_id':run, 'state':state}).status_code == 202


def _scope_bundle(client, admin, incident):
    response = client.post(f"/v1/incidents/{incident['id']}/evidence-bundles", headers=admin)
    assert response.status_code == 201, response.text
    return response.json()['payload']


def test_execution_subject_does_not_include_a_separate_run_with_a_prefix_id(api):
    client, admin, engine, headers, event = _scope_fixture(api)
    for run in ('foo', 'foo:bar'):
        _scope_event(client, headers, event, run, 'failed')
    evaluate_job(engine, event['job_id'])
    incident = next(i for i in client.get('/v1/incidents', headers=admin).json()
                    if i['condition'] == 'execution_failure' and i['subject'] == 'foo:bar')
    body = _scope_bundle(client, admin, incident)
    assert body['context_scope'] == 'execution'
    assert body['external_run_ids'] == ['foo:bar']
    assert {i['summary']['external_run_id'] for i in body['items'] if i['table'] == 'runs'} == {'foo:bar'}


def test_source_coverage_stays_job_wide_when_a_run_is_named_job(api):
    client, admin, engine, headers, event = _scope_fixture(api, airflow=True)
    for run in ('job', 'other'):
        _scope_event(client, headers, event, run)
    with Session(engine) as session, session.begin():
        observe(session, UUID(event['job_id']), 'airflow', 'source_scan',
                {'status':'incomplete'}, datetime.now(timezone.utc))
    evaluate_job(engine, event['job_id'])
    incident = next(i for i in client.get('/v1/incidents', headers=admin).json() if i['condition'] == 'source_coverage')
    body = _scope_bundle(client, admin, incident)
    assert body['context_scope'] == 'job'
    assert body['external_run_ids'] == ['job', 'other']


def _scope_quality(client, headers, event, key, status):
    report = {k:event[k] for k in ('schema_version', 'integration_id', 'job_id',
        'external_run_id', 'attempt_number', 'occurred_at')}
    report.update(event_id=key, inventory_complete=True,
                  checks=[{'rule_id':'orders.unique', 'rule_version':'a'*64, 'status':status}])
    assert client.post('/v1/quality-reports', headers=headers, json=report).status_code == 202


@pytest.mark.parametrize('condition', ['quality_failure', 'quality_conflict', 'lineage_conflict'])
def test_composite_subject_uses_its_typed_suffix_not_a_run_id_prefix_or_exact_decoy(api, condition):
    client, admin, engine, headers, event = _scope_fixture(api)
    for run in ('foo', 'foo:bar'):
        _scope_event(client, headers, event, run)
    target = event | {'external_run_id':'foo:bar'}
    if condition.startswith('quality'):
        _scope_quality(client, headers, target, 'quality-failed', 'fail')
        if condition == 'quality_conflict':
            _scope_quality(client, headers, target, 'quality-passed', 'pass')
    else:
        first = report(target)
        post(client, headers, first)
        second = first | {'event_id':'lineage-failed', 'event':first['event'] | {'eventType':'FAIL'}}
        post(client, headers, second)
    evaluate_job(engine, event['job_id'])
    incident = next(i for i in client.get('/v1/incidents', headers=admin).json() if i['condition'] == condition)
    # A legal run can even equal the entire composite incident subject.
    _scope_event(client, headers, event, incident['subject'])
    body = _scope_bundle(client, admin, incident)
    assert body['context_scope'] == 'execution'
    assert body['external_run_ids'] == ['foo:bar']
    assert {i['summary']['external_run_id'] for i in body['items'] if i['table'] == 'runs'} == {'foo:bar'}


def test_quality_only_subject_remains_execution_scoped_without_a_run_projection(api):
    client, admin, engine, headers, event = _scope_fixture(api)
    _scope_event(client, headers, event, 'other')
    _scope_quality(client, headers, event | {'external_run_id':'foo:bar'}, 'quality-only', 'fail')
    evaluate_job(engine, event['job_id'])
    incident = next(i for i in client.get('/v1/incidents', headers=admin).json() if i['condition'] == 'quality_failure')
    body = _scope_bundle(client, admin, incident)
    assert body['context_scope'] == 'execution'
    assert body['external_run_ids'] == ['foo:bar']
    assert not [i for i in body['items'] if i['table'] in {'runs', 'ingested_events'}]


def test_lineage_only_subject_does_not_include_another_binding_with_a_prefix_id(api):
    client, admin, engine, headers, event = _scope_fixture(api)
    for run in ('foo', 'foo:bar'):
        body = report(event | {'external_run_id':run}, key=run)
        body.update(coverage='partial', missing_metadata=['unresolved_dependency'])
        post(client, headers, body)
    evaluate_job(engine, event['job_id'])
    incident = next(i for i in client.get('/v1/incidents', headers=admin).json()
                    if i['condition'] == 'lineage_partial' and i['subject'] == 'foo:bar')
    body = _scope_bundle(client, admin, incident)
    assert body['context_scope'] == 'execution'
    assert body['external_run_ids'] == ['foo:bar']
    assert {i['summary']['external_run_id'] for i in body['items'] if i['table'] == 'lineage_events'} == {'foo:bar'}
