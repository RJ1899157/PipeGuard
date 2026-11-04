"""Fixed local recovery transport. No mutation retry, redirect, proxy or raw output."""
import json
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener

from pipeguard.detection.airflow import NoRedirect
from pipeguard.recovery.service import DAG, RecoveryRejected

USER = "pipeguard_recovery"
TASK = "build_orders"
POLICY = "recovery_execute_v1"


def parameters(action_id):
    return {"dag_id": DAG, "body": {"dag_run_id": "pipeguard-execution-" + action_id.hex,
        "logical_date": None, "conf": {"pipeguard_recovery": {"action_id": str(action_id), "policy": POLICY}}}}


class TransportFailure(RuntimeError):
    pass


class AirflowRecoveryClient:
    def __init__(self, username, password):
        if username != USER or not isinstance(password, str) or not password:
            raise RecoveryRejected("recovery_dedicated_identity_required")
        self._password = password
        self._token = None
        self._opener = build_opener(ProxyHandler({}), NoRedirect())

    def _request(self, method, path, body=None):
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = "Bearer " + self._token
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request("http://127.0.0.1:8080" + path, method=method, headers=headers,
                          data=None if body is None else json.dumps(body).encode())
        try:
            with self._opener.open(request, timeout=5) as response:
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise TransportFailure("recovery_source_response_too_large")
                return response.status, json.loads(raw)
        except HTTPError as error:
            code = error.code
            error.close()
            return code, None  # Never retain error bodies, URLs, headers or credentials.
        except (URLError, HTTPException, TimeoutError, OSError):
            raise TransportFailure("recovery_source_unreachable") from None
        except (ValueError, TypeError, RecursionError):
            raise TransportFailure("recovery_source_invalid_response") from None

    def _authenticate(self):
        status, result = self._request("POST", "/auth/token", {"username": USER, "password": self._password})
        if (status not in (200, 201) or not isinstance(result, dict)
                or not isinstance(result.get("access_token"), str) or not result["access_token"]
                or len(result["access_token"]) > 16384):
            raise TransportFailure("recovery_source_authentication_failed")
        self._token = result["access_token"]

    def _get(self, path):
        if self._token is None:
            self._authenticate()
        status, result = self._request("GET", path)
        if status == 401:
            self._authenticate()
            status, result = self._request("GET", path)
        return status, result

    def preflight(self, failed_source_run):
        try:
            status, health = self._get("/api/v2/monitor/health")
            if status != 200 or any(health[name]["status"] != "healthy" for name in ("metadatabase", "scheduler", "dag_processor")):
                raise RecoveryRejected("recovery_source_unhealthy")
            path = "/api/v2/dags/" + DAG
            status, dag = self._get(path)
            if (status != 200 or dag["dag_id"] != DAG or dag["is_paused"] is not False
                    or dag["has_import_errors"] is not False):
                raise RecoveryRejected("recovery_source_dag_unavailable")
            status, page = self._get(path + "/dagRuns?limit=100&order_by=id")
            if (status != 200 or not isinstance(page["dag_runs"], list)
                    or type(page["total_entries"]) is not int or not 1 <= page["total_entries"] <= 100
                    or len(page["dag_runs"]) != page["total_entries"]):
                raise RecoveryRejected("recovery_source_inventory_incomplete")
            runs = page["dag_runs"]
            if len({run["dag_run_id"] for run in runs}) != len(runs):
                raise RecoveryRejected("recovery_source_inventory_incomplete")
            if any(run["dag_id"] != DAG or run["state"] not in {"success", "failed"} for run in runs):
                raise RecoveryRejected("recovery_source_run_unsettled")
            if not any(run["dag_run_id"] == failed_source_run and run["state"] == "failed" for run in runs):
                raise RecoveryRejected("recovery_source_failure_changed")
        except RecoveryRejected:
            raise
        except TransportFailure as error:
            raise RecoveryRejected(str(error)) from None
        except (KeyError, TypeError, ValueError):
            raise RecoveryRejected("recovery_source_invalid_response") from None

    @staticmethod
    def _fact(action_id, result):
        expected = parameters(action_id)
        if (not isinstance(result, dict)
                or not {"dag_id", "dag_run_id", "conf", "logical_date", "run_type", "triggered_by", "triggering_user_name", "state"} <= result.keys()
                or result.get("dag_id") != DAG
                or result.get("dag_run_id") != expected["body"]["dag_run_id"]
                or result.get("conf") != expected["body"]["conf"]
                or result.get("logical_date") is not None or result.get("run_type") != "manual"
                or result.get("triggered_by") != "rest_api" or result.get("triggering_user_name") != USER):
            return {"state": "conflict", "code": "recovery_external_identity_conflict", "facts": {}}
        state = {"queued": "queued", "running": "running", "success": "succeeded", "failed": "failed"}.get(
            result["state"] if isinstance(result["state"], str) else None)
        if state is None:
            return {"state": "unknown", "code": "recovery_external_state_unknown", "facts": {}}
        # Explicit allowlist: raw conf, notes, arbitrary strings and provider output
        # never enter the operational ledger or command output.
        return {"state": state, "code": "recovery_external_run_observed",
                "facts": {"dag_id": DAG, "dag_run_id": expected["body"]["dag_run_id"], "state": state}}

    def submit(self, action_id):
        # Authentication/preflight must finish before durable intent is committed.
        # Never authenticate, refresh or retry around this business POST.
        if self._token is None:
            return {"state": "rejected", "code": "recovery_source_not_authenticated", "facts": {}}
        try:
            status, result = self._request("POST", "/api/v2/dags/" + DAG + "/dagRuns", parameters(action_id)["body"])
            if status in (200, 201):
                return self._fact(action_id, result)
            if status in (400, 401, 403, 404, 422):
                return {"state": "rejected", "code": "recovery_source_rejected", "facts": {"http_status": status}}
            return {"state": "unknown", "code": "recovery_source_response_uncertain", "facts": {"http_status": status}}
        except TransportFailure as error:
            return {"state": "unknown", "code": str(error), "facts": {}}

    def lookup(self, action_id):
        try:
            identity = parameters(action_id)["body"]["dag_run_id"]
            status, result = self._get("/api/v2/dags/" + DAG + "/dagRuns/" + quote(identity, safe=""))
            if status == 200:
                return self._fact(action_id, result)
            return {"state": "unknown", "code": "recovery_external_not_found" if status == 404 else "recovery_source_response_uncertain",
                    "facts": {"http_status": status}}
        except TransportFailure as error:
            return {"state": "unknown", "code": str(error), "facts": {}}
