"""Scoped lineage ingestion/history/traversal and immutable incident evidence capture."""
from typing import Annotated
from uuid import UUID
from fastapi import Depends, HTTPException, Query
from pydantic import AwareDatetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from pipeguard.db.models import EvidenceBundle, Incident, Job, LineageEvent, LineageRun, LineageExpectation
from pipeguard.lineage.contracts import LineageReport, ExpectationCreate
from pipeguard.lineage.service import graph, receive, LineageRejected
from pipeguard.lineage.evidence import capture


def install_routes(app, engine, authenticate):
    Caller = Annotated[object, Depends(authenticate)]
    def job(session, job_id, principal):
        row = session.get(Job, job_id)
        if row is None or (not principal.admin and row.integration_id != principal.integration_id):
            raise HTTPException(404,"job_not_found")
        return row
    def incident(session, incident_id, principal):
        row = session.get(Incident, incident_id)
        if row is None:
            raise HTTPException(404,"incident_not_found")
        try:
            job(session,row.job_id,principal)
        except HTTPException:
            raise HTTPException(404,"incident_not_found") from None
        return row

    @app.exception_handler(LineageRejected)
    async def rejected(request, error):
        from fastapi.responses import JSONResponse
        code = str(error)
        return JSONResponse({"error":code},status_code=404 if code=="dataset_not_found_in_scope" else
                            409 if code in {"lineage_content_conflict","lineage_run_identity_conflict","lineage_scan_limit"} else 422)

    @app.post('/v1/lineage-expectations',status_code=201)
    def expectation(body:ExpectationCreate,principal:Caller):
        if not principal.admin:
            raise HTTPException(403,'administrator_required')
        with Session(engine) as session,session.begin():
            job(session,body.job_id,principal)
            row=LineageExpectation(**body.model_dump());session.add(row);session.flush()
            return {'id':str(row.id),'job_id':str(row.job_id),'grace_seconds':row.grace_seconds,
                    'version':row.version,'created_at':row.created_at}

    @app.get('/v1/jobs/{job_id}/lineage-expectation')
    def inspect_expectation(job_id:UUID,principal:Caller):
        with Session(engine) as session:
            job(session,job_id,principal)
            row=session.scalar(select(LineageExpectation).where(LineageExpectation.job_id==job_id))
            if row is None:
                raise HTTPException(404,'lineage_expectation_not_configured')
            return {'id':str(row.id),'job_id':str(row.job_id),'grace_seconds':row.grace_seconds,
                    'version':row.version,'created_at':row.created_at}

    @app.post('/v1/lineage-events',status_code=202)
    def submit(body:LineageReport,principal:Caller):
        if not principal.admin and body.integration_id!=principal.integration_id:
            raise HTTPException(403,'integration_scope_mismatch')
        return receive(engine,body)

    @app.get('/v1/lineage-events/{event_id}')
    def detail(event_id:UUID,principal:Caller):
        with Session(engine) as session:
            row=session.get(LineageEvent,event_id)
            if not row or (not principal.admin and row.integration_id!=principal.integration_id):
                raise HTTPException(404,'lineage_event_not_found')
            return {'id':str(row.id),'payload':row.payload,'payload_hash':row.payload_hash,
                    'occurred_at':row.occurred_at,'received_at':row.created_at}

    @app.get('/v1/jobs/{job_id}/lineage')
    def lineage(job_id:UUID,principal:Caller, external_run_id:str|None=None,
                attempt_number:Annotated[int|None,Query(ge=1,le=2147483647)]=None,
                as_of:AwareDatetime|None=None,known_at:AwareDatetime|None=None,
                root_dataset_id:UUID|None=None,direction:str='downstream',
                depth:Annotated[int,Query(ge=1,le=12)]=6,
                max_nodes:Annotated[int,Query(ge=1,le=200)]=200):
        if direction not in ('upstream','downstream','both') or (external_run_id is not None and len(external_run_id)>255):
            raise HTTPException(422,'invalid_request')
        with Session(engine) as session:
            job(session,job_id,principal)
            return graph(session,job_id,external_run_id=external_run_id,attempt_number=attempt_number,
                         as_of=as_of,known_at=known_at,root=root_dataset_id,direction=direction,depth=depth,max_nodes=max_nodes)

    @app.post('/v1/incidents/{incident_id}/evidence-bundles',status_code=201)
    def snapshot(incident_id:UUID,principal:Caller):
        with Session(engine) as session:
            incident(session,incident_id,principal)
        return capture(engine,incident_id)

    @app.get('/v1/evidence-bundles/{bundle_id}')
    def bundle(bundle_id:UUID,principal:Caller):
        with Session(engine) as session:
            row=session.get(EvidenceBundle,bundle_id)
            if not row:
                raise HTTPException(404,'evidence_bundle_not_found')
            incident(session,row.incident_id,principal)
            return {'id':str(row.id),'incident_id':str(row.incident_id),'payload_hash':row.payload_hash,
                    'created_at':row.created_at,'payload':row.payload}
