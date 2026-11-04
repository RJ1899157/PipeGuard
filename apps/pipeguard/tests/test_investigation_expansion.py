"""Small complete API fixtures for the three previously untested live classes."""
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from test_api import api, producer
from pipeguard.detection.service import evaluate_job, observe, digest
from pipeguard.investigation.core import project_bundle, supported_categories
from pipeguard.investigation.evaluation import score


def expanded_cases(api):
    client, admin, engine, _ = api
    cases = []
    now = datetime.now(timezone.utc) - timedelta(seconds=5)
    for name, condition, category in [
        ('quality_failure', 'quality_failure', 'reported_quality_failure'),
        ('source_gap', 'source_coverage', 'source_evidence_gap'),
        ('same_attempt_conflict', 'execution_failure', 'conflicting_execution_reports'),
    ]:
        headers, event, _ = producer(api, 'expanded_' + name)
        event.update(external_run_id='expanded-run', occurred_at=now.isoformat())
        policy = {'job_id': event['job_id'], 'quality_required': name == 'quality_failure'}
        if name == 'source_gap':
            policy.update(airflow_dag_id='synthetic_gap', airflow_task_id='synthetic_task')
        assert client.post('/v1/monitor-policies', headers=admin, json=policy).status_code == 201
        # Monitoring loss is demonstrated alongside a successful producer report;
        # it must not be conflated with a confirmed business execution failure.
        terminal = 'failed' if name == 'same_attempt_conflict' else 'succeeded'
        assert client.post('/v1/events', headers=headers, json=event | {'state': terminal}).status_code == 202
        if name == 'quality_failure':
            report = {k: event[k] for k in ('schema_version', 'integration_id', 'job_id',
                'external_run_id', 'attempt_number', 'occurred_at')}
            report.update(event_id='expanded-quality', inventory_complete=True,
                checks=[{'rule_id':'orders.unique','rule_version':'a'*64,'status':'fail','failures':2},
                        {'rule_id':'orders.present','rule_version':'b'*64,'status':'pass'}])
            assert client.post('/v1/quality-reports', headers=headers, json=report).status_code == 202
        elif name == 'source_gap':
            with Session(engine) as session, session.begin():
                observe(session, UUID(event['job_id']), 'airflow', 'source_scan',
                    {'status':'incomplete','error_code':'source_unreachable'}, now, 'expanded-gap')
        else:
            assert client.post('/v1/events', headers=headers, json=event | {
                'event_id':'expanded-conflict','state':'succeeded',
                'occurred_at':(now+timedelta(seconds=1)).isoformat()}).status_code == 202
        evaluate_job(engine, event['job_id'])
        incidents = client.get('/v1/incidents', headers=headers).json()
        incident = next(i for i in incidents if i['condition'] == condition)
        response = client.post(f"/v1/incidents/{incident['id']}/evidence-bundles", headers=admin)
        assert response.status_code == 201, response.text
        bundle = response.json()
        packet, _ = project_bundle(bundle)
        assert not bundle['payload']['truncated']
        assert supported_categories(packet) == [category]
        cases.append({'name':name,'condition':condition,'incident_id':incident['id'],
            'bundle_id':bundle['id'],'bundle_hash':bundle['payload_hash'],'packet_hash':digest(packet),
            'expected_categories':[category],'must_abstain':False,'packet':packet})
    return cases


@pytest.mark.parametrize('index', range(3))
def test_complete_expanded_fixture_projects_expected_claim(api, index):
    case = expanded_cases(api)[index]
    packet = case['packet']
    category = case['expected_categories'][0]
    from pipeguard.investigation.core import supports
    support = next(i['citation'] for i in packet['items'] if supports(category, i['facts']))
    answer = {'abstained':False,'abstention_reason':'','next_checks':['request_missing_evidence'],
        'hypotheses':[{'category':category,'explanation':'A reported condition; its underlying cause is not established.',
            'confidence':'low','supporting_evidence':[support],'contradicting_evidence':'none'}]}
    assert score(answer, packet, [category])['useful']
    facts = [i['facts'] for i in packet['items']]
    if index == 0:
        assert any(f.get('quality_counts') == {'pass':1,'fail':1,'error':0,'skipped':0,'unknown':0} for f in facts)
    elif index == 1:
        assert any(f.get('state') == 'succeeded' for f in facts)
        assert any(f.get('scan_status') == 'incomplete' for f in facts)
    else:
        claims = [f for f in facts if f.get('attempt') == 1 and f.get('run') == 'run_1']
        assert {'failed','succeeded'} <= {f.get('state') for f in claims}
        assert any(f.get('reconciliation_required') is True for f in facts)
