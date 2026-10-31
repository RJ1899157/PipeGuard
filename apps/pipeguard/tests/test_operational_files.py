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


def test_airflow_launcher_cleans_groups_after_leader_exits(tmp_path, monkeypatch):
    launcher_spec = importlib.util.spec_from_file_location("run_airflow", Path(__file__).resolve().parents[3] / "scripts/run_airflow.py")
    launcher = importlib.util.module_from_spec(launcher_spec)
    launcher_spec.loader.exec_module(launcher)
    monkeypatch.setenv("AIRFLOW_HOME", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["run_airflow.py", "start"])
    monkeypatch.setattr(launcher.signal, "signal", lambda *args: None)
    calls = []
    processes = []
    class Process:
        def __init__(self, *args, **kwargs):
            assert kwargs["start_new_session"]
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
               "params": {"simulate_first_attempt_failure": False}}
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
