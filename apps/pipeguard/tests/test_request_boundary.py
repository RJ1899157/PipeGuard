"""Exercise ASGI admission without a database, network or wall-clock-sized timeout."""
import asyncio
import json

import pytest

from pipeguard.api.app import RequestBoundary


def run_request(messages, *, headers=(), configure=None):
    sent, consumed = [], []

    async def application(scope, receive, send):
        consumed.append(await receive())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    boundary = RequestBoundary(application)
    if configure:
        configure(boundary)

    async def receive():
        value = next(messages)
        if callable(value):
            return await value()
        return value

    async def send(message):
        sent.append(message)

    asyncio.run(boundary({"type": "http", "headers": list(headers)}, receive, send))
    return boundary, sent, consumed


def test_exact_byte_cap_is_accepted_and_extra_byte_is_rejected_before_parsing():
    boundary, sent, consumed = run_request(iter([
        {"type": "http.request", "body": b"x" * 32768, "more_body": True},
        {"type": "http.request", "body": b"x" * 32768, "more_body": False},
    ]))
    assert sent[0]["status"] == 200 and len(consumed[0]["body"]) == 65536
    assert boundary._body_readers == 0
    _, sent, consumed = run_request(iter([{"type": "http.request", "body": b"x" * 65537}]))
    assert sent[0]["status"] == 413 and not consumed
    assert dict(sent[0]["headers"])[b"cache-control"] == b"no-store"


@pytest.mark.parametrize("headers,status,code", [
    ([(b"content-length", b"65537")], 413, "request_too_large"),
    ([(b"content-length", b"-1")], 400, "invalid_content_length"),
    ([(b"content-length", b"not-a-number")], 400, "invalid_content_length"),
    ([(b"content-length", b"9" * 100)], 400, "invalid_content_length"),
    ([(b"content-length", b"1"), (b"content-length", b"2")], 400, "invalid_content_length"),
    ([(b"origin", b"null")], 403, "browser_origin_not_enabled"),
])
def test_early_rejections_do_not_read_a_body_and_have_safe_headers(headers, status, code):
    _, sent, consumed = run_request(iter(()), headers=headers)
    assert sent[0]["status"] == status and json.loads(sent[1]["body"])["error"] == code
    assert dict(sent[0]["headers"])[b"x-content-type-options"] == b"nosniff"
    assert not consumed


def test_absolute_deadline_rejects_stalled_and_trickling_bodies():
    async def stalled():
        await asyncio.sleep(1)

    async def trickle():
        await asyncio.sleep(.005)
        return {"type": "http.request", "body": b"x", "more_body": True}

    for messages in (iter([stalled]), iter([trickle] * 100)):
        boundary, sent, consumed = run_request(messages, configure=lambda b: setattr(b, "body_timeout_seconds", .02))
        assert sent[0]["status"] == 408 and not consumed and boundary._body_readers == 0
        assert json.loads(sent[1]["body"]) == {"error": "request_body_timeout"}


def test_body_admission_disconnect_and_cancellation_release_capacity():
    async def exercise():
        started, release = asyncio.Event(), asyncio.Event()

        async def application(scope, receive, send):
            raise AssertionError("Incomplete bodies must never reach the application")

        boundary = RequestBoundary(application)
        boundary.max_body_readers = 1
        scope = {"type": "http", "headers": []}

        async def held_receive():
            started.set()
            await release.wait()
            return {"type": "http.disconnect"}

        async def disconnected():
            return {"type": "http.disconnect"}

        sent = []

        async def send(message):
            sent.append(message)

        held = asyncio.create_task(boundary(scope, held_receive, send))
        await started.wait()
        await boundary(scope, disconnected, send)
        assert sent[0]["status"] == 503 and json.loads(sent[1]["body"])["error"] == "request_body_busy"
        held.cancel()
        with pytest.raises(asyncio.CancelledError):
            await held
        assert boundary._body_readers == 0
        sent.clear()
        await boundary(scope, disconnected, send)
        assert not sent and boundary._body_readers == 0

    asyncio.run(exercise())
