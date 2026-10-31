import json
from urllib.error import URLError

from orders_pipeline.lineage import extract,gap
from test_observer import observer,Opener


def artifacts(path,parents=('source.orders',),status='success'):
    timing=[{'started_at':'2026-10-31T10:00:00Z','completed_at':'2026-10-31T10:00:01Z'}]
    manifest={'metadata':{'invocation_id':'one'},'sources':{'source.orders':{
        'resource_type':'source','database':'sample_warehouse','schema':'raw','name':'orders','identifier':'orders'}},
        'nodes':{'model.orders':{'resource_type':'model','database':'sample_warehouse','schema':'staging','alias':'orders',
            'name':'orders','depends_on':{'nodes':list(parents)},'config':{'materialized':'view'},'compiled_code':'SECRET_SQL'}}}
    results={'metadata':{'invocation_id':'one','generated_at':'2026-10-31T10:00:02Z'},'results':[
        {'unique_id':'model.orders','status':status,'timing':timing,'message':'SECRET_ERROR'}]}
    (path/'manifest.json').write_text(json.dumps(manifest));(path/'run_results.json').write_text(json.dumps(results))


def test_declared_lineage_has_stable_attempt_identity_and_artifact_hashes(tmp_path):
    artifacts(tmp_path)
    a=extract(tmp_path,'run',1);b=extract(tmp_path,'run',1);c=extract(tmp_path,'run',2)
    assert len(a)==2 and [v['event']['eventType'] for v in a]==['START','COMPLETE']
    assert a==b and a[0]['event']['run']['runId']!=c[0]['event']['run']['runId']
    assert a[0]['event']['inputs'][0]['name']=='raw.orders'
    assert a[0]['event']['outputs'][0]['name']=='staging.orders'
    assert a[0]['basis']=='declared_dbt' and a[0]['coverage']=='complete'
    assert all(len(v)==64 for v in a[0]['artifact_hashes'].values())
    assert 'SECRET' not in json.dumps(a)


def test_loader_lineage_uses_logical_input_without_local_file_path(tmp_path):
    artifacts(tmp_path)
    summary={'load_started_at':'2026-10-31T09:00:00Z','load_finished_at':'2026-10-31T09:00:01Z'}
    values=extract(tmp_path,'run',1,summary)
    loader=[v for v in values if v['event']['job']['name']=='orders-loader']
    assert len(loader)==2 and loader[0]['basis']=='producer_reported'
    assert loader[0]['event']['inputs']==[{'namespace':'file://orders-pipeline','name':'orders-input'}]
    assert loader[0]['event']['outputs'][0]['name']=='raw.orders'


def test_missing_malformed_or_mixed_artifacts_are_explicit_gaps(tmp_path):
    assert extract(tmp_path,'run',1)[0]['coverage']=='partial'
    artifacts(tmp_path);p=tmp_path/'run_results.json';data=json.loads(p.read_text())
    data['metadata']['invocation_id']='different';p.write_text(json.dumps(data))
    assert extract(tmp_path,'run',1)[0]['missing_metadata']==['artifact_mismatch']
    p.write_text('{')
    assert extract(tmp_path,'run',1)[0]['coverage']=='partial'


def test_unresolved_dependency_does_not_fabricate_edge(tmp_path):
    artifacts(tmp_path,parents=('unknown.parent',))
    values=extract(tmp_path,'run',1)
    assert all(v['coverage']=='partial' and v['event']['inputs']==[] for v in values)
    assert values[0]['missing_metadata']==['unresolved_dependency']


def test_skipped_unknown_missing_and_duplicate_results_are_incomplete(tmp_path):
    for state in ('skipped','unknown'):
        artifacts(tmp_path,status=state)
        values=extract(tmp_path,'run',1)
        assert values[-1]['event']['eventType']=='OTHER' and values[-1]['coverage']=='partial'
    artifacts(tmp_path);p=tmp_path/'run_results.json';data=json.loads(p.read_text())
    data['results'].append(data['results'][0]);p.write_text(json.dumps(data))
    assert extract(tmp_path,'run',1)[0]['missing_metadata']==['incomplete_results']


def test_unsupported_physical_relation_and_naive_timestamp_are_gaps(tmp_path):
    artifacts(tmp_path);p=tmp_path/'manifest.json';m=json.loads(p.read_text())
    m['nodes']['model.orders']['config']['materialized']='ephemeral';p.write_text(json.dumps(m))
    values=extract(tmp_path,'run',1)
    assert values[0]['coverage']=='partial' and values[0]['event']['outputs']==[]
    artifacts(tmp_path);p=tmp_path/'run_results.json';r=json.loads(p.read_text())
    r['results'][0]['timing'][0]['started_at']='2026-10-31T10:00:00';p.write_text(json.dumps(r))
    assert extract(tmp_path,'run',1)[0]['coverage']=='partial'


def test_lineage_outbox_survives_outage_and_replay(observer,monkeypatch):
    class Offline:
        def open(self,*args,**kwargs):raise URLError('controlled')
    monkeypatch.setattr('orders_pipeline.observer.build_opener',lambda *args:Offline())
    assert not observer.emit_lineage('run',1,gap('run',1))
    original=list(observer.directory.glob('*.json'))[0].read_bytes()
    # A repeated gap keeps the first event timestamp and identity.
    assert not observer.emit_lineage('run',1,gap('run',1))
    assert list(observer.directory.glob('*.json'))[0].read_bytes()==original
    opener=Opener();monkeypatch.setattr('orders_pipeline.observer.build_opener',lambda *args:opener)
    assert observer.replay()['pending']==0
    assert opener.requests[0].full_url.endswith('/v1/lineage-events')
