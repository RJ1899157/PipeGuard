"""Fresh-export HTTP acceptance: real orders/dbt retry, no scheduler, AI or recovery start."""
import json
from http.client import HTTPResponse
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from uuid import UUID

import httpx
from sqlalchemy import create_engine, func, select

from check_delivery import stop

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/pipeguard/src"))
from pipeguard.db.config import database_url
from pipeguard.db.models import Integration
from pipeguard.detection.service import evaluate_job

# Transport fixture only: retain the producer's port-8000 validation while sending
# its three fixed POST paths to the separately owned, ephemeral acceptance API.
WORKLOAD_CHECK = '''
import os, sys
sys.path.insert(0, "src")
from urllib.request import Request
import orders_pipeline.observer as observer
original = observer.build_opener
class IsolatedTransport:
    def __init__(self, *handlers):
        self.opener = original(*handlers)
    def open(self, request, **options):
        prefix = "http://127.0.0.1:8000"
        if request.full_url not in {prefix + path for path in
            ("/v1/events", "/v1/quality-reports", "/v1/lineage-events")}:
            raise ValueError("Unexpected producer destination")
        redirected = Request(os.environ["DELIVERY_API_URL"] + request.full_url[len(prefix):],
            data=request.data, headers=dict(request.header_items()), method=request.get_method())
        return self.opener.open(redirected, **options)
observer.build_opener = IsolatedTransport
from orders_pipeline.runner import main
raise SystemExit(main())
'''


def require(condition, description):
    if not condition:
        raise RuntimeError(description)


def main():
    def interrupted(signum, frame):
        raise KeyboardInterrupt

    marker = json.loads((ROOT / ".delivery-check.json").read_text())
    url = database_url()
    require(marker["project"].startswith("pipeguard-check-") and url.host == "127.0.0.1"
            and url.port == marker["port"] and url.port != 55432,
            "Requires the isolated delivery-check database")
    require(not os.environ.get("GROQ_API_KEY") and os.environ.get("PIPEGUARD_RECOVERY_EXECUTION_ENABLED", "0") == "0"
            and os.environ.get("PIPEGUARD_AIRFLOW_RECOVERY_ENABLED", "0") == "0", "Provider and recovery must be disabled")
    engine = create_engine(url, hide_parameters=True)
    with engine.connect() as connection:
        require(connection.scalar(select(func.count()).select_from(Integration)) == 0, "Requires an empty monitoring catalog")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "apps/pipeguard/src")
    process = None
    previous = signal.signal(signal.SIGTERM, interrupted)
    try:
        with (ROOT / "data/local/delivery-api.log").open("wb") as log:
            process = subprocess.Popen([sys.executable, "-m", "uvicorn", "pipeguard.api.app:create_app", "--factory",
                "--host", "127.0.0.1", "--port", str(port), "--no-access-log", "--no-proxy-headers"],
                cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            with httpx.Client(base_url=base, headers={"Authorization": "Bearer " + os.environ["PIPEGUARD_ADMIN_TOKEN"]},
                              trust_env=False, timeout=10) as client:
                deadline = time.monotonic() + 30
                while True:
                    require(process.poll() is None, "Isolated API stopped before readiness")
                    try:
                        if client.get("/health/ready").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    require(time.monotonic() < deadline, "Isolated API readiness deadline exceeded")
                    time.sleep(0.2)

                def request(method, path, *, expected=200, **arguments):
                    response = client.request(method, path, **arguments)
                    require(response.status_code == expected, "Unexpected response at " + path)
                    return response.json()

                require(httpx.get(base + "/v1/jobs", trust_env=False).status_code == 401, "Metadata must require authentication")
                for length, expected in ((65537, 413), (1, 408)):
                    with socket.create_connection(("127.0.0.1", port), timeout=20) as connection:
                        connection.sendall(("POST /v1/events HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                            f"Content-Length: {length}\r\nConnection: close\r\n\r\n").encode())
                        response = HTTPResponse(connection)
                        response.begin()
                        require(response.status == expected, "Body admission must reject oversize/stalled HTTP requests")
                        require(response.getheader("Cache-Control") == "no-store", "Admission errors must not be cached")
                        response.read()
                integration = request("POST", "/v1/integrations", expected=201,
                    json={"name": "delivery-orders", "environment": "test", "kind": "synthetic"})
                job = request("POST", "/v1/jobs", expected=201,
                    json={"integration_id": integration["id"], "namespace": "delivery", "name": "orders", "kind": "job"})
                credential = request("POST", f"/v1/integrations/{integration['id']}/credentials", expected=201)
                request("POST", "/v1/monitor-policies", expected=201, json={"job_id": job["id"], "quality_required": True})
                workload = ROOT / "sample-pipelines/orders"
                configuration = workload / ".env"
                with configuration.open("a") as stream:
                    for key, value in {"PIPEGUARD_INTEGRATION_ID": integration["id"], "PIPEGUARD_JOB_ID": job["id"],
                                       "PIPEGUARD_PRODUCER_TOKEN": credential["token"], "PIPEGUARD_BASE_URL": "http://127.0.0.1:8000"}.items():
                        stream.write(f"{key}={value}\n")

                def attempt(number, *, fail=False):
                    command = ["uv", "run", "--locked", "--env-file", ".env", "python", "-c", WORKLOAD_CHECK,
                               "--run-id", "delivery-retry", "--attempt", str(number)]
                    if fail:
                        command.append("--simulate-first-attempt-failure")
                    # Only workload configuration is loaded; monitoring-owner credentials stay out.
                    child_env = {key: value for key, value in os.environ.items()
                                 if key in {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL"}}
                    child_env["DELIVERY_API_URL"] = base
                    with (ROOT / f"data/local/delivery-attempt-{number}.log").open("wb") as attempt_log:
                        child = subprocess.Popen(command, cwd=workload, env=child_env, stdout=attempt_log,
                                                 stderr=subprocess.STDOUT, start_new_session=True)
                        try:
                            code = child.wait(timeout=150)
                        finally:
                            stop(child)
                    require(code == (1 if fail else 0), "Unexpected workload outcome")
                    evaluate_job(engine, UUID(job["id"]))

                attempt(1, fail=True)
                incident = next(row for row in request("GET", "/v1/incidents") if row["condition"] == "execution_failure")
                require(incident["state"] == "open", "Failed attempt must open an incident")
                evidence = request("POST", f"/v1/incidents/{incident['id']}/evidence-bundles", expected=201)
                frozen = request("GET", f"/v1/evidence-bundles/{evidence['id']}")
                history_before = request("GET", f"/v1/incidents/{incident['id']}/history")
                attempt(2)
                runs = request("GET", "/v1/runs")["items"]
                require(len(runs) == 1 and runs[0]["state"] == "succeeded", "Retry must succeed on the original run")
                attempts = request("GET", f"/v1/runs/{runs[0]['id']}/attempts")["items"]
                require([a["state"] for a in attempts] == ["failed", "succeeded"]
                        and attempts[0]["error_code"] == "source_unavailable", "Failure history must survive retry")
                require(request("GET", f"/v1/incidents/{incident['id']}")["state"] == "resolved", "Retry must resolve the execution incident")
                history_after = request("GET", f"/v1/incidents/{incident['id']}/history")
                require(all(row in history_after for row in history_before)
                        and "resolved" in {row["action"] for row in history_after}, "Incident lifecycle must remain retained")
                require(request("GET", f"/v1/evidence-bundles/{evidence['id']}") == frozen, "Captured evidence must remain immutable")
                reports = request("GET", f"/v1/jobs/{job['id']}/quality-reports", params={"external_run_id": "delivery-retry", "attempt_number": 2})
                checks = reports["items"][0]["payload"]["checks"]
                require(len(checks) == 14 and all(c["status"] == "pass" for c in checks), "Expected 14 passing quality checks")
                graph = request("GET", f"/v1/jobs/{job['id']}/lineage", params={"external_run_id": "delivery-retry", "attempt_number": 2})
                require(graph["coverage"] == "reported_complete" and graph["nodes"] and graph["edges"], "Successful attempt must report lineage")
                # Fail only this isolated cluster's API account; preserve its data.
                administrator = create_engine(url.set(username="postgres", password=os.environ["POSTGRES_PASSWORD"]), hide_parameters=True)
                try:
                    with administrator.begin() as connection:
                        connection.exec_driver_sql("ALTER ROLE pipeguard_api NOLOGIN")
                        connection.exec_driver_sql("SELECT pg_terminate_backend(pid, 1000) FROM pg_stat_activity WHERE usename='pipeguard_api'")
                    try:
                        require(request("GET", "/health/live") == {"status": "alive"}, "Database access loss must not imply process death")
                        require(request("GET", "/health/ready", expected=503) == {"error": "database_unavailable"}, "Readiness must fail closed")
                    finally:
                        with administrator.begin() as connection:
                            connection.exec_driver_sql("ALTER ROLE pipeguard_api LOGIN")
                    require(request("GET", "/health/ready") == {"status": "ready"}, "Readiness must recover after runtime access restoration")
                    require(request("GET", f"/v1/evidence-bundles/{evidence['id']}") == frozen, "Evidence must survive runtime access outage")
                finally:
                    administrator.dispose()
                print(json.dumps({"passed": True, "attempt_states": [a["state"] for a in attempts],
                    "incident_state": "resolved", "quality_checks": len(checks), "lineage_coverage": graph["coverage"],
                    "captured_evidence_unchanged": True, "body_admission_statuses": [413, 408],
                    "runtime_database_access_outage": {"live": 200, "ready": 503, "restored_ready": 200},
                    "hosted_ai_calls": 0, "recovery_dispatches": 0}))
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        if process is not None:
            stop(process)
        engine.dispose()
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    main()
