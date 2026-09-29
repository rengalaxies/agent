"""Versioned, domain-owned metadata ledger and immutable release snapshots.

Authority grants are trusted deployment configuration, not assertions in records.
This module stores metadata only; it never imports scoring labels.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Literal

from pydantic import Field, model_validator

from .models import ConsumerObligation, DataContract, StrictModel

KINDS = Literal['team', 'product', 'attribute', 'usage', 'obligation', 'coverage', 'global_rule', 'constitution']


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('timezone-aware timestamp required')
    return value.astimezone(timezone.utc)


class Authority(StrictModel):
    actor: str
    domain: str
    kinds: list[KINDS]
    authority_ref: str


class TeamData(StrictModel):
    team_id: str
    domain_id: str
    authority_ref: str


class ProductData(StrictModel):
    product_id: str
    producer_team_ref: str
    contract: DataContract


class AttributeData(StrictModel):
    product_id: str
    field_path: str
    semantic_profile_ref: str
    contract_version: str


class UsageData(StrictModel):
    consumer_id: str
    consumer_team_ref: str
    product_id: str
    field_paths: list[str] = Field(min_length=1)
    purpose: str
    calculation_ref: str
    registration_ref: str
    active: bool = True


class ObligationData(StrictModel):
    usage_ref: str
    requirement: ConsumerObligation
    mandatory: bool = True


class CoverageData(StrictModel):
    product_id: str
    membership_epoch: int = Field(ge=1)
    registered_consumer_ids: list[str]
    registry_evidence_ref: str
    registration_boundary: str
    authority_ref: str

    @model_validator(mode='after')
    def unique_members(self):
        if len(set(self.registered_consumer_ids)) != len(self.registered_consumer_ids):
            raise ValueError('duplicate registered consumer')
        return self


class RuleData(StrictModel):
    product_id: str
    rule_id: str
    rule_version: str
    predicate: ConsumerObligation
    priority: int = 0


class ConstitutionData(StrictModel):
    product_id: str
    constitution_ref: str
    constitution_version: str
    content_hash: str


DATA_TYPES = {'team': TeamData, 'product': ProductData, 'attribute': AttributeData,
              'usage': UsageData, 'obligation': ObligationData, 'coverage': CoverageData,
              'global_rule': RuleData, 'constitution': ConstitutionData}


class KnowledgeRecord(StrictModel):
    record_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    kind: KINDS
    owner_domain: str
    status: Literal['candidate', 'confirmed', 'revoked'] = 'candidate'
    confirmed_by: str | None = None
    evidence_ref: str = Field(min_length=1)
    valid_from: datetime
    valid_until: datetime | None = None
    data: dict[str, Any]

    @model_validator(mode='after')
    def validate_payload(self):
        self.valid_from = utc(self.valid_from)
        if self.valid_until is not None:
            self.valid_until = utc(self.valid_until)
            if self.valid_until <= self.valid_from:
                raise ValueError('invalid validity interval')
        self.data = DATA_TYPES[self.kind].model_validate(self.data).model_dump(mode='json')
        if self.status == 'confirmed' and not self.confirmed_by:
            raise ValueError('confirmation actor required')
        return self


class KnowledgeSnapshot(StrictModel):
    snapshot_id: str
    schema_version: str = 'knowledge-1'
    proposal_id: str
    product_id: str
    as_of: datetime
    membership_epoch: int | None
    old_contract: DataContract
    new_contract: DataContract
    required_consumer_ids: list[str]
    records: list[KnowledgeRecord]
    completeness: Literal['complete', 'incomplete', 'unknown']
    issues: list[str]
    record_hashes: dict[str, str]
    canonical_payload_hash: str

    def payload(self):
        return self.model_dump(mode='json', exclude={'snapshot_id', 'canonical_payload_hash'})

    def verify(self):
        if digest(self.payload()) != self.snapshot_id or self.snapshot_id != self.canonical_payload_hash:
            raise ValueError('snapshot integrity failure')
        expected = {f'{r.record_id}@{r.version}': digest(r.model_dump(mode='json')) for r in self.records}
        if expected != self.record_hashes:
            raise ValueError('record integrity failure')


class KnowledgeStore:
    """Append-only history. Copies on reads prevent mutable model aliasing.

    Optional JSON persistence uses atomic replacement. One writer process per file;
    RLock protects snapshot/commit from in-process time-of-check races.
    """
    def __init__(self, authorities: list[Authority], path: Path | None = None):
        self.authorities = tuple(a.model_copy(deep=True) for a in authorities)
        self.path = path
        self.lock = RLock()
        self._records: dict[str, list[KnowledgeRecord]] = {}
        self._snapshots: dict[str, KnowledgeSnapshot] = {}
        self._events: list[dict] = []
        if path and path.exists():
            self._restore(json.loads(path.read_text()))

    def _authorized(self, actor, domain, kind):
        return next((a for a in self.authorities if a.actor == actor and a.domain == domain and kind in a.kinds), None)

    def _append(self, record, actor, operation, at):
        at = utc(at)
        if record.valid_from != at:
            raise ValueError('version effective time must equal event time')
        grant = self._authorized(actor, record.owner_domain, record.kind)
        if not grant:
            raise PermissionError('actor lacks configured domain authority')
        history = self._records.get(record.record_id, [])
        if record.version != len(history) + 1:
            raise ValueError('non-sequential immutable version')
        if history:
            prior = history[-1]
            if prior.kind != record.kind or prior.owner_domain != record.owner_domain:
                raise ValueError('identity/owner transfer requires explicit migration')
            if record.valid_from <= prior.valid_from:
                raise ValueError('event time must increase')
        copy = record.model_copy(deep=True)
        self._records.setdefault(record.record_id, []).append(copy)
        event = {'record_id': record.record_id, 'version': record.version, 'operation': operation,
                 'actor': actor, 'authority_ref': grant.authority_ref, 'at': at.isoformat(),
                 'evidence_ref': record.evidence_ref, 'record_hash': digest(record.model_dump(mode='json'))}
        event['previous_hash'] = digest(self._events[-1]) if self._events else None
        self._events.append(event)
        self._persist()
        return copy.model_copy(deep=True)

    def propose_record(self, record: KnowledgeRecord, actor: str, at: datetime):
        with self.lock:
            if record.status != 'candidate' or record.confirmed_by is not None:
                raise ValueError('proposal must be unconfirmed candidate')
            return self._append(record, actor, 'propose', at)

    def confirm_record(self, record_id: str, actor: str, evidence_ref: str, at: datetime):
        with self.lock:
            prior = self._records[record_id][-1]
            if prior.status == 'revoked':
                raise ValueError('revoked record requires a new proposal')
            record = KnowledgeRecord.model_validate({**prior.model_dump(), 'version': prior.version + 1,
                'status': 'confirmed', 'confirmed_by': actor, 'evidence_ref': evidence_ref, 'valid_from': at})
            return self._append(record, actor, 'confirm', at)

    def revoke_record(self, record_id: str, actor: str, evidence_ref: str, at: datetime):
        with self.lock:
            prior = self._records[record_id][-1]
            record = KnowledgeRecord.model_validate({**prior.model_dump(), 'version': prior.version + 1,
                'status': 'revoked', 'confirmed_by': None, 'evidence_ref': evidence_ref,
                'valid_from': at, 'valid_until': None})
            return self._append(record, actor, 'revoke', at)

    def _selected(self, as_of):
        as_of = utc(as_of)
        return [max(eligible, key=lambda r: r.version) for history in self._records.values()
                if (eligible := [r for r in history if r.valid_from <= as_of])]

    def list_impact(self, product_id: str, changed_fields: list[str], as_of: datetime):
        with self.lock:
            selected = self._selected(as_of)
            usages = {r.record_id: r for r in selected if r.kind == 'usage' and r.data['product_id'] == product_id
                      and (not changed_fields or set(changed_fields) & set(r.data['field_paths']))}
            return [{'usage': r.model_dump(mode='json'), 'obligations': [o.model_dump(mode='json')
                     for o in selected if o.kind == 'obligation' and o.data['usage_ref'] == r.record_id]}
                    for r in sorted(usages.values(), key=lambda r: r.record_id)]

    def build_snapshot(self, proposal_id: str, old: DataContract, new: DataContract, as_of: datetime):
        with self.lock:
            if old.product_id != new.product_id or old.contract_version == new.contract_version or old.owner_domain != new.owner_domain:
                raise ValueError('invalid contract change')
            as_of = utc(as_of)
            all_records = self._selected(as_of)
            usages = {r.record_id for r in all_records if r.kind == 'usage' and r.data['product_id'] == new.product_id}
            records = [r for r in all_records if r.data.get('product_id') == new.product_id
                       or (r.kind == 'obligation' and (r.data['usage_ref'] in usages or r.data['requirement']['product_id'] == new.product_id))]
            team_ids = {r.data[k] for r in records for k in ('producer_team_ref', 'consumer_team_ref') if k in r.data}
            records += [r for r in all_records if r.kind == 'team' and r.record_id in team_ids]
            records = sorted(records, key=lambda r: (r.record_id, r.version))
            issues = []
            by_id = {r.record_id: r for r in records}
            for r in records:
                if r.status != 'confirmed': issues.append(f'{r.status}:{r.record_id}')
                if r.valid_until and r.valid_until <= as_of: issues.append(f'expired:{r.record_id}')
                if r.status == 'confirmed' and not self._authorized(r.confirmed_by, r.owner_domain, r.kind):
                    issues.append(f'unauthorized:{r.record_id}')
            coverage = [r for r in records if r.kind == 'coverage']
            members = sorted(coverage[0].data['registered_consumer_ids']) if len(coverage) == 1 else []
            if len(coverage) != 1: issues.append('coverage_missing_or_conflicting')
            products = [r for r in records if r.kind == 'product']
            if len(products) != 1 or products[0].data['contract'] != old.model_dump(mode='json'):
                issues.append('old_contract_unconfirmed_or_conflicting')
            for r in records:
                grant = self._authorized(r.confirmed_by, r.owner_domain, r.kind)
                if r.kind in ('team', 'coverage') and grant and r.data['authority_ref'] != grant.authority_ref:
                    issues.append(f'authority_ref_mismatch:{r.record_id}')
                if r.kind == 'team' and r.data['domain_id'] != r.owner_domain:
                    issues.append(f'team_domain_mismatch:{r.record_id}')
                if r.kind == 'product' and (r.data['contract']['product_id'] != new.product_id or r.data['contract']['owner_domain'] != r.owner_domain):
                    issues.append(f'product_owner_mismatch:{r.record_id}')
                if r.kind == 'attribute' and r.owner_domain != old.owner_domain:
                    issues.append(f'attribute_owner_mismatch:{r.record_id}')
                if r.kind == 'obligation' and (r.data['usage_ref'] not in by_id or by_id[r.data['usage_ref']].kind != 'usage'):
                    issues.append(f'dangling_usage:{r.record_id}')
                if r.kind == 'global_rule' and r.data['predicate']['product_id'] != new.product_id:
                    issues.append(f'rule_product_mismatch:{r.record_id}')
                if r.kind in ('product', 'usage'):
                    key = 'producer_team_ref' if r.kind == 'product' else 'consumer_team_ref'
                    team = by_id.get(r.data[key])
                    if not team or team.kind != 'team' or team.data['domain_id'] != r.owner_domain or team.owner_domain != r.owner_domain:
                        issues.append(f'team_authority_mismatch:{r.record_id}')
                if r.kind == 'attribute' and (r.data['field_path'] not in old.schema_fields or r.data['contract_version'] != old.contract_version):
                    issues.append(f'attribute_contract_mismatch:{r.record_id}')
            attrs = {r.data['field_path'] for r in records if r.kind == 'attribute'}
            for member in members:
                active = [r for r in records if r.kind == 'usage' and r.data['consumer_id'] == member and r.data['active']]
                if len(active) != 1:
                    issues.append(f'usage_missing_or_conflicting:{member}')
                    continue
                usage = active[0]
                if not set(usage.data['field_paths']) <= attrs: issues.append(f'attribute_missing:{member}')
                obligations = [r for r in records if r.kind == 'obligation' and r.data['usage_ref'] == usage.record_id and r.data['mandatory']]
                if not obligations: issues.append(f'obligation_missing:{member}')
                ids = [r.data['requirement']['obligation_id'] for r in obligations]
                if len(ids) != len(set(ids)): issues.append(f'obligation_conflicting:{member}')
                for r in obligations:
                    req = r.data['requirement']
                    if req['consumer_id'] != member or req['consumer_domain'] != usage.owner_domain or r.owner_domain != usage.owner_domain or req['product_id'] != new.product_id:
                        issues.append(f'obligation_link_mismatch:{r.record_id}')
            active_members = {r.data['consumer_id'] for r in records if r.kind == 'usage' and r.data['active']}
            if active_members != set(members): issues.append('registration_usage_mismatch')
            constitutions = [r for r in records if r.kind == 'constitution']
            if len(constitutions) != 1: issues.append('constitution_missing_or_conflicting')
            rules = [r.data['rule_id'] for r in records if r.kind == 'global_rule']
            if len(rules) != len(set(rules)): issues.append('global_rule_conflict')
            obligation_ids = [r.data['requirement']['obligation_id'] for r in records if r.kind == 'obligation']
            if len(obligation_ids) != len(set(obligation_ids)): issues.append('obligation_identity_conflict')
            payload = dict(schema_version='knowledge-1', proposal_id=proposal_id, product_id=new.product_id,
                as_of=as_of.isoformat().replace('+00:00', 'Z'), membership_epoch=coverage[0].data['membership_epoch'] if len(coverage) == 1 else None,
                old_contract=old.model_dump(mode='json'), new_contract=new.model_dump(mode='json'), required_consumer_ids=members,
                records=[r.model_dump(mode='json') for r in records], completeness='complete' if not issues else ('unknown' if len(coverage) != 1 else 'incomplete'),
                issues=sorted(set(issues)), record_hashes={f'{r.record_id}@{r.version}': digest(r.model_dump(mode='json')) for r in records})
            sid = digest(payload)
            snapshot = KnowledgeSnapshot(snapshot_id=sid, canonical_payload_hash=sid, **payload)
            snapshot.verify()
            self._snapshots[sid] = snapshot
            self._persist()
            return snapshot.model_copy(deep=True)

    def resolve_snapshot(self, snapshot_id: str):
        with self.lock:
            snapshot = self._snapshots[snapshot_id].model_copy(deep=True)
            snapshot.verify()
            return snapshot

    def is_current(self, snapshot: KnowledgeSnapshot, at: datetime):
        current = self.build_snapshot(snapshot.proposal_id, snapshot.old_contract, snapshot.new_contract, at)
        return current.record_hashes == snapshot.record_hashes and current.completeness == snapshot.completeness

    def _persist(self):
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {'records': [r.model_dump(mode='json') for h in self._records.values() for r in h],
                       'snapshots': [s.model_dump(mode='json') for s in self._snapshots.values()], 'events': self._events}
            temp = self.path.with_suffix(self.path.suffix + '.tmp')
            temp.write_text(canonical(payload), encoding='utf-8')
            temp.replace(self.path)

    def _restore(self, payload):
        for raw in payload['records']:
            r = KnowledgeRecord.model_validate(raw)
            history = self._records.setdefault(r.record_id, [])
            if r.version != len(history) + 1: raise ValueError('corrupt version history')
            history.append(r)
        self._events = payload['events']
        records = {(r.record_id, r.version): r for h in self._records.values() for r in h}
        if len(self._events) != len(records): raise ValueError('incomplete event ledger')
        previous = None
        for e in self._events:
            r = records[(e['record_id'], e['version'])]
            grant = self._authorized(e['actor'], r.owner_domain, r.kind)
            if not grant or grant.authority_ref != e['authority_ref'] or e['previous_hash'] != previous or e['record_hash'] != digest(r.model_dump(mode='json')):
                raise ValueError('invalid ledger authority or integrity')
            previous = digest(e)
        for raw in payload['snapshots']:
            s = KnowledgeSnapshot.model_validate(raw)
            s.verify()
            for r in s.records:
                if digest(records[(r.record_id, r.version)].model_dump(mode='json')) != s.record_hashes[f'{r.record_id}@{r.version}']:
                    raise ValueError('snapshot not anchored to ledger')
            self._snapshots[s.snapshot_id] = s
