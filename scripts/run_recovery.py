"""Manual local recovery commands; proposals never execute automatically."""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/pipeguard/src"))
from pipeguard.db.permissions import verify_runtime_access
from pipeguard.recovery import execution
from pipeguard.recovery.airflow import AirflowRecoveryClient
from pipeguard.recovery.service import RecoveryRejected


def proposal_hash(value):
    if not re.fullmatch("[0-9a-f]{64}", value):
        raise argparse.ArgumentTypeError("A lowercase SHA-256 is required")
    return value


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("propose", "inspect", "decide", "dispatch", "reconcile"):
        command = commands.add_parser(name)
        if name == "propose":
            command.add_argument("--incident", type=UUID, required=True)
        elif name == "reconcile":
            command.add_argument("--dispatch", type=UUID, required=True)
        else:
            command.add_argument("--action", type=UUID, required=True)
        if name != "inspect":
            command.add_argument("--key", type=UUID, required=True)
        if name in ("decide", "dispatch"):
            command.add_argument("--hash", type=proposal_hash, required=True)
            command.add_argument("--confirmed", action="store_true",
                help="Confirm the exact displayed proposal/hash and warehouse effect; no implicit approval")
        if name == "decide":
            command.add_argument("--decision", choices=("approve", "reject", "cancel"), required=True)
    args = parser.parse_args()
    url = make_url(os.environ["PIPEGUARD_API_DATABASE_URL"])
    if (url.drivername != "postgresql+psycopg" or url.host != "127.0.0.1" or url.database != "pipeguard"
            or url.username != "pipeguard_api"):
        raise RecoveryRejected("recovery_restricted_database_required")
    engine = create_engine(url, hide_parameters=True, pool_pre_ping=True,
        connect_args={"options": "-cstatement_timeout=5000 -clock_timeout=3000"})
    try:
        with engine.connect() as connection:
            verify_runtime_access(connection)
        if args.command == "propose":
            result = execution.propose(engine, args.incident, args.key)
        elif args.command == "inspect":
            result = execution.inspect(engine, args.action)
        elif args.command == "decide":
            result = execution.decide(engine, args.action, args.key, args.hash, args.decision, confirmed=args.confirmed)
        else:
            client = AirflowRecoveryClient(os.environ["PIPEGUARD_AIRFLOW_RECOVERY_USERNAME"],
                                          os.environ["PIPEGUARD_AIRFLOW_RECOVERY_PASSWORD"])
            if args.command == "dispatch":
                result = execution.dispatch(engine, args.action, args.key, args.hash, client, confirmed=args.confirmed)
            else:
                result = execution.reconcile(engine, args.dispatch, args.key, client)
        print(json.dumps(result, default=str, indent=2))
    finally:
        engine.dispose()


def guarded_main():
    try:
        main()
    except RecoveryRejected as error:
        raise SystemExit(str(error))
    except KeyboardInterrupt:
        raise SystemExit("Recovery command interrupted; inspect any stored intent before further action")
    except Exception:
        raise SystemExit("Recovery command failed; outcome may be uncertain; inspect stored history (private details withheld)")


def bounded_main():
    # Socket timeouts alone do not bound a response that trickles bytes forever.
    # Supervise the whole command. Termination never authorizes another POST.
    environment = dict(os.environ, _PIPEGUARD_RECOVERY_CHILD="1")
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
                               env=environment, start_new_session=True)
    try:
        return process.wait(timeout=45)
    except subprocess.TimeoutExpired:
        print("Recovery command timed out; inspect and reconcile any stored intent before further action", file=sys.stderr)
        return 124
    except KeyboardInterrupt:
        print("Recovery command interrupted; inspect any stored intent before further action", file=sys.stderr)
        return 130
    finally:
        if process.poll() is None:
            # Ignore additional signals while stopping only our owned child group.
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            try:os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:pass
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:pass
                process.wait()


if __name__ == "__main__":
    if os.environ.pop("_PIPEGUARD_RECOVERY_CHILD", None) == "1":
        guarded_main()
    else:
        def interrupt(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, interrupt)
        raise SystemExit(bounded_main())
