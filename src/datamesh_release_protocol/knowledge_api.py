"""Authenticated API factory for the knowledge contour.

Caller supplies deployment-owned grants and bearer-token identities. Never accept
an actor identity or an authority grant from a mutation request body.
"""
from datetime import datetime, timezone
import secrets
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import Field
from .knowledge import KnowledgeRecord, KnowledgeStore
from .knowledge_release import KnowledgeReleaseEngine
from .models import DataContract, Migration, StrictModel

class Mutation(StrictModel):
    evidence_ref: str = Field(min_length=1)

class Proposal(StrictModel):
    record: KnowledgeRecord

class SnapshotRequest(StrictModel):
    proposal_id: str
    old_contract: DataContract
    new_contract: DataContract

class ReleaseRequest(StrictModel):
    snapshot_id: str
    run_id: str
    migrations: list[Migration] = Field(default_factory=list)


def create_knowledge_app(store: KnowledgeStore, token_actors: dict[str,str]):
    if not token_actors or any(not token or not actor for token,actor in token_actors.items()):
        raise ValueError('nonempty deployment token identities required')
    identities=dict(token_actors)
    engine=KnowledgeReleaseEngine(store)
    app=FastAPI(title='Domain-owned Knowledge and Release API',version='knowledge-1')
    async def identity(authorization: str | None=Header(default=None)):
        supplied=authorization[7:] if authorization and authorization.startswith('Bearer ') else ''
        actor=next((actor for token,actor in identities.items() if secrets.compare_digest(token,supplied)),None)
        if actor is None: raise HTTPException(401,'authenticated platform identity required')
        return actor
    def invoke(call):
        try:return call()
        except PermissionError as e:raise HTTPException(403,str(e)) from e
        except KeyError as e:raise HTTPException(404,'record or snapshot not found') from e
        except ValueError as e:raise HTTPException(409,str(e)) from e
    def producer(actor,domain):
        if not store._authorized(actor,domain,'product'):raise HTTPException(403,'producer authority required')
    @app.post('/records/propose')
    async def propose(body: Proposal,actor=Depends(identity)):
        at=datetime.now(timezone.utc)
        record=KnowledgeRecord.model_validate({**body.record.model_dump(),'valid_from':at})
        return invoke(lambda:store.propose_record(record,actor,at))
    @app.post('/records/{record_id}/confirm')
    async def confirm(record_id: str,body: Mutation,actor=Depends(identity)):
        return invoke(lambda:store.confirm_record(record_id,actor,body.evidence_ref,datetime.now(timezone.utc)))
    @app.post('/records/{record_id}/revoke')
    async def revoke(record_id: str,body: Mutation,actor=Depends(identity)):
        return invoke(lambda:store.revoke_record(record_id,actor,body.evidence_ref,datetime.now(timezone.utc)))
    @app.get('/impact/{product_id}')
    async def impact(product_id: str,at: datetime,fields: str='',actor=Depends(identity)):
        return invoke(lambda:store.list_impact(product_id,[f for f in fields.split(',') if f],at))
    @app.post('/snapshots')
    async def snapshot(body: SnapshotRequest,actor=Depends(identity)):
        producer(actor,body.old_contract.owner_domain)
        return invoke(lambda:store.build_snapshot(body.proposal_id,body.old_contract,body.new_contract,datetime.now(timezone.utc)))
    @app.get('/snapshots/{snapshot_id}')
    async def resolve(snapshot_id: str,actor=Depends(identity)):
        return invoke(lambda:store.resolve_snapshot(snapshot_id))
    @app.post('/release')
    async def release(body: ReleaseRequest,actor=Depends(identity)):
        snapshot=invoke(lambda:store.resolve_snapshot(body.snapshot_id))
        producer(actor,snapshot.old_contract.owner_domain)
        return invoke(lambda:engine.run(body.snapshot_id,body.run_id,datetime.now(timezone.utc),body.migrations))
    return app
