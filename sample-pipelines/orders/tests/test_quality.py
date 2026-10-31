from hashlib import sha256
import json
from orders_pipeline.quality import extract
from test_observer import observer


def files(path,status='pass',include=True):
    manifest={'metadata':{'dbt_version':'1.12.6'},'nodes':{'test.orders.unique':{
        'resource_type':'test','raw_code':'SECRET_SQL','config':{},'depends_on':{'nodes':[]}}},
        'macros':{'macro.test':{'macro_sql':'SECRET_MACRO'}}}
    results={'results':[{'unique_id':'test.orders.unique','status':status,'failures':0,'message':'SECRET_ERROR'}] if include else []}
    (path/'manifest.json').write_text(json.dumps(manifest));(path/'run_results.json').write_text(json.dumps(results))


def test_complete_inventory_contains_outcomes_not_sql_or_errors(tmp_path):
    files(tmp_path)
    result=extract(tmp_path)
    assert result['inventory_complete'] and result['checks'][0]['status']=='pass'
    assert 'SECRET' not in json.dumps(result)
    assert len(result['checks'][0]['rule_version'])==64


def test_missing_partial_or_invalid_artifacts_are_incomplete(tmp_path):
    assert extract(tmp_path)=={'checks':[],'inventory_complete':False}
    files(tmp_path,include=False)
    result=extract(tmp_path)
    assert not result['inventory_complete'] and result['checks'][0]['status']=='unknown'
    (tmp_path/'run_results.json').write_text('{')
    assert not extract(tmp_path)['inventory_complete']


def test_warning_error_skip_and_unrecognized_outcomes_are_not_passes(tmp_path):
    for state,expected in [('warn','fail'),('error','error'),('skipped','skipped'),('new','unknown')]:
        files(tmp_path,state)
        assert extract(tmp_path)['checks'][0]['status']==expected


def test_rule_version_changes_with_macro_content(tmp_path):
    files(tmp_path);first=extract(tmp_path)['checks'][0]['rule_version']
    path=tmp_path/'manifest.json';manifest=json.loads(path.read_text())
    manifest['macros']['macro.test']['macro_sql']='changed';path.write_text(json.dumps(manifest))
    assert extract(tmp_path)['checks'][0]['rule_version']!=first


def test_quality_outbox_survives_outage_and_uses_quality_endpoint(observer,monkeypatch):
    from test_observer import Opener
    opener=Opener()
    monkeypatch.setattr('orders_pipeline.observer.build_opener',lambda *args:opener)
    quality={'inventory_complete':True,'checks':[{'rule_id':'orders.unique','rule_version':'a'*64,'status':'fail'}]}
    assert observer.emit_quality('quality-run',1,quality)
    assert opener.requests[0].full_url.endswith('/v1/quality-reports')
