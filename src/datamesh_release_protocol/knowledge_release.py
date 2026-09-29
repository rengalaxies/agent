"""V2 release over authoritative snapshots, with commit-time fencing."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from .engine import finalize
from .interpreter import TypedObligationInterpreter
from .validators import _schema_checks
from .knowledge import KnowledgeSnapshot, KnowledgeStore, digest, utc
from .models import Decision, Migration, StrictModel


class MappedRelease(StrictModel):
    proposal_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    decision: Decision
    terminal_state: Literal['COMMITTED', 'QUARANTINED', 'ESCALATED', 'ABORTED', 'ALREADY_COMMITTED']
    release_id: str | None = None
    reasons: list[str]
    evidence: list[dict[str, Any]]
    state_trace: list[str]
    contract_change: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode='after')
    def consistent_terminal(self):
        if not self.state_trace or self.state_trace[-1] != self.terminal_state:
            raise ValueError('invalid terminal trace')
        if self.terminal_state in ('COMMITTED', 'ALREADY_COMMITTED'):
            if self.decision != Decision.ACCEPT or not self.release_id:
                raise ValueError('release requires ACCEPT and release_id')
        elif self.release_id is not None:
            raise ValueError('noncommitted result cannot authorize publication')
        if self.terminal_state == 'QUARANTINED' and self.decision != Decision.REJECT:
            raise ValueError('quarantine requires REJECT')
        if self.terminal_state == 'ESCALATED' and self.decision != Decision.NEEDS_REVIEW:
            raise ValueError('escalation requires NEEDS_REVIEW')
        return self

    def producer_view(self):
        return {'proposal_id': self.proposal_id, 'run_id': self.run_id, 'decision': self.decision.value,
                'state': self.terminal_state, 'release_id': self.release_id,
                'snapshot_id': self.snapshot_id, 'reasons': list(self.reasons),
                'explanations':[explain_reason(code) for code in self.reasons],
                'contract_change':self.contract_change, 'affected': [dict(e) for e in self.evidence]}

    def consumer_view(self, consumer_id):
        return {**self.producer_view(), 'affected': [e for e in self.evidence if e.get('consumer_id') == consumer_id]}


def request_fingerprint(snapshot_id, migrations):
    from .models import Migration
    payloads = [Migration.model_validate(m).model_dump(mode='json') if isinstance(m, dict)
                else m.model_dump(mode='json') for m in migrations]
    return digest({'snapshot':snapshot_id, 'migrations':payloads})


def change_key(snapshot):
    return digest({'product_id':snapshot.product_id,
        'old_contract':snapshot.old_contract.model_dump(mode='json'),
        'new_contract':snapshot.new_contract.model_dump(mode='json')})


def target_key(snapshot):
    return digest({'product_id':snapshot.product_id, 'version':snapshot.new_contract.contract_version})


def evaluate_snapshot(snapshot, migrations):
    decisions, evidence = [], []
    from .models import ConsumerObligation
    for r in snapshot.records:
        if r.status != 'confirmed' or (r.valid_until and r.valid_until <= snapshot.as_of):
            continue
        if r.kind == 'obligation' and r.data['mandatory']:
            requirement = ConsumerObligation.model_validate(r.data['requirement'])
        elif r.kind == 'global_rule':
            requirement = ConsumerObligation.model_validate(r.data['predicate'])
        else:
            continue
        # Invalid link/authority cannot supply a semantic proof.
        linked_ids = {r.record_id}
        if r.kind == 'obligation':
            usage_record = next((u for u in snapshot.records if u.record_id == r.data['usage_ref'] and u.kind == 'usage'), None)
            if not usage_record or not usage_record.data['active']: continue
            linked_ids.update([usage_record.record_id, usage_record.data['consumer_team_ref'], requirement.consumer_id])
            linked_ids.update(u.record_id for u in snapshot.records if u.kind == 'attribute'
                              and u.data['field_path'] in usage_record.data['field_paths'])
        if any(any(issue.endswith(':' + rid) for rid in linked_ids) for issue in snapshot.issues) or (r.kind == 'global_rule' and 'global_rule_conflict' in snapshot.issues) or (r.kind == 'obligation' and any(issue in snapshot.issues for issue in ('obligation_identity_conflict','attribute_identity_conflict'))):
            continue
        checks = _schema_checks(snapshot.old_contract, snapshot.new_contract) + TypedObligationInterpreter().evaluate(snapshot.new_contract, requirement, migrations)
        outcome = Decision.REJECT if any(c.outcome == 'FALSE' for c in checks) else (
            Decision.NEEDS_REVIEW if any(c.outcome == 'UNKNOWN' for c in checks) else Decision.ACCEPT)
        decisions.append(outcome)
        usages = {u.record_id: u for u in snapshot.records if u.kind == 'usage'}
        usage = usages.get(r.data.get('usage_ref'))
        evidence.append({'consumer_id': requirement.consumer_id, 'domain_id': requirement.consumer_domain,
            'obligation_id': requirement.obligation_id, 'obligation_version': requirement.obligation_version,
            'record_ref': f'{r.record_id}@{r.version}', 'evidence_ref': r.evidence_ref,
            'field_paths': usage.data['field_paths'] if usage else [], 'decision': outcome.value,
            'checks': [c.model_dump(mode='json') for c in checks]})
    if snapshot.completeness != 'complete': decisions.append(Decision.NEEDS_REVIEW)
    # Explicitly confirmed zero-consumer boundary is legitimate, unlike missing coverage.
    if not decisions and snapshot.completeness == 'complete' and not snapshot.required_consumer_ids:
        schema = _schema_checks(snapshot.old_contract, snapshot.new_contract)
        decisions.append(Decision.REJECT if any(c.outcome == 'FALSE' for c in schema) else Decision.ACCEPT)
    decision = finalize(decisions)
    return decision, sorted(evidence, key=lambda e: e["record_ref"])


def build_release(store, snapshot, run_id, at, migrations):
    decision, evidence = evaluate_snapshot(snapshot, migrations)
    current = store.is_current(snapshot, at)
    state = 'ABORTED' if not current else {Decision.ACCEPT: 'COMMITTED', Decision.REJECT: 'QUARANTINED', Decision.NEEDS_REVIEW: 'ESCALATED'}[decision]
    reasons = sorted(set(snapshot.issues + [c['reason_code'] for e in evidence for c in e['checks'] if c['outcome'] != 'TRUE'] + ([] if current else ['snapshot_changed_before_commit'])))
    key = change_key(snapshot)
    target = target_key(snapshot)
    if state == 'COMMITTED' and target in store._release_targets and store._release_targets[target] != key:
        state = 'ABORTED'
        reasons = sorted(set(reasons + ['target_version_already_authorized_with_different_content']))
    if state == 'COMMITTED' and key in store._release_commits:
        state = 'ALREADY_COMMITTED'
        reasons = sorted(set(reasons + ['change_already_authorized']))
    result = MappedRelease(proposal_id=snapshot.proposal_id, run_id=run_id, snapshot_id=snapshot.snapshot_id,
        decision=decision, terminal_state=state,
        release_id=key if state in ('COMMITTED','ALREADY_COMMITTED') else None,
        reasons=reasons, evidence=sorted(evidence, key=lambda e: e['record_ref']),
        state_trace=['RECEIVED', 'SNAPSHOT_LOCKED', 'LOCALLY_VALIDATED', 'DECIDED', state],
        contract_change={'old_contract':snapshot.old_contract.model_dump(mode='json'),
            'new_contract':snapshot.new_contract.model_dump(mode='json')})
    return result


class KnowledgeReleaseEngine:
    """Research release ledger; durable map, single-process release coordinator.

    Terminal decisions and unique release authorizations survive restarts.
    External publishers must deduplicate release_id; publication is not executed here.
    """
    def __init__(self, store: KnowledgeStore):
        self.store = store


    def run(self, snapshot_id: str, run_id: str, at: datetime, migrations: list[Migration] | None = None):
        with self.store.lock:
            snapshot = self.store.resolve_snapshot(snapshot_id)
            at = utc(at)
            if at < snapshot.as_of:
                raise ValueError('commit precedes snapshot')
            migrations = migrations or []
            fingerprint = request_fingerprint(snapshot_id, migrations)
            if run_id in self.store._release_runs:
                prior = self.store._release_runs[run_id]
                if prior['fingerprint'] != fingerprint: raise ValueError('run_id reused with conflicting payload')
                return MappedRelease.model_validate(prior['result'])
            result = build_release(self.store, snapshot, run_id, at, migrations)
            self.store._save_release_event({'kind':'decision', 'fingerprint':fingerprint,
                'migrations':[m.model_dump(mode='json') for m in migrations], 'at':at.isoformat(),
                'result':result.model_dump(mode='json')})
            return result.model_copy(deep=True)


def explain_reason(code):
    prefix, _, detail = code.partition(':')
    meanings = {
        'SCHEMA_BREAKING':'Изменение удаляет поле или меняет его тип несовместимым образом',
        'V2_REQUIRED_MEANING':'Не соблюдено требование к бизнес-смыслу',
        'V2_REQUIRED_FORMULA':'Не соблюдено требование к формуле расчёта',
        'V2_CONSUMER_UNIT_SCALE':'Не соблюдено требование к единице или масштабу',
        'V2_CONSUMER_MIN_WINDOW':'Не соблюдено требование к окну расчёта',
        'V2_CONSUMER_IDENTITY_SCOPE':'Не соблюдено требование к области идентификации',
        'V2_CONSUMER_ALLOWED_SOURCES':'Не соблюдено ограничение на источники',
        'V2_CONSUMER_REQUIRED_PURPOSES':'Не соблюдено требование к назначению использования',
        'V2_EMPTY_OBLIGATION':'Нет формализованного условия для проверки',
        'candidate':'Запись ещё не подтверждена владельцем',
        'revoked':'Запись отозвана', 'expired':'Срок действия записи истёк',
        'attribute_missing':'Нет действительных записей используемых атрибутов',
        'obligation_missing':'Нет обязательного требования потребителя',
        'dangling_usage':'Требование ссылается на отсутствующее использование',
        'obligation_link_mismatch':'Владелец, потребитель или продукт требования не согласованы',
        'coverage_missing_or_conflicting':'Состав зарегистрированных потребителей неизвестен или неоднозначен',
        'registration_usage_mismatch':'Реестр участников и активные использования расходятся',
        'snapshot_changed_before_commit':'Контекст изменился или истёк после фиксации снимка',
        'change_already_authorized':'Это изменение уже получило разрешение; новое разрешение не создаётся',
        'target_version_already_authorized_with_different_content':'Эта версия уже получила разрешение с другим содержимым',
        'obligation_identity_conflict':'Идентификатор требования неоднозначен',
        'attribute_identity_conflict':'Атрибут имеет конфликтующие записи',
    }
    return {'reason_code':code, 'message':meanings.get(prefix, 'Результат проверки: ' + prefix),
            'reference':detail or None}
