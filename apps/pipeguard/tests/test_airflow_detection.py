from datetime import datetime, timezone
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
