from datetime import datetime, timezone
from hashlib import sha256
import json
import os
import secrets
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pipeguard.api.app import create_app
from pipeguard.api.settings import Settings
from pipeguard.db.models import IngestedEvent, ProducerCredential
from pipeguard.db.permissions import grant_runtime_access


@pytest.fixture
def api(migrated_database):
    connection, _ = migrated_database
    schema = connection.scalar(text("SELECT current_schema()"))
    grant_runtime_access(connection, schema=schema)
    connection.commit()
    engine = create_engine(os.environ["PIPEGUARD_API_DATABASE_URL"], hide_parameters=True,
                           connect_args={"options": f"-csearch_path={schema} -cstatement_timeout=5000 -clock_timeout=3000"})
    admin_token = secrets.token_urlsafe(32)
    app = create_app(Settings(os.environ["PIPEGUARD_API_DATABASE_URL"], admin_token), engine=engine)
    try:
        with TestClient(app) as client:
            yield client, {"Authorization": f"Bearer {admin_token}"}, engine, connection
    finally:
        engine.dispose()


def producer(api, name="orders"):
    client, admin, _, _ = api
    integration = client.post("/v1/integrations", headers=admin,
                              json={"name": name, "environment": "test", "kind": "synthetic"})
    assert integration.status_code == 201
    integration_id = integration.json()["id"]
    job = client.post("/v1/jobs", headers=admin,
                      json={"integration_id": integration_id, "namespace": "test", "name": name, "kind": "job"})
    assert job.status_code == 201
    issued = client.post(f"/v1/integrations/{integration_id}/credentials", headers=admin)
    assert issued.status_code == 201
    credential = issued.json()
    headers = {"Authorization": "Bearer " + credential["token"]}
    event = {"schema_version": 1, "event_id": "start-1", "integration_id": integration_id,
             "job_id": job.json()["id"], "external_run_id": "run-1", "attempt_number": 1,
             "state": "running", "occurred_at": datetime(2026, 10, 31, 10, tzinfo=timezone.utc).isoformat()}
    return headers, event, credential


def test_api_successful_retry_preserves_failure(api):
    client, _, _, _ = api
    headers, event, _ = producer(api)
    first = client.post("/v1/events", headers=headers, json=event)
    assert first.status_code == 202 and first.json()["processing_state"] == "processed"
    failure = event | {"event_id": "failure-1", "state": "failed", "error_code": "connection_timeout",
                       "occurred_at": "2026-10-31T10:01:00Z"}
    assert client.post("/v1/events", headers=headers, json=failure).status_code == 202
    success = event | {"event_id": "success-2", "state": "succeeded", "attempt_number": 2,
                       "occurred_at": "2026-10-31T10:02:00Z"}
    assert client.post("/v1/events", headers=headers, json=success).status_code == 202
    run = client.get("/v1/runs", headers=headers).json()["items"][0]
    assert run["state"] == "succeeded" and not run["reconciliation_required"]
    detail = client.get(f"/v1/runs/{run['id']}", headers=headers)
    assert detail.status_code == 200
    attempts = client.get(f"/v1/runs/{run['id']}/attempts", headers=headers).json()["items"]
    assert [a["state"] for a in attempts] == ["failed", "succeeded"]
    assert attempts[0]["error_code"] == "connection_timeout"
    assert "error_message" not in attempts[0]
    status = client.get(f"/v1/events/{first.json()['event_id']}", headers=headers)
    assert status.status_code == 200 and "payload" not in status.json()


@pytest.mark.parametrize("method,path", [
    ("get", "/v1/runs"), ("post", "/v1/integrations"),
    ("get", "/v1/openapi.json"), ("get", "/health/ready"), ("get", "/v1/jobs"),
])
def test_authentication_required(api, method, path):
    client, _, _, _ = api
    assert getattr(client, method)(path).status_code == 401
    assert getattr(client, method)(path, headers={"Authorization": "Bearer invalid"}).status_code == 401


def test_producer_is_scoped_and_cannot_provision(api):
    client, _, _, _ = api
    first, event1, _ = producer(api, "first")
    second, event2, _ = producer(api, "second")
    accepted = client.post("/v1/events", headers=first, json=event1).json()
    client.post("/v1/events", headers=second, json=event2)
    assert client.post("/v1/events", headers=second, json=event1).status_code == 403
    assert client.post("/v1/integrations", headers=first,
                       json={"name": "bad", "environment": "test", "kind": "synthetic"}).status_code == 403
    assert client.post(f"/v1/integrations/{event2['integration_id']}/credentials", headers=first).status_code == 403
    assert client.get(f"/v1/events/{accepted['event_id']}", headers=second).status_code == 404
    assert client.post(f"/v1/events/{accepted['event_id']}/process", headers=second).status_code == 404
    run = client.get("/v1/runs", headers=first).json()["items"][0]
    assert client.get(f"/v1/runs/{run['id']}", headers=second).status_code == 404
    assert client.get(f"/v1/runs/{run['id']}/attempts", headers=second).status_code == 404
    assert len(client.get("/v1/jobs", headers=first).json()["items"]) == 1
    assert len(client.get("/v1/runs", headers=second).json()["items"]) == 1


def test_credentials_hashed_and_revocable(api):
    client, admin, _, connection = api
    headers, event, issued = producer(api)
    with Session(connection) as session:
        stored = session.get(ProducerCredential, issued["id"])
        assert stored.token_hash == sha256(issued["token"].encode()).hexdigest()
        assert not hasattr(stored, "token")
    assert client.post(f"/v1/credentials/{issued['id']}/revoke", headers=admin).status_code == 200
    assert client.post("/v1/events", headers=headers, json=event).status_code == 401


def test_disabled_integration_invalidates_producer(api):
    client, admin, _, _ = api
    headers, event, _ = producer(api)
    assert client.post(f"/v1/integrations/{event['integration_id']}/disable", headers=admin).status_code == 200
    assert client.get("/v1/jobs", headers=headers).status_code == 401


def test_exact_replay_and_collision_http_codes(api):
    client, _, _, _ = api
    headers, event, _ = producer(api)
    first = client.post("/v1/events", headers=headers, json=event)
    duplicate = client.post("/v1/events", headers=headers, json=event)
    assert duplicate.json()["replayed"] and duplicate.json()["event_id"] == first.json()["event_id"]
    collision = client.post("/v1/events", headers=headers, json=event | {"state": "failed"})
    assert collision.status_code == 409 and collision.json()["error"] == "event_id_content_conflict"


def test_validation_errors_do_not_echo_input(api):
    client, admin, _, _ = api
    marker = "SYNTHETIC_PRIVATE_INPUT_ONLY"
    response = client.post("/v1/integrations", headers=admin, json={"password": marker})
    assert response.status_code == 422 and marker not in response.text
    malformed = client.post("/v1/events", headers=admin | {"Content-Type": "application/json"},
                            content='{"secret":"'+marker+'"')
    assert malformed.status_code == 422 and marker not in malformed.text


def test_host_origin_and_actual_body_limits(api):
    client, admin, _, _ = api
    assert client.get("/health/live", headers={"Host": "attacker.example"}).status_code == 400
    assert client.get("/health/live", headers={"Origin": "https://attacker.example"}).status_code == 403
    assert client.post("/v1/events", headers=admin, content=b"x"*65537).status_code == 413
    assert client.post("/v1/events", headers=admin, content=iter([b"x"*40000,b"y"*30000])).status_code == 413
    assert client.get("/health/live").headers["cache-control"] == "no-store"


def test_pagination_and_openapi(api):
    client, admin, _, _ = api
    producer(api, "first")
    producer(api, "second")
    one = client.get("/v1/integrations?limit=1", headers=admin)
    two = client.get("/v1/integrations?limit=1&offset=1", headers=admin)
    assert one.json()["has_more"] and not two.json()["has_more"]
    assert one.json()["items"][0]["id"] != two.json()["items"][0]["id"]
    assert client.get("/v1/runs?limit=101", headers=admin).status_code == 422
    assert client.get("/v1/runs?offset=-1", headers=admin).status_code == 422
    schema = client.get("/v1/openapi.json", headers=admin).json()
    assert schema["paths"]["/v1/events"]["post"]["security"] == [{"HTTPBearer": []}]
    assert client.get("/docs").status_code == 404


def test_runtime_database_role_cannot_change_schema_or_history(api):
    _, _, engine, _ = api
    forbidden = ["CREATE TABLE unauthorized (id integer)", "DROP TABLE runs",
                 "DELETE FROM ingested_events", "TRUNCATE ingested_events",
                 "UPDATE ingested_events SET payload = '{}'::jsonb",
                 "DELETE FROM producer_credentials", "ALTER TABLE runs DISABLE TRIGGER ALL"]
    for statement in forbidden:
        with engine.begin() as connection:
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.exec_driver_sql(statement)


def test_owner_database_role_rejected_at_startup(migrated_database):
    connection, _ = migrated_database
    schema = connection.scalar(text("SELECT current_schema()"))
    connection.commit()
    engine = create_engine(os.environ["PIPEGUARD_DATABASE_URL"],
                           connect_args={"options": f"-csearch_path={schema}"})
    try:
        app = create_app(Settings(os.environ["PIPEGUARD_DATABASE_URL"], secrets.token_urlsafe(32)), engine=engine)
        with pytest.raises(RuntimeError, match="restricted database role"):
            with TestClient(app):
                pass
    finally:
        engine.dispose()


def test_projection_database_failure_keeps_receipt(api, monkeypatch):
    import pipeguard.api.app as api_module
    from sqlalchemy.exc import OperationalError
    client, _, _, connection = api
    headers, event, _ = producer(api)
    original = api_module.process
    def failure(*args):
        raise OperationalError("synthetic", {}, RuntimeError("synthetic"))
    monkeypatch.setattr(api_module, "process", failure)
    response = client.post("/v1/events", headers=headers, json=event)
    assert response.status_code == 202 and response.json()["warning"] == "processing_deferred"
    with Session(connection) as session:
        assert session.get(IngestedEvent, response.json()["event_id"]).processing_state == "pending"
    monkeypatch.setattr(api_module, "process", original)
    retry = client.post(f"/v1/events/{response.json()['event_id']}/process", headers=headers)
    assert retry.status_code == 200 and retry.json()["processing_state"] == "processed"
