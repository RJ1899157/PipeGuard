"""Supervised bridge never inherits API credentials or accepts a free command."""
from uuid import uuid4
import signal
import subprocess

import pytest

from pipeguard.recovery import bridge
from pipeguard.recovery.service import RecoveryRejected


@pytest.mark.parametrize('mode',['ok','rejected','invalid','timeout'])
def test_fixed_bridge_commands_output_and_cleanup(tmp_path,monkeypatch,mode):
    path=tmp_path/'.env.recovery';path.write_text('unused');path.chmod(0o600)
    monkeypatch.setattr(bridge,'ROOT',tmp_path)
    monkeypatch.setattr(bridge.shutil,'which',lambda name:'/trusted/uv')
    monkeypatch.setenv('GROQ_API_KEY','PRIVATE')
    monkeypatch.setenv('PIPEGUARD_ADMIN_TOKEN','PRIVATE')
    calls=[]
    class Process:
        pid=100000001
        returncode=1 if mode=='rejected' else 0
        alive=mode=='timeout'
        def __init__(self,args,**kwargs):
            assert args[:7]==['/trusted/uv','run','--offline','--no-sync','--env-file','.env.recovery','python']
            assert args[7:] == ['scripts/run_recovery.py','propose','--incident',str(identity),'--key',str(key)]
            assert kwargs['start_new_session'] and kwargs['cwd']==tmp_path
            assert not any('PRIVATE' in value for value in kwargs['env'].values())
        def communicate(self,timeout=None):
            calls.append(timeout)
            if mode=='timeout' and timeout==55:raise subprocess.TimeoutExpired('synthetic',55)
            self.alive=False
            return (b'[]' if mode=='invalid' else b'{"id":"synthetic"}',b'recovery_execution_disabled' if mode=='rejected' else b'')
        def poll(self):return None if self.alive else self.returncode
    identity,key=uuid4(),uuid4()
    monkeypatch.setattr(bridge.subprocess,'Popen',Process)
    monkeypatch.setattr(bridge.os,'killpg',lambda pid,kind:calls.append((pid,kind)))
    if mode=='ok':assert bridge.call('propose',incident_id=identity,request_key=key)=={'id':'synthetic'}
    elif mode=='rejected':
        with pytest.raises(RecoveryRejected,match='execution_disabled'):bridge.call('propose',incident_id=identity,request_key=key)
    else:
        with pytest.raises(bridge.WorkerUnavailable):bridge.call('propose',incident_id=identity,request_key=key)
    if mode=='timeout':assert calls==[55,(Process.pid,signal.SIGTERM),6]


def test_bridge_rejects_arbitrary_commands_arguments_and_nonprivate_file(tmp_path,monkeypatch):
    monkeypatch.setattr(bridge,'ROOT',tmp_path)
    monkeypatch.setattr(bridge.subprocess,'Popen',lambda *args,**kwargs:pytest.fail('No child should start'))
    for command,args in [('shell',{}),('propose',{'incident_id':'../escape','request_key':uuid4()}),
        ('dispatch',{'action_id':uuid4(),'request_key':uuid4(),'proposal_hash':'bad'}),('status',{})]:
        with pytest.raises(bridge.WorkerUnavailable):bridge.call(command,**args)
    path=tmp_path/'.env.recovery';path.write_text('private');path.chmod(0o644)
    with pytest.raises(bridge.WorkerUnavailable):bridge.call('status')
    path.unlink();path.symlink_to(tmp_path/'absent')
    with pytest.raises(bridge.WorkerUnavailable):bridge.call('status')
