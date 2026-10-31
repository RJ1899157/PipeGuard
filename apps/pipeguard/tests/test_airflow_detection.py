import pytest
from pipeguard.detection.airflow import AirflowClient, SourceUnavailable, external_id, STATES


class Fake(AirflowClient):
    def __init__(self, state="success", number=1, history=None):
        self.state=state;self.number=number;self.history=history or []
        self.paths=[]
    def get(self,path):
        self.paths.append(path)
        if path.endswith('/monitor/health'):
            return {k:{"status":"healthy"} for k in ("metadatabase","scheduler","dag_processor")}
        if path=='/api/v2/dags/dag': return {"has_import_errors":False,"is_paused":False}
        if '/dagRuns?' in path:
            return {"dag_runs":[{"dag_run_id":"run","queued_at":"2026-10-31T10:00:00Z"}],"total_entries":1}
        if path.endswith('/tries'): return {"task_instances":self.history,"total_entries":len(self.history)}
        return {"try_number":self.number,"state":self.state,"map_index":-1,
                "start_date":"2026-10-31T10:00:01Z","end_date":"2026-10-31T10:00:02Z"}


@pytest.mark.parametrize("raw,expected",list(STATES.items())+[("new_unrecognized_state","unknown")])
def test_all_documented_task_states_and_unknown(raw,expected):
    result=Fake(raw).scan("dag","task")
    assert result[0][1]["state"]==expected
    assert result[0][1]["external_run_id"]==external_id("dag","run","task")


def test_missing_try_history_is_explicit_not_success():
    with pytest.raises(SourceUnavailable,match="incomplete_history"):
        Fake(number=2).scan("dag","task")


def test_native_retry_keeps_both_tries():
    source=Fake(number=2,history=[{"try_number":1,"state":"failed","start_date":"2026-10-31T10:00:00Z",
                                 "end_date":"2026-10-31T10:00:01Z"}])
    result=source.scan('dag','task')
    assert [(p['attempt_number'],p['state']) for _,p in result]==[(1,'failed'),(2,'succeeded')]


@pytest.mark.parametrize("fault",["pagination","history","component","import","mapping","timestamp","malformed"])
def test_incomplete_or_unhealthy_sources_never_look_complete(fault):
    client=Fake();original=client.get
    def get(path):
        value=original(path)
        if fault=='pagination' and '/dagRuns?' in path: value['total_entries']=2
        if fault=='history' and path.endswith('/tries'): value['total_entries']=1
        if fault=='component' and path.endswith('/monitor/health'): value['scheduler']['status']='unhealthy'
        if fault=='import' and path=='/api/v2/dags/dag': value['has_import_errors']=True
        if fault=='mapping' and '/taskInstances/task' in path and not path.endswith('/tries'): value['map_index']=0
        if fault=='timestamp' and '/dagRuns?' in path: value['dag_runs'][0]['queued_at']=None
        if fault=='timestamp' and '/taskInstances/task' in path and not path.endswith('/tries'): value['start_date']=value['end_date']=None
        if fault=='malformed' and '/dagRuns?' in path: value['total_entries']='secret_invalid_number'
        return value
    client.get=get
    with pytest.raises(SourceUnavailable) as error:client.scan('dag','task')
    assert 'secret_invalid_number' not in str(error.value)


def test_authentication_requires_separate_viewer_identity():
    with pytest.raises(ValueError):AirflowClient('RJ1899157','unused')


def test_payload_allowlist_drops_conf_sql_logs_and_secrets():
    client=Fake();original=client.get
    def get(path):
        return original(path)|{'conf':{'password':'SECRET_MARKER'},'executor_config':{'token':'SECRET_MARKER'},'note':'SECRET_MARKER'}
    client.get=get
    assert 'SECRET_MARKER' not in str(client.scan('dag','task'))


@pytest.mark.parametrize('code,expected',[(401,'source_authentication_failed'),(403,'source_authentication_failed'),(404,'source_http_error'),(500,'source_http_error')])
def test_http_errors_are_safe_and_expire_bad_tokens(code,expected):
    from urllib.error import HTTPError
    client=AirflowClient('pipeguard_observer','SECRET_PASSWORD');client._token='SECRET_TOKEN'
    class Offline:
        def open(self,*args,**kwargs):raise HTTPError('SECRET_URL',code,'SECRET_BODY',{},None)
    client._opener=Offline()
    with pytest.raises(SourceUnavailable,match=expected) as error:client._request('/api/v2/dags')
    assert 'SECRET' not in str(error.value)
    if code in (401,403):assert client._token is None


@pytest.mark.parametrize('fault',['timeout','unreachable','invalid_json','oversize'])
def test_transport_and_payload_failures_are_explicit(fault):
    from urllib.error import URLError
    client=AirflowClient('pipeguard_observer','unused')
    class Result:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,*args):return b'{' if fault=='invalid_json' else b'x'*2_000_001
    class Opener:
        def open(self,*args,**kwargs):
            if fault=='timeout':raise TimeoutError('SECRET')
            if fault=='unreachable':raise URLError('SECRET')
            return Result()
    client._opener=Opener()
    with pytest.raises(SourceUnavailable) as error:client._request('/api/v2/dags')
    assert 'SECRET' not in str(error.value)


def test_expired_token_refreshes_once_and_persistent_denial_is_bounded():
    client=AirflowClient('pipeguard_observer','unused');client._token='expired'
    calls=[]
    def request(path,body=None):
        calls.append(path)
        if path=='/auth/token':return {'access_token':'fresh'}
        if client._token=='expired':
            client._token=None
            raise SourceUnavailable('source_authentication_failed')
        return {'ok':True}
    client._request=request
    assert client.get('/read-only')=={'ok':True}
    assert calls==['/read-only','/auth/token','/read-only']
    calls.clear()
    def denied(path,body=None):
        calls.append(path)
        if path=='/auth/token':return {'access_token':'fresh'}
        raise SourceUnavailable('source_authentication_failed')
    client._request=denied
    with pytest.raises(SourceUnavailable):client.get('/forbidden')
    assert len(calls)==3


def test_huge_try_number_reports_gap_without_allocating_a_range():
    with pytest.raises(SourceUnavailable,match='incomplete_history'):
        Fake(number=2147483647).scan('dag','task')
