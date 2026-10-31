"""Synthetic subprocess checks; no warehouse or monitoring records are touched."""
import os
import fcntl
import signal
import subprocess
import sys
import time

import pytest

from orders_pipeline import runner


@pytest.mark.parametrize("termination", [signal.SIGTERM, signal.SIGINT])
def test_interruption_reaps_dbt_child_before_unwinding(tmp_path, termination):
    identity = tmp_path / "child.pid"
    child = "import os,time;from pathlib import Path;Path(" + repr(str(identity)) + ").write_text(str(os.getpid()));time.sleep(60)"
    code = (
        "import os,sys;sys.path.insert(0," + repr(str(runner.ROOT / "src")) + ");"
        "from orders_pipeline.runner import _run_dbt\n"
        "try:_run_dbt([sys.executable,'-c'," + repr(child) + "],os.environ,sys.stdout)\n"
        "except InterruptedError:sys.exit(77)\n"
    )
    process = subprocess.Popen([sys.executable, "-c", code], start_new_session=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    child_pid = None
    try:
        deadline = time.monotonic() + 5
        while not identity.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert identity.exists(), "synthetic child did not start"
        child_pid = int(identity.read_text())
        process.send_signal(termination)
        assert process.wait(timeout=10) == 77
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        if child_pid is not None:
            try:
                os.killpg(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_normal_dbt_exit_code_is_preserved():
    result = runner._run_dbt([sys.executable, "-c", "raise SystemExit(7)"], {}, subprocess.DEVNULL)
    assert result.returncode == 7


def test_timeout_stops_process_before_reraising(monkeypatch):
    calls = []
    class Process:
        pid = 123456789
        def wait(self, timeout=None):
            calls.append(("wait", timeout))
            if timeout == 120:
                raise subprocess.TimeoutExpired("synthetic", timeout)
            return -15
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(runner.os, "killpg", lambda pid, kind: calls.append(("signal", kind)))
    with pytest.raises(subprocess.TimeoutExpired):
        runner._run_dbt(["synthetic"], {}, subprocess.DEVNULL)
    assert calls == [("wait", 120), ("signal", signal.SIGTERM), ("wait", 5),
                     ("signal", signal.SIGKILL), ("wait", None)]


def test_sigkill_parent_keeps_local_exclusion_until_dbt_child_exits(tmp_path):
    lock = tmp_path / "warehouse.lock"
    identity = tmp_path / "child.pid"
    child = "import os,time;from pathlib import Path;Path(" + repr(str(identity)) + ").write_text(str(os.getpid()));time.sleep(60)"
    code = (
        "import os,sys;from pathlib import Path;sys.path.insert(0," + repr(str(runner.ROOT / "src")) + ");"
        "from orders_pipeline.runner import _run_dbt,_warehouse_guard\n"
        "with _warehouse_guard(Path(" + repr(str(lock)) + ")) as descriptor:\n"
        " _run_dbt([sys.executable,'-c'," + repr(child) + "],os.environ,sys.stdout,descriptor)\n"
    )
    process = subprocess.Popen([sys.executable, "-c", code], start_new_session=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    child_pid = None
    descriptor = None
    try:
        deadline = time.monotonic() + 5
        while not identity.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert identity.exists()
        child_pid = int(identity.read_text())
        process.kill()
        assert process.wait(timeout=5) == -signal.SIGKILL
        descriptor = os.open(lock, os.O_RDWR)
        with pytest.raises(BlockingIOError):
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.killpg(child_pid, signal.SIGKILL)
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                assert time.monotonic() < deadline
                time.sleep(0.01)
        assert lock.exists(), "persistent lock inode must never be unlinked"
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        if child_pid is not None:
            try:
                os.killpg(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
