"""Create a private worker configuration and an explicit watch for the example job."""
import json
import os
from pathlib import Path
import sys
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/pipeguard/src"))
from pipeguard.detection.airflow import NoRedirect


def main():
    root = Path(__file__).resolve().parents[1]
    users = json.loads((root / "data/local/airflow/users.json").read_text())
    sample = dict(line.split("=", 1) for line in (root / "sample-pipelines/orders/.env").read_text().splitlines()
                  if line and not line.startswith("#"))
    values = {"PIPEGUARD_API_DATABASE_URL": os.environ["PIPEGUARD_API_DATABASE_URL"],
              "PIPEGUARD_AIRFLOW_USERNAME": "pipeguard_observer",
              "PIPEGUARD_AIRFLOW_PASSWORD": users["pipeguard_observer"]}
    target = root / ".env.monitoring"
    if target.is_symlink():
        raise RuntimeError("Regular private configuration required")
    temporary = target.with_name(".env.monitoring-tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write("".join(f"{key}={value}\n" for key, value in values.items()))
    temporary.replace(target)
    # Schedule expectation deliberately omitted while the example DAG is paused.
    body = {"job_id": sample["PIPEGUARD_JOB_ID"], "timeout_seconds": 300,
            "quality_required": True, "airflow_dag_id": "pipeguard_orders", "airflow_task_id": "build_orders"}
    request = Request("http://127.0.0.1:8000/v1/monitor-policies", data=json.dumps(body).encode(),
                      headers={"Authorization": "Bearer " + os.environ["PIPEGUARD_ADMIN_TOKEN"],
                               "Content-Type": "application/json"})
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=5) as response:
            if response.status != 201:
                raise RuntimeError("Policy provisioning failed")
    except HTTPError as exc:
        if exc.code != 409:
            raise RuntimeError("Policy provisioning failed") from None
        # Do not interpret an unrelated conflict as a matching watch.
        request = Request("http://127.0.0.1:8000/v1/monitor-policies?limit=100",
                          headers={"Authorization": "Bearer " + os.environ["PIPEGUARD_ADMIN_TOKEN"]})
        with opener.open(request, timeout=5) as response:
            policies = json.load(response)
        if not any(all(p.get(k) == v for k, v in body.items()) for p in policies):
            raise RuntimeError("Existing policy differs; review it before changing monitoring") from None
    print("Private observer configuration and explicit job watch prepared")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Monitoring configuration failed (private details withheld)")
