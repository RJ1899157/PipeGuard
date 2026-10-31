from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import BaseModel

from test_api import api, producer
from pipeguard.api.pagination import SnapshotStore


class Item(BaseModel):
    value: str


def test_snapshot_bounds_scope_expiry_and_reuse(monkeypatch):
    import pipeguard.api.pagination as pagination
    now = [10.0]
    monkeypatch.setattr(pagination.time, 'monotonic', lambda: now[0])
    store = SnapshotStore()
    store.max_entries = 1
    principal = SimpleNamespace(admin=True, integration_id=None)
    load = lambda cap: ([Item(value='original')], {})
    first = store.page(principal, ('runs',), 'new', load, limit=1, offset=0)
    token = first['snapshot']['token']
    assert len(token) == 43 and first['snapshot']['captured_at'] < first['snapshot']['expires_at']
    def unavailable(cap):
        raise AssertionError('existing snapshots must not query current data')
    assert store.page(principal, ('runs',), token, unavailable, limit=1, offset=0) == first
    for caller, scope in [(SimpleNamespace(admin=False, integration_id='other'), ('runs',)),
                          (principal, ('jobs',))]:
        with pytest.raises(HTTPException) as error:
            store.page(caller, scope, token, unavailable, limit=1, offset=0)
        assert error.value.status_code == 410
    with pytest.raises(HTTPException) as error:
        store.page(principal, ('runs',), 'new', load, limit=1, offset=0)
    assert error.value.status_code == 413
    assert store.page(principal, ('runs',), token, unavailable, limit=1, offset=0) == first
    now[0] += store.ttl_seconds
    with pytest.raises(HTTPException) as error:
        store.page(principal, ('runs',), token, unavailable, limit=1, offset=0)
    assert error.value.status_code == 410
    assert store.page(principal, ('runs',), 'new', load, limit=1, offset=0)['items'] == [{'value': 'original'}]


@pytest.mark.parametrize('bound', ['max_rows', 'max_bytes', 'total_bytes'])
def test_snapshot_capacity_never_returns_a_silently_truncated_page(bound):
    store = SnapshotStore()
    setattr(store, bound, 0)
    with pytest.raises(HTTPException) as error:
        store.page(SimpleNamespace(admin=True, integration_id=None), ('runs',), 'new',
                   lambda cap: ([Item(value='one')], {}), limit=1, offset=0)
    assert error.value.status_code == 413 and error.value.detail == 'snapshot_capacity_exceeded'


def test_concurrent_capture_admission_is_bounded_and_cached_reads_continue():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Event
    store = SnapshotStore()
    caller = SimpleNamespace(admin=True, integration_id=None)
    load = lambda cap: ([Item(value='cached')], {})
    cached = store.page(caller, ('runs',), 'new', load, limit=1, offset=0)
    started = Barrier(3)
    finish = Event()
    def blocked(cap):
        started.wait(timeout=5)
        assert finish.wait(timeout=5)
        return [Item(value='captured')], {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        work = [pool.submit(store.page, caller, ('runs',), 'new', blocked, limit=1, offset=0) for _ in range(2)]
        try:
            started.wait(timeout=5)
            with pytest.raises(HTTPException) as error:
                store.page(caller, ('runs',), 'new', load, limit=1, offset=0)
            assert error.value.status_code == 503 and error.value.detail == 'snapshot_busy'
            assert store.page(caller, ('runs',), cached['snapshot']['token'], load, limit=1, offset=0) == cached
        finally:
            finish.set()
        assert len({future.result()['snapshot']['token'] for future in work}) == 2
    assert store.page(caller, ('runs',), 'new', load, limit=1, offset=0)['items'] == cached['items']


def test_run_snapshot_keeps_membership_and_values_across_inserts_and_updates(api):
    client, admin, _, _ = api
    headers, event, _ = producer(api)
    for number in (1, 2):
        assert client.post('/v1/events', headers=headers, json=event | {
            'external_run_id': 'run-' + str(number), 'event_id': 'event-' + str(number),
            'state': 'succeeded'}).status_code == 202
    path = '/v1/runs?job_id=' + event['job_id']
    capture = client.get(path + '&snapshot=new&limit=1', headers=headers).json()
    token = capture['snapshot']['token']
    second = client.get(path + '&snapshot=' + token + '&limit=1&offset=1', headers=headers).json()
    original = capture['items'] + second['items']
    assert len({row['id'] for row in original}) == 2
    assert client.post('/v1/events', headers=headers, json=event | {
        'external_run_id': original[1]['external_run_id'], 'event_id': 'conflicting-terminal', 'state': 'failed'}).status_code == 202
    assert client.post('/v1/events', headers=headers, json=event | {
        'external_run_id': 'new-run', 'event_id': 'new-run', 'state': 'succeeded'}).status_code == 202
    assert client.get(path + '&snapshot=' + token + '&limit=1', headers=headers).json() == capture
    assert client.get(path + '&snapshot=' + token + '&limit=1&offset=1', headers=headers).json() == second
    live = client.get(path, headers=headers).json()['items']
    assert len(live) == 3 and any(row['state'] == 'unknown' for row in live)
    assert client.get(path + '&snapshot=' + token, headers=admin).status_code == 410
    assert client.get('/v1/runs?snapshot=' + token, headers=headers).status_code == 410
    assert client.get(path + '&snapshot=missing', headers=headers).status_code == 410


def test_catalog_and_attempt_snapshot_pages_are_scoped_and_stable(api):
    client, admin, _, _ = api
    headers, event, _ = producer(api)
    other, _, _ = producer(api, 'other')
    for path, caller in [('/v1/jobs', headers), ('/v1/integrations', admin), ('/v1/monitor-policies', headers)]:
        first = client.get(path + '?snapshot=new&limit=1', headers=caller)
        assert first.status_code == 200, first.text
        captured = first.json()
        assert captured['snapshot']['total_count'] >= 0
        token = captured['snapshot']['token']
        assert client.get(path + '?snapshot=' + token + '&limit=1', headers=caller).json() == captured
        if caller == headers:
            assert client.get(path + '?snapshot=' + token, headers=other).status_code == 410
    client.post('/v1/events', headers=headers, json=event)
    run = client.get('/v1/runs', headers=headers).json()['items'][0]
    path = '/v1/runs/' + run['id'] + '/attempts'
    captured = client.get(path + '?snapshot=new', headers=headers).json()
    token = captured['snapshot']['token']
    client.post('/v1/events', headers=headers, json=event | {'event_id': 'retry', 'attempt_number': 2})
    assert len(client.get(path, headers=headers).json()['items']) == 2
    assert len(client.get(path + '?snapshot=' + token, headers=headers).json()['items']) == 1


def test_quality_summary_covers_hidden_pages_and_is_frozen_with_snapshot(api):
    client, _, _, _ = api
    headers, event, _ = producer(api)
    path = '/v1/jobs/' + event['job_id'] + '/quality-reports'
    base = {key: value for key, value in event.items() if key != 'state'}
    for number in range(55):
        report = base | {'event_id': 'quality-' + str(number), 'inventory_complete': True,
            'checks': [{'rule_id': 'orders.unique', 'rule_version': 'a' * 64,
                        'status': 'fail' if number == 0 else 'pass'}]}
        assert client.post('/v1/quality-reports', headers=headers, json=report).status_code == 202
    first = client.get(path + '?limit=50&snapshot=new&external_run_id=run-1&attempt_number=1', headers=headers).json()
    assert all(row['payload']['checks'][0]['status'] == 'pass' for row in first['items'])
    assert first['summary'] == {'report_count': 55, 'conflicting_rule_count': 1, 'has_conflicts': True, 'scope': 'filtered_history'}
    token = first['snapshot']['token']
    assert client.post('/v1/quality-reports', headers=headers, json=report | {'event_id': 'later'}).status_code == 202
    same = client.get(path + '?limit=50&snapshot=' + token + '&external_run_id=run-1&attempt_number=1', headers=headers).json()
    assert same == first
    assert client.get(path, headers=headers).json()['summary']['report_count'] == 56
    assert client.get(path + '?attempt_number=2', headers=headers).json()['summary']['has_conflicts'] is False
    assert client.get(path + '?snapshot=' + token + '&attempt_number=2', headers=headers).status_code == 410


def test_incident_and_history_snapshots_keep_old_projection_and_acknowledgements(api):
    from pipeguard.detection.service import evaluate_job
    client, admin, engine, _ = api
    headers, event, _ = producer(api)
    client.post('/v1/monitor-policies', headers=admin, json={'job_id': event['job_id'], 'quality_required': False})
    client.post('/v1/events', headers=headers, json=event | {'state': 'failed'})
    evaluate_job(engine, event['job_id'])
    queue = client.get('/v1/incidents?snapshot=new', headers=headers).json()
    incident = next(row for row in queue['items'] if row['condition'] == 'execution_failure')
    path = '/v1/incidents/' + incident['id'] + '/history'
    history = client.get(path + '?snapshot=new', headers=headers).json()
    client.post('/v1/incidents/' + incident['id'] + '/acknowledge', headers=admin)
    assert len(client.get(path, headers=headers).json()) == len(history['items']) + 1
    assert client.get(path + '?snapshot=' + history['snapshot']['token'], headers=headers).json() == history
    client.post('/v1/events', headers=headers, json=event | {
        'event_id': 'recovery', 'attempt_number': 2, 'state': 'succeeded'})
    evaluate_job(engine, event['job_id'])
    assert client.get('/v1/incidents?snapshot=' + queue['snapshot']['token'], headers=headers).json() == queue


def test_snapshot_response_mutation_cannot_change_cached_values():
    store = SnapshotStore()
    principal = SimpleNamespace(admin=True, integration_id=None)
    extra = {"summary": {"report_count": 1}}
    first = store.page(principal, ('runs',), 'new',
                       lambda cap: ([Item(value='original')], extra), limit=1, offset=0)
    token = first['snapshot']['token']
    first['items'][0]['value'] = 'response mutation'
    first['summary']['report_count'] = 99
    extra['summary']['report_count'] = 100
    next_page = store.page(principal, ('runs',), token, None, limit=1, offset=0)
    assert next_page['items'] == [{'value': 'original'}]
    assert next_page['summary']['report_count'] == 1
