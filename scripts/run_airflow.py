"""Run the constrained Airflow CLI or three local components with private logs."""
import argparse
import os
from pathlib import Path
import signal
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]


def main():
    os.umask(0o077)
    if not os.environ.get("AIRFLOW_HOME"):
        raise SystemExit("Load .env.airflow before invoking the orchestrator")
    binary=ROOT/"infra/airflow/.venv/bin/airflow"
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=["init","start","cli"])
    parser.add_argument("arguments",nargs=argparse.REMAINDER)
    args=parser.parse_args()
    if args.command!="start":
        command=[str(binary)]+(["db","migrate"] if args.command=="init" else args.arguments)
        return subprocess.call(command)
    home=Path(os.environ["AIRFLOW_HOME"])
    logs=home/"component-logs"
    logs.mkdir(exist_ok=True,mode=0o700)
    processes=[]
    streams=[]
    def stop(signum,frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop)
    try:
        for name,command in [
            ("api",["api-server","--host","127.0.0.1","--port","8080","--workers","1"]),
            ("scheduler",["scheduler","--skip-serve-logs"]),
            ("processor",["dag-processor"]),
        ]:
            stream=(logs/(name+".log")).open("a")
            streams.append(stream)
            processes.append(subprocess.Popen([str(binary)]+command,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True))
        print("Local Airflow components started; API/UI at http://127.0.0.1:8080",flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(1)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        signal.signal(signal.SIGINT,signal.SIG_IGN)
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        for process in processes:
            try:
                os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError:
                pass
        for process in processes:
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                pass
            # A component leader may exit before its descendants. The group is
            # still ours, and must not survive the launcher shutdown.
            try:
                os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        for stream in streams:
            stream.close()


if __name__=="__main__":
    raise SystemExit(main())
