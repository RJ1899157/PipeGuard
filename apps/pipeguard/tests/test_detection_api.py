from sqlalchemy import select
from sqlalchemy.orm import Session
from test_api import api, producer
from pipeguard.detection.service import evaluate_job
from pipeguard.db.models import Incident


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
