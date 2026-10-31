"""Authenticated local API. Synchronous routes run database work in worker threads."""
from contextlib import asynccontextmanager
from dataclasses import dataclass
from hashlib import sha256
import secrets
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from pipeguard.api.schemas import (
    AttemptView, CredentialIssued, ErrorResponse, EventAccepted, EventView, IntegrationCreate,
    IntegrationView, JobCreate, JobView, Page, RunView,
)
from pipeguard.api.settings import Settings
from pipeguard.api.pagination import SnapshotStore
from pipeguard.db.models import Attempt, IngestedEvent, Integration, Job, ProducerCredential, Run
from pipeguard.db.permissions import verify_runtime_access
from pipeguard.ingestion.contracts import ExecutionEvent
from pipeguard.ingestion.service import IngestionRejected, process, receive


class RequestBoundary:
    """Bound actual body bytes, including chunked requests, before JSON parsing."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive_message, send):
        if scope["type"] != "http":
            return await self.app(scope, receive_message, send)
        headers = dict(scope.get("headers", []))
        if b"origin" in headers:
            return await JSONResponse({"error": "browser_origin_not_enabled"}, status_code=403)(scope, receive_message, send)
        body = bytearray()
        while True:
            message = await receive_message()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > 65536:
                return await JSONResponse({"error": "request_too_large"}, status_code=413)(scope, receive_message, send)
            if not message.get("more_body", False):
                break
        consumed = False
        async def bounded_receive():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive_message()
        async def safe_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [
                    (b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff")]
            await send(message)
        await self.app(scope, bounded_receive, safe_send)


@dataclass(frozen=True)
class Principal:
    admin: bool
    integration_id: UUID | None = None


def create_app(settings: Settings | None = None, *, engine=None):
    settings = settings or Settings.from_environment()
    owned_engine = engine is None
    engine = engine or create_engine(settings.database_url, hide_parameters=True, pool_pre_ping=True,
                                      connect_args={"connect_timeout": 5, "options": "-cstatement_timeout=10000 -clock_timeout=5000"})
    admin_hash = sha256(settings.admin_token.encode()).hexdigest()
    snapshots = SnapshotStore()

    @asynccontextmanager
    async def lifespan(app):
        try:
            # Startup verification happens once before the server accepts requests.
            with engine.connect() as connection:
                verify_runtime_access(connection)
            yield
        finally:
            if owned_engine:
                engine.dispose()

    app = FastAPI(title="PipeGuard API", version="0.1.0", lifespan=lifespan,
                  responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 410, 413, 422, 503)},
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(RequestBoundary)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    bearer = HTTPBearer(auto_error=False)

    def authenticate(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> Principal:
        invalid = HTTPException(401, "authentication_required", headers={"WWW-Authenticate": "Bearer"})
        if credentials is None or len(credentials.credentials) > 128:
            raise invalid
        digest = sha256(credentials.credentials.encode()).hexdigest()
        if secrets.compare_digest(digest, admin_hash):
            return Principal(True)
        with Session(engine) as session:
            credential = session.scalar(select(ProducerCredential).join(Integration).where(
                ProducerCredential.token_hash == digest, ProducerCredential.revoked.is_(False),
                Integration.enabled.is_(True)))
            if credential is None:
                raise invalid
            return Principal(False, credential.integration_id)

    def administrator(principal: Annotated[Principal, Depends(authenticate)]) -> Principal:
        if not principal.admin:
            raise HTTPException(403, "administrator_required")
        return principal

    Caller = Annotated[Principal, Depends(authenticate)]
    Admin = Annotated[Principal, Depends(administrator)]
    Limit = Annotated[int, Query(ge=1, le=100)]
    Offset = Annotated[int, Query(ge=0, le=100000)]

    def scoped_run(session, run_id, principal):
        statement = select(Run).join(Job).where(Run.id == run_id)
        if not principal.admin:
            statement = statement.where(Job.integration_id == principal.integration_id)
        run = session.scalar(statement)
        if run is None:
            raise HTTPException(404, "run_not_found")
        return run

    def scoped_event(session, event_id, principal):
        statement = select(IngestedEvent).where(IngestedEvent.id == event_id)
        if not principal.admin:
            statement = statement.where(IngestedEvent.integration_id == principal.integration_id)
        event = session.scalar(statement)
        if event is None:
            raise HTTPException(404, "event_not_found")
        return event

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def validation_error(request, exc):
        return JSONResponse({"error": "invalid_request"}, status_code=422)

    @app.exception_handler(IntegrityError)
    async def identity_error(request, exc):
        return JSONResponse({"error": "identity_conflict"}, status_code=409)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        return JSONResponse({"error": "database_unavailable"}, status_code=503)

    @app.exception_handler(IngestionRejected)
    async def ingestion_error(request, exc):
        code = str(exc)
        status = 409 if code == "event_id_content_conflict" else 422
        return JSONResponse({"error": code}, status_code=status)

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready(principal: Admin):
        with engine.connect() as connection:
            connection.execute(text("SELECT 1 FROM integrations LIMIT 0"))
        return {"status": "ready"}

    @app.get("/v1/openapi.json", include_in_schema=False)
    def openapi(principal: Admin):
        return app.openapi()

    @app.post("/v1/integrations", response_model=IntegrationView, status_code=201)
    def create_integration(body: IntegrationCreate, principal: Admin):
        with Session(engine) as session, session.begin():
            record = Integration(**body.model_dump())
            session.add(record)
            session.flush()
            return IntegrationView.model_validate(record)

    @app.get("/v1/integrations", response_model=Page[IntegrationView])
    def integrations(principal: Admin, limit: Limit = 50, offset: Offset = 0,
                     snapshot: Annotated[str | None, Query(max_length=128)] = None):
        if snapshot is not None:
            def load(cap):
                with Session(engine) as session:
                    return ([IntegrationView.model_validate(x) for x in session.scalars(select(Integration)
                        .order_by(Integration.created_at, Integration.id).limit(cap))], {})
            return snapshots.page(principal, ("integrations",), snapshot, load, limit=limit, offset=offset)
        with Session(engine) as session:
            records = list(session.scalars(select(Integration).order_by(Integration.created_at, Integration.id).limit(limit+1).offset(offset)))
            return Page[IntegrationView](items=[IntegrationView.model_validate(x) for x in records[:limit]], limit=limit, offset=offset, has_more=len(records)>limit)

    @app.post("/v1/integrations/{integration_id}/disable")
    def disable_integration(integration_id: UUID, principal: Admin):
        with Session(engine) as session, session.begin():
            record = session.get(Integration, integration_id)
            if record is None:
                raise HTTPException(404, "integration_not_found")
            record.enabled = False
        return {"status": "disabled"}

    @app.post("/v1/jobs", response_model=JobView, status_code=201)
    def create_job(body: JobCreate, principal: Admin):
        with Session(engine) as session, session.begin():
            integration = session.get(Integration, body.integration_id)
            if integration is None or not integration.enabled:
                raise HTTPException(404, "integration_not_found")
            record = Job(**body.model_dump())
            session.add(record)
            session.flush()
            return JobView.model_validate(record)

    @app.get("/v1/jobs", response_model=Page[JobView])
    def jobs(principal: Caller, limit: Limit = 50, offset: Offset = 0,
             snapshot: Annotated[str | None, Query(max_length=128)] = None):
        statement = select(Job)
        if not principal.admin:
            statement = statement.where(Job.integration_id == principal.integration_id)
        if snapshot is not None:
            def load(cap):
                with Session(engine) as session:
                    return ([JobView.model_validate(x) for x in session.scalars(statement
                        .order_by(Job.created_at, Job.id).limit(cap))], {})
            return snapshots.page(principal, ("jobs",), snapshot, load, limit=limit, offset=offset)
        with Session(engine) as session:
            records = list(session.scalars(statement.order_by(Job.created_at, Job.id).limit(limit+1).offset(offset)))
            return Page[JobView](items=[JobView.model_validate(x) for x in records[:limit]], limit=limit, offset=offset, has_more=len(records)>limit)

    @app.post("/v1/integrations/{integration_id}/credentials", response_model=CredentialIssued, status_code=201)
    def issue_credential(integration_id: UUID, principal: Admin):
        token = secrets.token_urlsafe(32)
        with Session(engine) as session, session.begin():
            integration = session.get(Integration, integration_id)
            if integration is None or not integration.enabled:
                raise HTTPException(404, "integration_not_found")
            record = ProducerCredential(integration_id=integration_id, token_hash=sha256(token.encode()).hexdigest())
            session.add(record)
            session.flush()
            return CredentialIssued(id=record.id, integration_id=integration_id, token=token)

    @app.post("/v1/credentials/{credential_id}/revoke")
    def revoke(credential_id: UUID, principal: Admin):
        with Session(engine) as session, session.begin():
            credential = session.get(ProducerCredential, credential_id)
            if credential is None:
                raise HTTPException(404, "credential_not_found")
            credential.revoked = True
        return {"status": "revoked"}

    @app.post("/v1/events", response_model=EventAccepted, status_code=202)
    def submit(body: ExecutionEvent, principal: Caller):
        if not principal.admin and body.integration_id != principal.integration_id:
            raise HTTPException(403, "integration_scope_mismatch")
        receipt = receive(engine, body.model_dump(mode="json"))
        try:
            outcome = process(engine, receipt.event_id)
            state, warning = outcome.processing_state, outcome.error
        except SQLAlchemyError:
            state, warning = "pending", "processing_deferred"
        return EventAccepted(event_id=receipt.event_id, replayed=receipt.replayed, processing_state=state, warning=warning)

    @app.get("/v1/events/{event_id}", response_model=EventView)
    def event_status(event_id: UUID, principal: Caller):
        with Session(engine) as session:
            return EventView.model_validate(scoped_event(session, event_id, principal))

    @app.post("/v1/events/{event_id}/process")
    def retry_event(event_id: UUID, principal: Caller):
        with Session(engine) as session:
            scoped_event(session, event_id, principal)
        outcome = process(engine, event_id)
        return {"event_id": str(outcome.event_id), "processing_state": outcome.processing_state, "warning": outcome.error}

    @app.get("/v1/runs", response_model=Page[RunView])
    def runs(principal: Caller, limit: Limit = 50, offset: Offset = 0, job_id: UUID | None = None,
             snapshot: Annotated[str | None, Query(max_length=128)] = None):
        statement = select(Run).join(Job)
        if not principal.admin:
            statement = statement.where(Job.integration_id == principal.integration_id)
        if job_id is not None:
            statement = statement.where(Job.id == job_id)
        if snapshot is not None:
            def load(cap):
                with Session(engine) as session:
                    return ([RunView.model_validate(x) for x in session.scalars(statement
                        .order_by(Run.created_at.desc(), Run.id.desc()).limit(cap))], {})
            return snapshots.page(principal, ("runs", str(job_id)), snapshot, load, limit=limit, offset=offset)
        with Session(engine) as session:
            records = list(session.scalars(statement.order_by(Run.created_at.desc(), Run.id.desc()).limit(limit+1).offset(offset)))
            return Page[RunView](items=[RunView.model_validate(x) for x in records[:limit]], limit=limit, offset=offset, has_more=len(records)>limit)

    @app.get("/v1/runs/{run_id}", response_model=RunView)
    def run_detail(run_id: UUID, principal: Caller):
        with Session(engine) as session:
            return RunView.model_validate(scoped_run(session, run_id, principal))

    @app.get("/v1/runs/{run_id}/attempts", response_model=Page[AttemptView])
    def attempts(run_id: UUID, principal: Caller, limit: Limit = 50, offset: Offset = 0,
                 snapshot: Annotated[str | None, Query(max_length=128)] = None):
        if snapshot is not None:
            def load(cap):
                with Session(engine) as session:
                    scoped_run(session, run_id, principal)
                    return ([AttemptView.model_validate(x) for x in session.scalars(select(Attempt)
                        .where(Attempt.run_id == run_id).order_by(Attempt.attempt_number, Attempt.id).limit(cap))], {})
            return snapshots.page(principal, ("attempts", str(run_id)), snapshot, load, limit=limit, offset=offset)
        with Session(engine) as session:
            scoped_run(session, run_id, principal)
            records = list(session.scalars(select(Attempt).where(Attempt.run_id == run_id).order_by(Attempt.attempt_number, Attempt.id).limit(limit+1).offset(offset)))
            return Page[AttemptView](items=[AttemptView.model_validate(x) for x in records[:limit]], limit=limit, offset=offset, has_more=len(records)>limit)

    from pipeguard.detection.api import install_routes
    install_routes(app, engine, authenticate, administrator, snapshots)
    from pipeguard.lineage.api import install_routes as install_lineage_routes
    install_lineage_routes(app, engine, authenticate)
    return app
