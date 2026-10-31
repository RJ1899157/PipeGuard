"""Local producer adapter with durable, replayable observations and no credential logging."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID, uuid4


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


@dataclass(frozen=True)
class Observer:
    integration_id: str
    job_id: str
    token: str = field(repr=False)
    outbox: Path
    base_url: str = "http://127.0.0.1:8000"

    def __post_init__(self):
        UUID(self.integration_id)
        UUID(self.job_id)
        url = urlparse(self.base_url)
        if (url.scheme != "http" or url.hostname not in ("127.0.0.1", "localhost")
                or url.port != 8000 or url.username or url.password or url.path not in ("", "/")
                or url.query or url.fragment):
            raise ValueError("Observer requires the local PipeGuard endpoint")
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", self.token):
            raise ValueError("Invalid producer credential configuration")

    @classmethod
    def from_environment(cls, root):
        keys = ("PIPEGUARD_INTEGRATION_ID", "PIPEGUARD_JOB_ID", "PIPEGUARD_PRODUCER_TOKEN")
        if not any(key in os.environ for key in keys):
            return None
        if not all(os.environ.get(key) for key in keys):
            raise ValueError("Incomplete monitoring configuration")
        return cls(*(os.environ[key] for key in keys), outbox=root / "target/events",
                   base_url=os.environ.get("PIPEGUARD_BASE_URL", "http://127.0.0.1:8000"))

    @property
    def directory(self):
        path = self.outbox / self.integration_id / self.job_id
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path

    def emit(self, run_id, attempt, state, error_code=None):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/@+\-]{0,254}", run_id) or type(attempt) is not int or not 1 <= attempt <= 2147483647:
            raise ValueError("Invalid execution identity")
        if state not in ("running", "succeeded", "failed") or (error_code is not None and state != "failed"):
            raise ValueError("Invalid execution observation")
        if error_code not in (None, "connection_timeout", "source_unavailable", "validation_failed", "execution_error", "unknown"):
            raise ValueError("Unsupported error category")
        key = f"orders.{sha256(run_id.encode()).hexdigest()}.a{attempt}.{state}"
        event = dict(schema_version=1, event_id=key, integration_id=self.integration_id,
                     job_id=self.job_id, external_run_id=run_id, attempt_number=attempt, state=state,
                     occurred_at=datetime.now(timezone.utc).isoformat(), error_code=error_code)
        path = self.directory / (key + ".json")
        temporary = self.directory / (".pending-" + uuid4().hex)
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w") as stream:
                json.dump(event, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                previous = json.loads(path.read_text())
                if {k: v for k, v in previous.items() if k != "occurred_at"} != {k: v for k, v in event.items() if k != "occurred_at"}:
                    raise ValueError("Conflicting local observation identity")
        finally:
            temporary.unlink(missing_ok=True)
        return self.deliver(path)

    def deliver(self, path):
        marker = path.with_suffix(".sent")
        if marker.exists():
            return True
        try:
            payload = json.loads(path.read_text())
            if payload["integration_id"] != self.integration_id or payload["job_id"] != self.job_id:
                return False
            request = Request(self.base_url.rstrip("/") + "/v1/events", data=json.dumps(payload).encode(),
                              headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"}, method="POST")
            opener = build_opener(ProxyHandler({}), NoRedirect())
            with opener.open(request, timeout=5) as response:
                answer = json.loads(response.read(65536))
                if response.status != 202:
                    return False
                UUID(answer["event_id"])
            marker.touch(mode=0o600)
            return True
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError):
            return False

    def replay(self):
        pending = list(self.directory.glob("*.json"))
        delivered = sum(self.deliver(path) for path in sorted(pending))
        return {"observations": len(pending), "acknowledged": delivered, "pending": len(pending)-delivered}
