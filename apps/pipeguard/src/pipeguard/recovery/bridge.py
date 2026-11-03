"""Fixed commands to the separately configured worker; no credentials in API memory."""
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
from uuid import UUID

from pipeguard.recovery.service import RecoveryRejected

ROOT = Path(__file__).resolve().parents[5]


class WorkerUnavailable(RuntimeError):
    pass


def call(command, *, incident_id=None, action_id=None, dispatch_id=None, request_key=None,
         proposal_hash=None, decision=None):
    arguments = [command]
    fields = {
        "status": {}, "propose": {"incident": incident_id, "key": request_key},
        "decide": {"action": action_id, "key": request_key, "hash": proposal_hash, "decision": decision},
        "dispatch": {"action": action_id, "key": request_key, "hash": proposal_hash},
        "reconcile": {"dispatch": dispatch_id, "key": request_key},
    }
    if command not in fields:
        raise WorkerUnavailable("recovery_worker_unknown")
    for key, value in fields[command].items():
        if key == "hash":
            valid = isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value)
        elif key == "decision":
            valid = value in {"approve", "reject", "cancel"}
        else:
            valid = isinstance(value, UUID)
        if not valid:
            raise WorkerUnavailable("recovery_worker_unknown")
        arguments.extend(["--" + key, str(value)])
    if command in {"decide", "dispatch"}:
        arguments.append("--confirmed")
    try:
        info = (ROOT / ".env.recovery").lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise WorkerUnavailable("recovery_worker_unknown")
        binary = shutil.which("uv")
        if not binary:
            raise WorkerUnavailable("recovery_worker_unknown")
        environment = {key: value for key, value in os.environ.items()
                       if key in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR"}}
        process = subprocess.Popen([binary, "run", "--offline", "--no-sync", "--env-file", ".env.recovery",
            "python", "scripts/run_recovery.py", *arguments], cwd=ROOT, env=environment,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    except (OSError, ValueError):
        raise WorkerUnavailable("recovery_worker_unknown") from None
    try:
        stdout, stderr = process.communicate(timeout=55)
        if len(stdout) > 1024 * 1024 or len(stderr) > 65536:
            raise WorkerUnavailable("recovery_worker_unknown")
        if process.returncode:
            code = stderr.decode("utf-8").strip()
            if re.fullmatch(r"recovery_[a-z_]{1,65}", code):
                raise RecoveryRejected(code)
            raise WorkerUnavailable("recovery_worker_unknown")
        result = json.loads(stdout)
        if not isinstance(result, dict):
            raise WorkerUnavailable("recovery_worker_unknown")
        return result
    except RecoveryRejected:
        raise
    except (subprocess.TimeoutExpired, OSError, ValueError, RecursionError):
        raise WorkerUnavailable("recovery_worker_unknown") from None
    finally:
        if process.poll() is None:
            try:os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:pass
            try:process.communicate(timeout=6)
            except subprocess.TimeoutExpired:
                try:os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:pass
                process.communicate()
