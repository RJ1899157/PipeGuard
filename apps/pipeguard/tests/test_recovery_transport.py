"""Fixed recovery transport boundary; all responses synthetic, no network access."""
from uuid import uuid4
from urllib.error import HTTPError, URLError

import pytest

from pipeguard.recovery.airflow import AirflowRecoveryClient, DAG, USER, parameters
from pipeguard.recovery.service import RecoveryRejected


def response(action, state='queued'):
    body = parameters(action)['body']
    return body | {'dag_id': DAG, 'state': state, 'run_type': 'manual',
        'triggered_by': 'rest_api', 'triggering_user_name': USER, 'note': 'PRIVATE_RAW_NOTE'}


@pytest.mark.parametrize('status,state', [(200, 'queued'), (201, 'queued'), (400, 'rejected'), (401, 'rejected'),
    (403, 'rejected'), (404, 'rejected'), (422, 'rejected'), (409, 'unknown'), (429, 'unknown'), (500, 'unknown'), (301, 'unknown')])
def test_business_post_is_sent_once_and_never_refreshes_or_retries(status, state):
    action = uuid4(); client = AirflowRecoveryClient(USER, 'PRIVATE_PASSWORD'); client._token='PRIVATE_TOKEN'
    calls=[]
    def request(method, path, body=None):
        calls.append((method, path, body))
        return status, response(action)
    client._request=request
    result=client.submit(action)
    assert result['state']==state and len(calls)==1
    assert calls[0]==('POST', '/api/v2/dags/'+DAG+'/dagRuns', parameters(action)['body'])
    assert 'PRIVATE' not in str(result)


@pytest.mark.parametrize('field,value', [('dag_id','other'), ('dag_run_id','other'), ('conf',{}),
    ('run_type','scheduled'), ('triggered_by','ui'), ('triggering_user_name','RJ1899157'), ('logical_date','2026-01-01')])
def test_identity_mismatch_is_never_accepted(field, value):
    action=uuid4(); result=response(action) | {field:value}
    assert AirflowRecoveryClient._fact(action, result)['state']=='conflict'


@pytest.mark.parametrize('fault', ['timeout','unreachable','invalid_json','oversize','recursive_json','incomplete_body'])
def test_mutation_transport_failure_is_unknown_and_redacted(fault):
    action=uuid4(); client=AirflowRecoveryClient(USER, 'PRIVATE_PASSWORD'); client._token='PRIVATE_TOKEN'
    requests=[]
    class Response:
        status=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self, limit):
            assert limit==2_000_001
            if fault=='incomplete_body':
                from http.client import IncompleteRead
                raise IncompleteRead(b'PRIVATE')
            if fault=='invalid_json':return b'PRIVATE_INVALID_JSON'
            if fault=='recursive_json':return b'['*10000+b']'*10000
            return b'x'*2_000_001
    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            assert request.full_url=='http://127.0.0.1:8080/api/v2/dags/'+DAG+'/dagRuns'
            assert timeout==5 and request.get_method()=='POST'
            if fault=='timeout':raise TimeoutError('PRIVATE')
            if fault=='unreachable':raise URLError('PRIVATE')
            return Response()
    client._opener=Opener()
    result=client.submit(action)
    assert result['state']=='unknown' and 'PRIVATE' not in str(result) and len(requests)==1


def test_unauthenticated_submit_does_not_attempt_authentication_or_post():
    client=AirflowRecoveryClient(USER,'private')
    client._request=lambda *args:pytest.fail('Unexpected network request')
    assert client.submit(uuid4())['state']=='rejected'
    with pytest.raises(RecoveryRejected):AirflowRecoveryClient('RJ1899157','private')
    with pytest.raises(RecoveryRejected):AirflowRecoveryClient(USER,'')


def test_reconciliation_not_found_cannot_resubmit_and_read_refresh_is_bounded():
    client=AirflowRecoveryClient(USER,'PRIVATE'); client._token='expired'; calls=[]
    def request(method,path,body=None):
        calls.append((method,path))
        if path=='/auth/token':return 200,{'access_token':'fresh'}
        return (401,None) if client._token=='expired' else (404,None)
    client._request=request
    result=client.lookup(uuid4())
    assert result['state']=='unknown' and result['code']=='recovery_external_not_found'
    assert [method for method,_ in calls]==['GET','POST','GET']
    assert calls[1][1]=='/auth/token'


@pytest.mark.parametrize('fault', ['none','paused','imports','unhealthy','active','missing_failed','duplicate','truncated','invalid_total','malformed'])
def test_preflight_requires_healthy_unpaused_settled_complete_inventory(fault):
    client=AirflowRecoveryClient(USER,'private')
    def get(path):
        if path.endswith('/health'):
            return 200,{name:{'status':'unhealthy' if fault=='unhealthy' and name=='scheduler' else 'healthy'}
                        for name in ('metadatabase','scheduler','dag_processor')}
        if path.endswith('/'+DAG):return 200,{'dag_id':DAG,'is_paused':fault=='paused','has_import_errors':fault=='imports'}
        run={'dag_id':DAG,'dag_run_id':'failed-original','state':'running' if fault=='active' else 'failed'}
        if fault=='malformed':return 200,[]
        if fault=='missing_failed':run['dag_run_id']='another'
        runs=[run,run] if fault=='duplicate' else [run]
        total='1' if fault=='invalid_total' else 2 if fault in {'truncated','duplicate'} else 1
        return 200,{'dag_runs':runs,'total_entries':total}
    client._get=get
    if fault=='none':client.preflight('failed-original')
    else:
        with pytest.raises(RecoveryRejected):client.preflight('failed-original')


def test_http_errors_are_closed_and_never_read_or_leaked():
    client=AirflowRecoveryClient(USER,'PRIVATE'); client._token='PRIVATE_TOKEN'
    class Opener:
        def open(self,*args,**kwargs):raise HTTPError('PRIVATE_URL',503,'PRIVATE_BODY',{},None)
    client._opener=Opener()
    assert client.submit(uuid4())=={'state':'unknown','code':'recovery_source_response_uncertain','facts':{'http_status':503}}


def test_unknown_or_malformed_run_state_never_claims_success():
    action=uuid4()
    assert AirflowRecoveryClient._fact(action,response(action,[]))['state']=='unknown'
    result=response(action);result.pop('logical_date')
    assert AirflowRecoveryClient._fact(action,result)['state']=='conflict'
