import json
import secrets
from urllib.error import URLError
from uuid import uuid4

import pytest
from orders_pipeline.observer import Observer
from orders_pipeline.runner import execute


@pytest.fixture
def observer(tmp_path):
    return Observer(str(uuid4()),str(uuid4()),secrets.token_urlsafe(32),tmp_path)


class Response:
    status=202
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def read(self,*args): return json.dumps({"event_id":str(uuid4()),"processing_state":"processed"}).encode()


class Opener:
    def __init__(self): self.requests=[]
    def open(self,request,**kwargs):
        self.requests.append(request)
        return Response()


def test_observation_identity_and_timestamp_survive_repeat(observer,monkeypatch):
    opener=Opener()
    monkeypatch.setattr("orders_pipeline.observer.build_opener",lambda *args:opener)
    assert observer.emit("same-run",1,"running")
    original=list(observer.directory.glob("*.json"))[0].read_bytes()
    assert observer.emit("same-run",1,"running")
    assert len(opener.requests)==1
    assert list(observer.directory.glob("*.json"))[0].read_bytes()==original
    assert observer.token not in original.decode()


def test_outage_retains_event_and_replay_delivers_it(observer,monkeypatch):
    class Offline:
        def open(self,*args,**kwargs): raise URLError("synthetic outage")
    monkeypatch.setattr("orders_pipeline.observer.build_opener",lambda *args:Offline())
    assert not observer.emit("offline-run",1,"failed","source_unavailable")
    original=list(observer.directory.glob("*.json"))[0].read_bytes()
    assert not list(observer.directory.glob("*.sent"))
    opener=Opener()
    monkeypatch.setattr("orders_pipeline.observer.build_opener",lambda *args:opener)
    assert observer.replay()=={"observations":1,"acknowledged":1,"pending":0}
    assert list(observer.directory.glob("*.json"))[0].read_bytes()==original


def test_conflicting_local_event_cannot_overwrite_history(observer,monkeypatch):
    monkeypatch.setattr("orders_pipeline.observer.build_opener",lambda *args:Opener())
    observer.emit("same-run",1,"failed","source_unavailable")
    with pytest.raises(ValueError,match="Conflicting local"):
        observer.emit("same-run",1,"failed","execution_error")


@pytest.mark.parametrize("url",["https://example.com","http://127.0.0.1:9000","http://user:pass@localhost:8000","http://localhost:8000/?token=x"])
def test_destination_is_restricted(observer,url):
    with pytest.raises(ValueError):
        Observer(observer.integration_id,observer.job_id,observer.token,observer.outbox,url)


def test_partial_config_fails_closed(tmp_path,monkeypatch):
    for key in ("PIPEGUARD_INTEGRATION_ID","PIPEGUARD_JOB_ID","PIPEGUARD_PRODUCER_TOKEN"):
        monkeypatch.delenv(key,raising=False)
    assert Observer.from_environment(tmp_path) is None
    monkeypatch.setenv("PIPEGUARD_INTEGRATION_ID",str(uuid4()))
    with pytest.raises(ValueError,match="Incomplete"):
        Observer.from_environment(tmp_path)


def test_first_failure_precedes_work_and_retry_can_succeed(monkeypatch):
    import orders_pipeline.runner as runner
    observed=[]
    class Recording:
        def emit(self,*args):
            observed.append(args)
            return True
    work=[]
    def build(*args):
        work.append(True)
        return {"dbt_succeeded":True}
    monkeypatch.setattr(runner,"run",build)
    with pytest.raises(RuntimeError,match="controlled"):
        execute(None,None,Recording(),"retry",1,True)
    assert work==[]
    assert observed==[("retry",1,"running"),("retry",1,"failed","source_unavailable")]
    assert execute(None,None,Recording(),"retry",2,True)["dbt_succeeded"]
    assert observed[-1]==("retry",2,"succeeded",None)


def test_monitoring_http_outage_does_not_change_business_success(monkeypatch):
    import orders_pipeline.runner as runner
    class Offline:
        def emit(self,*args): return False
    monkeypatch.setattr(runner,"run",lambda *args:{"dbt_succeeded":True})
    result=execute(None,None,Offline(),"offline",1)
    assert result["dbt_succeeded"] and result["monitoring"]=="pending"


def test_dbt_subprocess_does_not_receive_monitoring_or_airflow_credentials(warehouse,monkeypatch):
    import orders_pipeline.runner as runner
    from subprocess import CompletedProcess
    settings,_=warehouse
    monkeypatch.setenv("PIPEGUARD_PRODUCER_TOKEN","SYNTHETIC_TOKEN_FOR_FILTER_CHECK")
    monkeypatch.setenv("AIRFLOW_LOCAL_DB_PASSWORD","SYNTHETIC_PASSWORD_FOR_FILTER_CHECK")
    captured=[]
    def invocation(command,**kwargs):
        captured.append(kwargs["env"])
        return CompletedProcess(command,0)
    monkeypatch.setattr(runner.subprocess,"run",invocation)
    runner.run(runner.ROOT/"data/orders.csv",settings)
    assert not any(key.startswith(("PIPEGUARD_","AIRFLOW")) for key in captured[0])
    assert captured[0]["DBT_ENV_SECRET_ORDERS_PASSWORD"]==settings.password


def test_arbitrary_error_text_never_enters_outbox(observer):
    with pytest.raises(ValueError,match="Unsupported error"):
        observer.emit("private-error",1,"failed","SYNTHETIC_PRIVATE_ERROR_TEXT")
    assert not list(observer.outbox.rglob("*.json"))
