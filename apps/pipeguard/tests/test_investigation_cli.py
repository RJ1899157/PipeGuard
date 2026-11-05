"""CLI metadata diagnostics never generate or bypass durable investigation admission."""
import importlib.util
import json
from pathlib import Path
import sys
from uuid import uuid4

import pytest

from pipeguard.investigation import groq
from pipeguard.investigation.core import InvestigationRejected


@pytest.fixture
def cli(monkeypatch):
    path = Path(__file__).resolve().parents[3] / 'scripts/investigate.py'
    spec = importlib.util.spec_from_file_location('investigation_cli_check', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv('GROQ_API_KEY', 'synthetic_private_key')
    monkeypatch.setattr(sys, 'argv', ['investigate.py', '--verify-connection', '--free-plan-confirmed'])
    return module


def test_connectivity_reads_only_fixed_model_metadata(cli, monkeypatch, capsys):
    calls = []
    def request(url, *, key, body=None):
        calls.append((url, key, body))
        return {'data': [{'id': groq.MODEL}]}
    monkeypatch.setattr(cli, 'json_request', request)
    monkeypatch.setattr(groq, 'investigate', lambda *args: pytest.fail('Diagnostic generated a response'))
    assert not hasattr(cli, 'investigate')
    cli.main()
    assert calls == [('https://api.groq.com/openai/v1/models', 'synthetic_private_key', None)]
    output = json.loads(capsys.readouterr().out)
    assert output['model_available'] is True
    assert output['generation_requested'] is False and output['billing_plan_verified'] is False
    assert 'synthetic_private_key' not in json.dumps(output)


def test_metadata_dry_run_needs_no_key_or_confirmation_and_never_connects(cli, monkeypatch, capsys):
    monkeypatch.delenv('GROQ_API_KEY')
    monkeypatch.setattr(sys, 'argv', ['investigate.py', '--verify-connection', '--dry-run'])
    monkeypatch.setattr(cli, 'json_request', lambda *args, **kwargs: pytest.fail('Dry run connected'))
    cli.main()
    output = json.loads(capsys.readouterr().out)
    assert output['groq_request_sent'] is False and output['generation_requested'] is False
    assert output['model_available'] is None


@pytest.mark.parametrize('response', [None, [], {}, {'data':None}, {'data':{}},
    {'data':[None]}, {'data':[{'id':None}]}, {'data':[{'id':''}]},
    {'data':[{'id':groq.MODEL}, {'id':1}]}, {'data':[{'id':groq.MODEL,'active':'true'}]}])
def test_malformed_model_metadata_fails_closed(cli, monkeypatch, response):
    monkeypatch.setattr(cli, 'json_request', lambda *args, **kwargs: response)
    with pytest.raises(InvestigationRejected, match='invalid_model_metadata'):
        cli.main()


@pytest.mark.parametrize('data', [[], [{'id':'another-model'}], [{'id':groq.MODEL,'active':False}]])
def test_absent_configured_model_fails_closed(cli, monkeypatch, data):
    monkeypatch.setattr(cli, 'json_request', lambda *args, **kwargs: {'data':data})
    with pytest.raises(InvestigationRejected, match='configured_model_unavailable'):
        cli.main()


def test_metadata_check_keeps_free_confirmation_and_private_key_guards(cli, monkeypatch):
    monkeypatch.setattr(cli, 'json_request', lambda *args, **kwargs: pytest.fail('Guard made a request'))
    monkeypatch.setattr(sys, 'argv', ['investigate.py', '--verify-connection'])
    with pytest.raises(InvestigationRejected, match='free_plan_confirmation_required'):
        cli.main()
    monkeypatch.setattr(sys, 'argv', ['investigate.py', '--verify-connection', '--free-plan-confirmed'])
    monkeypatch.delenv('GROQ_API_KEY')
    with pytest.raises(InvestigationRejected, match='groq_key_missing'):
        cli.main()


def test_model_metadata_transport_is_get_only(monkeypatch):
    calls = []
    class Response:
        raw = json.dumps({'data':[{'id':groq.MODEL}]}).encode()
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read1(self, size):
            result, self.raw = self.raw[:size], self.raw[size:]
            return result
    class Opener:
        def open(self, request, **kwargs):
            calls.append((request.full_url, request.get_method(), request.data))
            return Response()
    monkeypatch.setattr(groq, 'build_opener', lambda *args: Opener())
    url = 'https://api.groq.com/openai/v1/models'
    assert groq.json_request(url, key='synthetic')['data'][0]['id'] == groq.MODEL
    assert calls == [(url, 'GET', None)]
    for target, body in [(url, {}), (url+'?model=x', None), (url+'/other', None),
                         ('https://outside.invalid/openai/v1/models', None)]:
        with pytest.raises(InvestigationRejected, match='unsupported_endpoint'):
            groq.json_request(target, key='synthetic', body=body)
    assert len(calls) == 1


def test_bundle_submission_still_uses_the_durable_local_api(cli, monkeypatch, capsys):
    bundle, incident, key = [str(uuid4()) for _ in range(3)]
    monkeypatch.setenv('PIPEGUARD_ADMIN_TOKEN', 'synthetic_admin')
    monkeypatch.setattr(sys, 'argv', ['investigate.py', '--bundle-id', bundle,
        '--request-key', key, '--free-plan-confirmed'])
    calls = []
    def request(url, **kwargs):
        calls.append((url, kwargs))
        if kwargs.get('body') is None:
            return {'incident_id':incident}
        return {'id':str(uuid4()),'state':'completed'}
    monkeypatch.setattr(cli, 'json_request', request)
    cli.main()
    assert calls[0][0] == 'http://127.0.0.1:8000/v1/evidence-bundles/'+bundle
    assert calls[1] == ('http://127.0.0.1:8000/v1/incidents/'+incident+'/investigations',
        {'key':'synthetic_admin','body':{'request_key':key,'bundle_id':bundle,'free_plan_confirmed':True}})
    assert 'synthetic_admin' not in capsys.readouterr().out
