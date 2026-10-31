"""Explicitly enroll an existing job; never invent its schedule or quality expectations."""
import argparse
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/pipeguard/src"))
from pipeguard.detection.airflow import NoRedirect
from pipeguard.detection.contracts import PolicyCreate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--expected-interval-seconds", type=int)
    parser.add_argument("--quality-required", action="store_true")
    parser.add_argument("--airflow-dag-id")
    parser.add_argument("--airflow-task-id")
    args = parser.parse_args()
    body = PolicyCreate(**vars(args)).model_dump(mode="json")
    headers = {"Authorization": "Bearer " + os.environ["PIPEGUARD_ADMIN_TOKEN"],
               "Content-Type": "application/json"}
    opener = build_opener(ProxyHandler({}), NoRedirect())
    request = Request("http://127.0.0.1:8000/v1/monitor-policies", headers=headers,
                      data=json.dumps(body).encode())
    try:
        with opener.open(request, timeout=5) as response:
            assert response.status == 201
    except HTTPError as error:
        if error.code != 409:
            raise RuntimeError("enrollment_failed") from None
        offset = 0
        while True:
            request = Request(f"http://127.0.0.1:8000/v1/monitor-policies?limit=100&offset={offset}", headers=headers)
            with opener.open(request, timeout=5) as response:
                policies = json.load(response)
            if any(all(row.get(k) == value for k, value in body.items()) for row in policies):
                break
            if len(policies) < 100 or offset >= 100000:
                raise RuntimeError("existing_policy_differs")
            offset += 100
    print("Explicit monitoring policy enrolled or matching policy verified")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Enrollment failed (private details withheld)")
