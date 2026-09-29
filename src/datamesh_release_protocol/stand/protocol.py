from __future__ import annotations

from typing import Any, Literal
from pydantic import Field
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization

from ..knowledge import KnowledgeSnapshot, canonical, digest
from ..knowledge_release import evaluate_snapshot, request_fingerprint
from ..models import Decision, Migration, StrictModel
from ..validators import _schema_checks


class WorkItem(StrictModel):
    event_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    snapshot: KnowledgeSnapshot
    migrations: list[Migration] = Field(default_factory=list)


class Vote(StrictModel):
    kind: Literal['VERDICT','FENCE']
    event_id: str
    request_id: str
    run_id: str
    proposal_id: str
    snapshot_id: str
    domain_id: str
    request_fingerprint: str
    old_contract_version: str
    new_contract_version: str
    membership_epoch: int | None
    revision: str
    decision: Decision | None = None
    evidence: list[dict[str,Any]] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class SignedMessage(StrictModel):
    vote: Vote
    signature: str


def keypair():
    private=Ed25519PrivateKey.generate()
    return (private.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption()).hex(),
            private.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex())


def sign(vote: Vote, private_hex: str):
    return SignedMessage(vote=vote,signature=Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_hex)).sign(canonical(vote.model_dump(mode='json')).encode()).hex())


def verify(message: SignedMessage, public_hex: str):
    Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_hex)).verify(bytes.fromhex(message.signature),canonical(message.vote.model_dump(mode='json')).encode())


def route(owner, routes):
    if owner not in routes: raise ValueError('unrouted authority domain: '+owner)
    return routes[owner]


def owned_records(snapshot, domain, routes):
    return sorted([r for r in snapshot.records if route(r.owner_domain,routes)==domain],key=lambda r:r.record_id)


def revision(records):
    return digest([r.model_dump(mode='json') for r in sorted(records,key=lambda r:r.record_id)])


def required_domains(snapshot, routes):
    owners={snapshot.old_contract.owner_domain}
    owners.update(r.owner_domain for r in snapshot.records if (r.kind=='obligation' and r.data['mandatory']) or r.kind=='global_rule')
    # Coverage consumers may have no obligation. Include every known active consumer domain.
    owners.update(r.owner_domain for r in snapshot.records if r.kind=='usage' and r.data['consumer_id'] in snapshot.required_consumer_ids)
    return sorted({route(owner,routes) for owner in owners})


def evaluate_domain(snapshot, domain, routes, migrations):
    snapshot.verify()
    records=[r for r in snapshot.records if r.kind not in ('obligation','global_rule') or route(r.owner_domain,routes)==domain]
    consumers=sorted({r.data['requirement']['consumer_id'] for r in records if r.kind=='obligation' and r.data['mandatory']})
    local=snapshot.model_copy(update={'records':records,'required_consumer_ids':consumers})
    return evaluate_snapshot(local,migrations)


def make_vote(work, domain, routes, current_records, kind='VERDICT'):
    snapshot=work.snapshot;snapshot.verify()
    own_revision=revision(current_records)
    expected=revision(owned_records(snapshot,domain,routes))
    issues=[] if own_revision==expected else ['local_revision_mismatch']
    decision,evidence=evaluate_domain(snapshot,domain,routes,work.migrations) if kind=='VERDICT' else (None,[])
    if issues and kind=='VERDICT': decision,evidence=Decision.NEEDS_REVIEW,[]
    if decision==Decision.REJECT and not evidence:issues.append('SCHEMA_BREAKING')
    payload=dict(kind=kind,request_id=work.event_id,run_id=work.run_id,proposal_id=snapshot.proposal_id,
        snapshot_id=snapshot.snapshot_id,domain_id=domain,request_fingerprint=request_fingerprint(snapshot.snapshot_id,work.migrations),
        old_contract_version=snapshot.old_contract.contract_version,new_contract_version=snapshot.new_contract.contract_version,
        membership_epoch=snapshot.membership_epoch,revision=own_revision,decision=decision,evidence=evidence,issues=issues)
    return Vote(event_id=digest(payload),**payload)
