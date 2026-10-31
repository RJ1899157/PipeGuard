from test_api import api, producer
from pipeguard.detection.service import evaluate_job


def test_incident_scope_acknowledgement_and_quality_receipt(api):
    client,admin,engine,_=api
    first,event,_=producer(api,'one');second,other,_=producer(api,'two')
    body={'job_id':event['job_id'],'quality_required':False,'timeout_seconds':60}
    assert client.post('/v1/monitor-policies',headers=first,json=body).status_code==403
    assert client.post('/v1/monitor-policies',headers=admin,json=body).status_code==201
    assert client.post('/v1/monitor-policies',headers=admin,json=body).status_code==409
    assert client.post('/v1/events',headers=first,json=event|{'state':'failed'}).status_code==202
    evaluate_job(engine,event['job_id'])
    items=client.get('/v1/incidents',headers=first).json()
    incident=next(i for i in items if i['condition']=='execution_failure')
    path='/v1/incidents/'+incident['id']
    assert client.get('/v1/incidents',headers=second).json()==[]
    assert client.get(path,headers=second).status_code==404
    assert client.get(path+'/history',headers=second).status_code==404
    assert client.post(path+'/acknowledge',headers=first).status_code==403
    assert client.post(path+'/acknowledge',headers=admin).status_code==200
    assert client.post(path+'/acknowledge',headers=admin).status_code==200
    assert client.get(path,headers=first).json()['state']=='open'
    history=client.get(path+'/history',headers=first).json()
    assert len([h for h in history if h['action']=='acknowledged'])==1
    assert next(h for h in history if h['action']=='acknowledged')['actor']=='local_admin_token'
    report={k:v for k,v in event.items() if k!='state'}|{'event_id':'quality','checks':[
        {'rule_id':'orders.unique','rule_version':'a'*64,'status':'fail'}],'inventory_complete':True}
    response=client.post('/v1/quality-reports',headers=first,json=report)
    assert response.status_code==202
    observation='/v1/observations/'+response.json()['event_id']
    assert client.get(observation,headers=first).status_code==200
    assert client.get(observation,headers=second).status_code==404
    assert client.post('/v1/quality-reports',headers=second,json=report).status_code==403
    assert client.get('/v1/monitoring/coverage',headers=first).status_code==403
    assert client.get('/v1/monitoring/coverage',headers=admin).status_code==200
    assert client.get('/v1/incidents?limit=101',headers=admin).status_code==422


def test_invalid_quality_is_rejected_without_input_leak(api):
    client,_,_,_=api;headers,event,_=producer(api)
    body={k:v for k,v in event.items() if k!='state'}|{'inventory_complete':True,'checks':[],'sql':'SECRET'}
    response=client.post('/v1/quality-reports',headers=headers,json=body)
    assert response.status_code==422 and 'SECRET' not in response.text


def test_event_only_enrollment_removes_gap_without_inventing_capabilities(api):
    from pipeguard.detection.worker import cycle
    client,admin,engine,_=api
    headers,event,_=producer(api)
    job=event['job_id']
    assert job in client.get('/v1/monitoring/coverage',headers=admin).json()['unmonitored_job_ids']
    assert client.post('/v1/monitor-policies',headers=admin,json={
        'job_id':job,'quality_required':False,'timeout_seconds':300}).status_code==201
    cycle(engine)
    body=client.get('/v1/monitoring/coverage',headers=admin).json()
    assert body['unmonitored_job_ids']==[]
    row=next(j for j in body['jobs'] if j['job_id']==job)
    assert row['detector_status']=='fresh' and row['mode']=='event_only'
    assert row['quality_expected'] is False and row['activity_interval_seconds'] is None
    assert client.post('/v1/events',headers=headers,json=event|{'state':'failed'}).status_code==202
    cycle(engine)
    assert any(i['condition']=='execution_failure' for i in client.get('/v1/incidents',headers=headers).json())


def test_quality_history_scope_filters_and_pagination(api):
    client, admin, _, _ = api
    first, event, _ = producer(api, 'quality-first')
    second, _, _ = producer(api, 'quality-other')
    base = {k: v for k, v in event.items() if k != 'state'}
    path = '/v1/jobs/' + event['job_id'] + '/quality-reports'
    assert client.get(path).status_code == 401
    assert client.get(path, headers=second).status_code == 404
    assert client.get(path, headers=first).json()['items'] == []
    for number, attempt, status in [(1, 1, 'fail'), (2, 2, 'pass'), (3, 2, 'error')]:
        report = base | {'event_id': f'report-{number}', 'attempt_number': attempt,
            'inventory_complete': True, 'checks': [{'rule_id': 'orders.unique',
                'rule_version': 'a' * 64, 'status': status, 'failures': None}]}
        assert client.post('/v1/quality-reports', headers=first, json=report).status_code == 202
    all_rows = client.get(path, headers=admin).json()
    assert len(all_rows['items']) == 3 and not all_rows['has_more']
    assert {r['payload']['checks'][0]['status'] for r in all_rows['items']} == {'fail', 'pass', 'error'}
    assert all('received_at' in r and 'occurred_at' in r for r in all_rows['items'])
    one = client.get(path + '?limit=1&attempt_number=2&external_run_id=run-1', headers=first).json()
    assert one['has_more'] and len(one['items']) == 1
    assert one['items'][0]['payload']['attempt_number'] == 2
    two = client.get(path + '?limit=1&offset=1&attempt_number=2', headers=first).json()
    assert not two['has_more'] and one['items'][0]['id'] != two['items'][0]['id']
    assert client.get(path + '?external_run_id=other', headers=first).json()['items'] == []
    for query in ['limit=101', 'offset=-1', 'attempt_number=0', 'external_run_id=bad%26value']:
        assert client.get(path + '?' + query, headers=first).status_code == 422
    # Same report replay is not a new historical observation.
    assert client.post('/v1/quality-reports', headers=first, json=report).json()['replayed']
    assert len(client.get(path, headers=first).json()['items']) == 3
