"""Private configuration writes use only synthetic temporary files."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("local_files", Path(__file__).resolve().parents[3] / "scripts/local_files.py")
local_files = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local_files)


def test_private_write_is_atomic_owner_only_and_does_not_reuse_orphans(tmp_path):
    path = tmp_path / ".env"
    orphan = tmp_path / ".env.api-tmp"
    orphan.write_text("interrupted synthetic write")
    local_files.write_private(path, "first", exclusive=True)
    assert path.stat().st_mode & 0o777 == 0o600
    local_files.write_private(path, "second")
    assert path.read_text() == "second"
    assert orphan.read_text() == "interrupted synthetic write"
    assert sorted(p.name for p in tmp_path.iterdir()) == [".env", ".env.api-tmp"]


def test_exclusive_write_preserves_existing_configuration(tmp_path):
    path = tmp_path / ".env"
    path.write_text("existing")
    with pytest.raises(FileExistsError):
        local_files.write_private(path, "replacement", exclusive=True)
    assert path.read_text() == "existing"
    assert list(tmp_path.iterdir()) == [path]


def test_failed_file_sync_preserves_previous_configuration(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("existing")
    def unavailable(descriptor):
        raise OSError("synthetic sync failure")
    monkeypatch.setattr(local_files.os, "fsync", unavailable)
    with pytest.raises(OSError):
        local_files.write_private(path, "replacement")
    assert path.read_text() == "existing"
    assert list(tmp_path.iterdir()) == [path]


def test_private_write_rejects_symlink(tmp_path):
    target = tmp_path / "target"
    target.write_text("existing")
    link = tmp_path / ".env"
    link.symlink_to(target)
    with pytest.raises(ValueError):
        local_files.write_private(link, "replacement")
    assert target.read_text() == "existing"


def test_airflow_accounts_are_preseeded_privately_without_rotating_existing_users(tmp_path, monkeypatch):
    import json
    root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    spec = importlib.util.spec_from_file_location("configure_airflow", root / "scripts/configure_airflow.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    path = tmp_path / "users.json"
    script.provision_users(path)
    original = json.loads(local_files.read_private(path, 65536))
    assert set(original) == {"RJ1899157", "pipeguard_observer", "pipeguard_recovery"}
    assert len(set(original.values())) == 3
    script.provision_users(path)
    assert json.loads(path.read_text()) == original
    # Older installations may have only one account; preserve its credential.
    local_files.write_private(path, json.dumps({"pipeguard_observer": original["pipeguard_observer"]}))
    script.provision_users(path)
    assert json.loads(path.read_text())["pipeguard_observer"] == original["pipeguard_observer"]
    path.chmod(0o644)
    with pytest.raises(ValueError):
        script.provision_users(path)
    path.chmod(0o600)
    path.write_text('[]')
    with pytest.raises(ValueError):
        script.provision_users(path)
    path.unlink()
    path.symlink_to(tmp_path / "missing")
    with pytest.raises(ValueError):
        script.provision_users(path)


def test_recovery_configuration_is_scoped_private_and_resets_execution(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from uuid import uuid4
    root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(root / 'scripts'))
    spec = importlib.util.spec_from_file_location('configure_recovery', root / 'scripts/configure_recovery.py')
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    script.__file__ = str(tmp_path / 'scripts/configure_recovery.py')
    job_id = str(uuid4())
    monkeypatch.setenv('PIPEGUARD_RECOVERY_JOB_ID', job_id)
    monkeypatch.setenv('PIPEGUARD_API_DATABASE_URL', 'postgresql+psycopg://pipeguard_api:synthetic@127.0.0.1:55432/pipeguard')
    monkeypatch.setenv('GROQ_API_KEY', 'PRIVATE_MUST_NOT_COPY')
    users = tmp_path/'data/local/airflow/users.json'
    users.parent.mkdir(parents=True)
    local_files.write_private(users, json.dumps({'pipeguard_recovery':'scoped_password', 'RJ1899157':'PRIVATE_MUST_NOT_COPY'}))
    class Connection:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    class Engine:
        def connect(self):return Connection()
        def dispose(self):pass
    class Session(Connection):
        def __init__(self,*args):pass
        def scalar(self,*args):return SimpleNamespace(airflow_dag_id='pipeguard_orders', airflow_task_id='build_orders')
    monkeypatch.setattr(script,'create_engine',lambda *args,**kwargs:Engine())
    monkeypatch.setattr(script,'verify_runtime_access',lambda connection:None)
    monkeypatch.setattr(script,'Session',Session)
    destination = tmp_path/'.env.recovery'
    local_files.write_private(destination, 'PIPEGUARD_RECOVERY_EXECUTION_ENABLED=1\n')
    script.main()
    result = local_files.read_private(destination, 65536).decode()
    assert 'PRIVATE_MUST_NOT_COPY' not in result
    assert 'PIPEGUARD_RECOVERY_EXECUTION_ENABLED=0\n' in result
    assert 'PIPEGUARD_AIRFLOW_RECOVERY_USERNAME=pipeguard_recovery\n' in result
    assert len(result.splitlines())==5
    monkeypatch.setenv('PIPEGUARD_API_DATABASE_URL', 'postgresql+psycopg://pipeguard_owner:synthetic@127.0.0.1:55432/pipeguard')
    with pytest.raises(ValueError,match='Restricted local recovery database'):
        script.main()


def test_recovery_command_deadline_terminates_only_its_owned_child_group(monkeypatch):
    import subprocess
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location('run_recovery', root/'scripts/run_recovery.py')
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    calls=[]
    class Process:
        pid=100000001
        def __init__(self,*args,**kwargs):
            assert kwargs['start_new_session']
            assert kwargs['env']['_PIPEGUARD_RECOVERY_CHILD']=='1'
        def wait(self,timeout=None):
            calls.append(('wait',timeout))
            if timeout is not None:raise subprocess.TimeoutExpired('synthetic',timeout)
            return 0
        def poll(self):return None
    monkeypatch.setattr(script.subprocess,'Popen',Process)
    monkeypatch.setattr(script.os,'killpg',lambda pid,kind:calls.append(('signal',pid,kind)))
    monkeypatch.setattr(script.signal,'signal',lambda *args:None)
    assert script.bounded_main()==124
    assert calls==[('wait',45),('signal',Process.pid,script.signal.SIGTERM),('wait',5),
                   ('signal',Process.pid,script.signal.SIGKILL),('wait',None)]


def test_recovery_supervisor_import_does_not_load_application_modules():
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[3]
    check = ('import runpy, sys; runpy.run_path("scripts/run_recovery.py", run_name="supervisor_check"); '
             'assert "sqlalchemy" not in sys.modules; '
             'assert not any(name.startswith("pipeguard.") for name in sys.modules)')
    subprocess.run([sys.executable, '-c', check], cwd=root, check=True, capture_output=True, timeout=5)


def test_airflow_launcher_cleans_groups_after_leader_exits(tmp_path, monkeypatch):
    launcher_spec = importlib.util.spec_from_file_location("run_airflow", Path(__file__).resolve().parents[3] / "scripts/run_airflow.py")
    launcher = importlib.util.module_from_spec(launcher_spec)
    launcher_spec.loader.exec_module(launcher)
    monkeypatch.setenv("AIRFLOW_HOME", str(tmp_path))
    monkeypatch.setenv("PYTHONPATH", "/untrusted/inherited/path")
    monkeypatch.setattr("sys.argv", ["run_airflow.py", "start"])
    monkeypatch.setattr(launcher.signal, "signal", lambda *args: None)
    calls = []
    processes = []
    class Process:
        def __init__(self, *args, **kwargs):
            assert kwargs["start_new_session"]
            assert launcher.os.environ["PYTHONPATH"] == str(launcher.ROOT / "infra/airflow/auth")
            self.pid = 100000000 + len(processes)
            processes.append(self)
        def poll(self):
            return 0  # Leaders can exit while descendants retain the group.
        def wait(self, timeout=None):
            return 0
    monkeypatch.setattr(launcher.subprocess, "Popen", Process)
    monkeypatch.setattr(launcher.os, "killpg", lambda pid, kind: calls.append((pid, kind)))
    assert launcher.main() == 1
    assert calls == ([(p.pid, launcher.signal.SIGTERM) for p in processes]
                     + [(p.pid, launcher.signal.SIGKILL) for p in processes])


def test_airflow_task_filters_credentials_and_cleans_timeout(tmp_path, monkeypatch):
    import ast
    import hashlib
    import json
    import signal
    import subprocess
    from types import SimpleNamespace
    source = Path(__file__).resolve().parents[3] / "infra/airflow/dags/orders.py"
    function = next(node for node in ast.parse(source.read_text()).body
                    if isinstance(node, ast.FunctionDef) and node.name == "build_orders")
    function.decorator_list = []
    config = tmp_path / "sample-pipelines/orders/.env"
    config.parent.mkdir(parents=True)
    config.write_text("PIPEGUARD_INTEGRATION_ID=synthetic\nPIPEGUARD_JOB_ID=synthetic\n"
                      "PIPEGUARD_PRODUCER_TOKEN=synthetic\nORDERS_DATABASE=sample_warehouse\n")
    calls = []
    class Process:
        pid = 123456789
        def __init__(self, command, **kwargs):
            assert kwargs["start_new_session"]
            assert "AIRFLOW_LOCAL_DB_PASSWORD" not in kwargs["env"]
            assert "POSTGRES_PASSWORD" not in kwargs["env"]
        def communicate(self, timeout):
            assert timeout == 180
            raise subprocess.TimeoutExpired("synthetic", timeout)
        def wait(self, timeout=None):
            calls.append(("wait", timeout))
            return -15
    context = {"dag": SimpleNamespace(dag_id="synthetic"), "run_id": "synthetic",
               "task": SimpleNamespace(task_id="synthetic"), "ti": SimpleNamespace(try_number=1),
               "params": {"simulate_first_attempt_failure": False, "simulate_terminal_failure": False}}
    namespace = {"ROOT": tmp_path, "get_current_context": lambda: context,
                 "sha256": hashlib.sha256, "json": json, "signal": signal,
                 "os": SimpleNamespace(environ={"AIRFLOW_LOCAL_DB_PASSWORD": "synthetic", "POSTGRES_PASSWORD": "synthetic"},
                                       killpg=lambda pid, kind: calls.append(("signal", kind))),
                 "subprocess": SimpleNamespace(Popen=Process, PIPE=subprocess.PIPE,
                                               TimeoutExpired=subprocess.TimeoutExpired)}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
    with pytest.raises(subprocess.TimeoutExpired):
        namespace["build_orders"]()
    assert calls == [("signal", signal.SIGTERM), ("wait", 10),
                     ("signal", signal.SIGKILL), ("wait", None)]


def test_monitoring_setup_finds_matching_policy_after_first_page(tmp_path, monkeypatch):
    import io
    import json
    from urllib.error import HTTPError
    root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    script_spec = importlib.util.spec_from_file_location("configure_monitoring", root / "scripts/configure_monitoring.py")
    script = importlib.util.module_from_spec(script_spec)
    script_spec.loader.exec_module(script)
    script.__file__ = str(tmp_path / "scripts/configure_monitoring.py")
    users = tmp_path / "data/local/airflow/users.json"
    users.parent.mkdir(parents=True)
    users.write_text(json.dumps({"pipeguard_observer": "synthetic"}))
    config = tmp_path / "sample-pipelines/orders/.env"
    config.parent.mkdir(parents=True)
    config.write_text("PIPEGUARD_JOB_ID=synthetic\n")
    monkeypatch.setenv("PIPEGUARD_API_DATABASE_URL", "synthetic")
    monkeypatch.setenv("PIPEGUARD_ADMIN_TOKEN", "synthetic")
    requests = []
    class Opener:
        def open(self, request, timeout):
            requests.append(request.full_url)
            if request.get_method() == "POST":
                raise HTTPError(request.full_url, 409, "synthetic", None, None)
            if "offset=100" in request.full_url:
                body = [{"job_id": "synthetic", "timeout_seconds": 300, "quality_required": True,
                         "airflow_dag_id": "pipeguard_orders", "airflow_task_id": "build_orders"}]
            else:
                body = [{"job_id": "other"}] * 100
            return io.BytesIO(json.dumps(body).encode())
    monkeypatch.setattr(script, "build_opener", lambda *args: Opener())
    script.main()
    assert requests[-1].endswith("offset=100")
