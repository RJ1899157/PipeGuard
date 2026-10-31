"""Read-only public API adapter. Never reads the orchestrator database or raw logs."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from urllib.parse import quote
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError, URLError


class SourceUnavailable(RuntimeError):
    """Only fixed safe codes may cross this adapter boundary."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def external_id(dag, run, task):
    return "airflow-" + sha256("|".join((dag, run, task)).encode()).hexdigest()


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timezone required")
    return result.astimezone(timezone.utc)


STATES = {"success": "succeeded", "failed": "failed", "upstream_failed": "blocked",
          "skipped": "skipped", "removed": "cancelled", "running": "running",
          "queued": "queued", "scheduled": "queued", "up_for_retry": "failed",
          "up_for_reschedule": "waiting", "deferred": "waiting", "awaiting_input": "waiting",
          "restarting": "waiting", None: "queued"}


class AirflowClient:
    def __init__(self, username, password):
        if username != "pipeguard_observer":
            raise ValueError("A dedicated read-only observer is required")
        self._username, self._password = username, password
        self._token = None
        self._opener = build_opener(ProxyHandler({}), NoRedirect())

    def _request(self, path, body=None):
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = "Bearer " + self._token
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request("http://127.0.0.1:8080" + path, headers=headers,
                          data=json.dumps(body).encode() if body is not None else None)
        try:
            with self._opener.open(request, timeout=5) as response:
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise SourceUnavailable("source_response_too_large")
                return json.loads(raw)
        except HTTPError as exc:
            if exc.code in (401, 403):
                self._token = None
                raise SourceUnavailable("source_authentication_failed") from None
            raise SourceUnavailable("source_http_error") from None
        except (URLError, TimeoutError, OSError):
            raise SourceUnavailable("source_unreachable") from None
        except (ValueError, TypeError):
            raise SourceUnavailable("source_invalid_response") from None

    def _authenticate(self):
        answer = self._request("/auth/token", {"username": self._username, "password": self._password})
        if not isinstance(answer, dict) or not isinstance(answer.get("access_token"), str):
            raise SourceUnavailable("source_authentication_failed")
        self._token = answer["access_token"]

    def get(self, path):
        if not self._token:
            self._authenticate()
        try:
            return self._request(path)
        except SourceUnavailable as error:
            if str(error) != "source_authentication_failed":
                raise
            # Expiring bearer tokens are normal. Refresh once; persistent denial is a coverage fault.
            self._authenticate()
            return self._request(path)

    def scan(self, dag_id, task_id):
        self.partial = []
        self.run_facts = []
        try:
            return self._scan(dag_id, task_id)
        except (KeyError, ValueError, TypeError, AttributeError):
            raise SourceUnavailable("source_invalid_response") from None

    def _scan(self, dag_id, task_id):
        """All-or-incomplete scan. A cap or missing try produces an explicit coverage fault."""
        dag_path = "/api/v2/dags/" + quote(dag_id, safe="")
        snapshots, seen = self.partial, set()
        health = self.get("/api/v2/monitor/health")
        unhealthy = False
        for component in ("metadatabase", "scheduler", "dag_processor"):
            if health[component]["status"] != "healthy":
                unhealthy = True
        dag = self.get(dag_path)
        import_errors = dag["has_import_errors"]
        if type(import_errors) is not bool:
            raise SourceUnavailable("source_invalid_response")
        self.is_paused = dag["is_paused"]
        if type(self.is_paused) is not bool:
            raise SourceUnavailable("source_invalid_response")
        offset = 0
        for _ in range(100):
            page = self.get(dag_path + f"/dagRuns?limit=100&offset={offset}&order_by=id")
            runs, total = page["dag_runs"], page["total_entries"]
            if type(total) is not int or total < 0 or not isinstance(runs, list):
                raise SourceUnavailable("source_invalid_response")
            for run in runs:
                run_id = run["dag_run_id"]
                if run_id in seen:
                    raise SourceUnavailable("source_unstable_pagination")
                seen.add(run_id)
                run_time = run.get("end_date") or run.get("start_date") or run.get("queued_at") or run.get("run_after")
                if not run_time:
                    raise SourceUnavailable("source_missing_timestamp")
                self.run_facts.append((timestamp(run_time), {
                    "external_run_id": external_id(dag_id, run_id, task_id),
                    "dag_id": dag_id, "dag_run_id": run_id,
                    "state": STATES.get(run.get("state"), "unknown")}))
                path = dag_path + "/dagRuns/" + quote(run_id, safe="") + "/taskInstances/" + quote(task_id, safe="")
                current = self.get(path)
                if current.get("map_index", -1) != -1:
                    raise SourceUnavailable("source_unsupported_mapping")
                history = self.get(path + "/tries")
                tries = history["task_instances"]
                if len(tries) != history["total_entries"]:
                    raise SourceUnavailable("source_incomplete_history")
                by_number = {}
                for entry in tries + [current]:
                    number = entry["try_number"]
                    if type(number) is not int or number < 0:
                        raise SourceUnavailable("source_invalid_response")
                    # Current try takes precedence over its historical snapshot.
                    by_number[number] = entry
                positive = {n for n in by_number if n > 0}
                if positive and len(positive) != max(positive):
                    raise SourceUnavailable("source_incomplete_history")
                for number, entry in sorted(by_number.items()):
                    state = STATES.get(entry["state"], "unknown")
                    ended = entry.get("end_date")
                    started = entry.get("start_date") or entry.get("queued_when") or run.get("queued_at") or run.get("run_after")
                    when = ended or started
                    if not when:
                        raise SourceUnavailable("source_missing_timestamp")
                    # Zero denotes a task not started yet; no fabricated failed try.
                    snapshots.append((timestamp(when), {
                        "external_run_id": external_id(dag_id, run_id, task_id), "attempt_number": max(1, number),
                        "state": state, "started_at": timestamp(started).isoformat() if started else None,
                        "finished_at": timestamp(ended).isoformat() if ended else None,
                        "dag_id": dag_id, "dag_run_id": run_id, "task_id": task_id,
                        "raw_state": entry["state"]}))
            offset += len(runs)
            if offset >= total:
                if unhealthy:
                    raise SourceUnavailable("source_component_unhealthy")
                if import_errors:
                    raise SourceUnavailable("source_dag_import_error")
                return snapshots
            if not runs:
                raise SourceUnavailable("source_incomplete_pagination")
        raise SourceUnavailable("source_scan_limit_exceeded")
