"""Independent local API/database/detector checks with change-only notifications."""
import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import threading
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

import psycopg
from sqlalchemy.engine import make_url

from local_files import ensure_private_directory, read_private, write_private

ROOT = Path(__file__).resolve().parents[1]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def database_parameters(value):
    url = make_url(value)
    if (url.drivername != "postgresql+psycopg" or url.host not in {"127.0.0.1", "localhost"}
            or url.database != "pipeguard" or url.username != "pipeguard_watchdog" or url.query):
        raise ValueError("Restricted local watchdog configuration required")
    return dict(host=url.host, port=url.port or 5432, dbname=url.database, user=url.username,
                password=url.password, connect_timeout=3,
                options="-cstatement_timeout=3000 -clock_timeout=1000 -cdefault_transaction_read_only=on")


def api_status():
    try:
        opener = build_opener(ProxyHandler({}), NoRedirect())
        with opener.open("http://127.0.0.1:8000/health/live", timeout=3) as response:
            if response.status != 200 or json.loads(response.read(1025)) != {"status": "alive"}:
                return "invalid_response"
        return "healthy"
    except Exception:
        return "unreachable"


def database_status(parameters):
    try:
        with psycopg.connect(**parameters) as connection:
            at, completed, unmonitored, stale = connection.execute("""
                SELECT now(), (SELECT completed_at FROM monitor_heartbeats WHERE name='detector'),
                       count(j.id) FILTER (WHERE p.job_id IS NULL),
                       count(p.job_id) FILTER (WHERE h.completed_at IS NULL
                           OR h.completed_at > now() OR h.completed_at <= now()-interval '90 seconds')
                FROM jobs j LEFT JOIN monitor_policies p ON p.job_id=j.id
                LEFT JOIN monitor_heartbeats h ON h.name='job:'||j.id::text
            """).fetchone()
        monitor = "fresh"
        if not completed or not timedelta(0) <= at-completed < timedelta(seconds=90) or stale:
            monitor = "stale"
        elif unmonitored:
            monitor = "unmonitored"
        return {"database": "healthy", "monitor": monitor}
    except Exception:
        return {"database": "unreachable", "monitor": "unknown"}


def local_notification(status):
    if sys.platform != "darwin":
        return "unavailable"
    message = ", ".join(f"{name}={value}" for name, value in sorted(status.items()))
    script = ('on run argv\n display notification (item 1 of argv) '
              'with title "PipeGuard watchdog"\nend run')
    try:
        result = subprocess.run(["/usr/bin/osascript", "-e", script, message],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
                                env={key: value for key, value in os.environ.items()
                                     if key in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR"}})
        return "submitted" if result.returncode == 0 else "failed"
    except (OSError, subprocess.TimeoutExpired):
        return "failed"


def record_check(directory, status, *, notify=False, notification=local_notification):
    ensure_private_directory(directory)
    path = directory / "state.json"
    previous = None
    if path.exists():
        try:
            previous = json.loads(read_private(path, 4096))
            if (not isinstance(previous, dict) or not isinstance(previous.get("status"), dict)
                    or previous.get("notification") not in {"none", "disabled", "unavailable", "submitted", "failed"}):
                previous = None
        except (OSError, ValueError):
            pass
    changed = previous is not None and previous["status"] != status
    unhealthy = status != {"api": "healthy", "database": "healthy", "monitor": "fresh"}
    actionable = changed or (previous is None and unhealthy)
    state = {"version": 1, "checked_at": datetime.now(timezone.utc).isoformat(), "status": status,
             "notification": previous.get("notification", "none") if previous else "none"}
    if actionable:
        state["notification"] = notification(status) if notify else "disabled"
        state["changed_at"] = state["checked_at"]
        journal = directory / "changes.jsonl"
        descriptor = os.open(journal, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        information = os.fstat(descriptor)
        if (not stat.S_ISREG(information.st_mode) or information.st_uid != os.getuid()
                or information.st_mode & 0o077 or information.st_nlink != 1):
            os.close(descriptor)
            raise ValueError("Watchdog journal must be owner-private and regular")
        if information.st_size >= 1024 * 1024:
            os.close(descriptor)
            previous_journal = directory / "changes.previous.jsonl"
            if previous_journal.is_symlink():
                raise ValueError("Watchdog journal must not be a symlink")
            os.replace(journal, previous_journal)
            descriptor = os.open(journal, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(json.dumps(state, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    elif previous and previous.get("changed_at"):
        state["changed_at"] = previous["changed_at"]
    write_private(path, json.dumps(state, sort_keys=True) + "\n")
    return actionable, state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--notify", action="store_true", help="Submit macOS notifications on state changes")
    parser.add_argument("--quiet", action="store_true", help="Write only bounded durable state/journal")
    args = parser.parse_args()
    os.umask(0o077)
    parameters = database_parameters(os.environ["PIPEGUARD_WATCHDOG_DATABASE_URL"])
    directory = ROOT / "data/local/watchdog"
    ensure_private_directory(directory)
    # A second watchdog must not duplicate notifications or race durable state.
    descriptor = os.open(directory / "watchdog.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a") as lock:
        information = os.fstat(descriptor)
        if (not stat.S_ISREG(information.st_mode) or information.st_uid != os.getuid()
                or information.st_mode & 0o077):
            raise ValueError("Watchdog lock must be owner-private and regular")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pidfile = directory / "watchdog.pid"
        write_private(pidfile, str(os.getpid()) + "\n")
        stopped = threading.Event()
        for kind in (signal.SIGINT, signal.SIGTERM):
            signal.signal(kind, lambda *args: stopped.set())
        try:
            while not stopped.is_set():
                status = {"api": api_status(), **database_status(parameters)}
                actionable, state = record_check(directory, status, notify=args.notify)
                if not args.quiet and (actionable or args.once):
                    print(json.dumps(state, sort_keys=True), flush=True)
                if args.once:
                    return 0 if status == {"api": "healthy", "database": "healthy", "monitor": "fresh"} else 1
                stopped.wait(15)
        finally:
            pidfile.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        raise SystemExit("Local watchdog failed; inspect private configuration and local state (details withheld)")
