"""Short-lived, principal-scoped materialized reads; never a claimed MVCC snapshot."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import secrets
from threading import BoundedSemaphore, RLock
import time

from fastapi import HTTPException


@dataclass(frozen=True)
class ReadSnapshot:
    scope: tuple
    expires: float
    expires_at: datetime
    captured_at: datetime
    items: list[dict]
    extra: dict
    size: int


class SnapshotStore:
    """One process owns bounded typed response copies; restart invalidates its tokens."""
    max_rows = 5000
    max_bytes = 8 * 1024 * 1024
    total_bytes = 64 * 1024 * 1024
    max_entries = 128
    ttl_seconds = 300

    def __init__(self):
        self._entries = {}
        self._lock = RLock()
        self._captures = BoundedSemaphore(2)

    def page(self, principal, scope, token, loader, *, limit, offset):
        scope = (principal.admin, str(principal.integration_id), *scope)
        if token == "new":
            token, entry = self._capture(scope, loader)
        else:
            with self._lock:
                self._prune(time.monotonic())
                entry = self._entries.get(token)
                if entry is None or entry.scope != scope:
                    raise HTTPException(410, "snapshot_expired_or_unavailable")
        return {"items": deepcopy(entry.items[offset:offset + limit]), "limit": limit, "offset": offset,
            "has_more": offset + limit < len(entry.items), **deepcopy(entry.extra),
            "snapshot": {"token": token, "expires_at": entry.expires_at,
                         "captured_at": entry.captured_at, "total_count": len(entry.items)}}

    def _capture(self, scope, loader):
        # Reject excess captures before materialization; cached reads remain available.
        if not self._captures.acquire(blocking=False):
            raise HTTPException(503, "snapshot_busy")
        try:
            with self._lock:
                self._prune(time.monotonic())
                if len(self._entries) >= self.max_entries or sum(e.size for e in self._entries.values()) >= self.total_bytes:
                    raise HTTPException(413, "snapshot_capacity_exceeded")
            captured_at = datetime.now(timezone.utc)
            rows, extra = loader(self.max_rows + 1)
            if len(rows) > self.max_rows:
                raise HTTPException(413, "snapshot_capacity_exceeded")
            items = [row.model_dump(mode="json") for row in rows]
            size = len(json.dumps({"items": items, **extra}, separators=(",", ":")).encode())
            if size > self.max_bytes:
                raise HTTPException(413, "snapshot_capacity_exceeded")
            now = time.monotonic()
            entry = ReadSnapshot(scope, now + self.ttl_seconds,
                datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds), captured_at, items, deepcopy(extra), size)
            with self._lock:
                self._prune(now)
                if len(self._entries) >= self.max_entries or sum(e.size for e in self._entries.values()) + size > self.total_bytes:
                    raise HTTPException(413, "snapshot_capacity_exceeded")
                token = secrets.token_urlsafe(32)
                self._entries[token] = entry
            return token, entry
        finally:
            self._captures.release()

    def _prune(self, now):
        for token in [key for key, entry in self._entries.items() if entry.expires <= now]:
            del self._entries[token]
