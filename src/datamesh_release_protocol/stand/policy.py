"""Transport-free finalization of signed domain verdicts, without oracle labels."""
from ..engine import finalize
from ..knowledge_release import MappedRelease, change_key, target_key, request_fingerprint
from ..models import Decision
from ..knowledge import digest
from .protocol import SignedMessage, verify, required_domains, revision, owned_records


def project(snapshot,run_id,migrations,messages,public_keys,routes,deadline_expired):
    snapshot.verify()
    required=required_domains(snapshot,routes)
    groups={d:{} for d in required};fences={d:{} for d in required}
    reasons=set();abort=False
    for raw in messages:
        try:
            msg=SignedMessage.model_validate(raw);v=msg.vote
            verify(msg,public_keys[v.domain_id])
            if v.event_id!=digest(v.model_dump(mode='json',exclude={'event_id'})):
                abort=True;reasons.add('signed_event_integrity_failure');raise ValueError('event_id differs from content')
            if (v.domain_id not in groups or v.run_id!=run_id or v.proposal_id!=snapshot.proposal_id or
                v.snapshot_id!=snapshot.snapshot_id or v.request_fingerprint!=request_fingerprint(snapshot.snapshot_id,migrations) or
                v.membership_epoch!=snapshot.membership_epoch or v.old_contract_version!=snapshot.old_contract.contract_version or
                v.new_contract_version!=snapshot.new_contract.contract_version):
                raise ValueError('wrong event binding')
            expected_revision=revision(owned_records(snapshot,v.domain_id,routes))
            if v.revision!=expected_revision: abort=True;reasons.add('local_revision_changed:'+v.domain_id)
            if v.kind=='VERDICT':
                if v.decision is None: raise ValueError('missing decision')
                consumers={r.data['requirement']['consumer_id'] for r in snapshot.records if r.kind=='obligation' and routes[r.owner_domain]==v.domain_id}
                rule_consumers={r.data['predicate']['consumer_id'] for r in snapshot.records if r.kind=='global_rule' and routes[r.owner_domain]==v.domain_id}
                if any(e['consumer_id'] not in consumers|rule_consumers for e in v.evidence):raise ValueError('foreign consumer evidence')
                check_outcomes=[c['outcome'] for e in v.evidence for c in e['checks']]
                if v.decision==Decision.ACCEPT and (any(x!='TRUE' for x in check_outcomes) or v.issues):raise ValueError('accept contradicts evidence')
                if v.decision==Decision.REJECT and not any(x=='FALSE' for x in check_outcomes):
                    # Producer with no obligations can independently reject a schema break.
                    if not v.issues or 'SCHEMA_BREAKING' not in v.issues:raise ValueError('reject without evidence')
                groups[v.domain_id][v.event_id]=v
            else:
                if v.decision is not None or v.evidence:raise ValueError('invalid fence')
                fences[v.domain_id][v.event_id]=v
        except Exception:
            reasons.add('invalid_event_ignored')
    decisions=[];evidence=[];missing=[];conflicts=[]
    for domain in required:
        # Retransmission with another request_id remains the same semantic response.
        semantic={str((v.decision,v.revision,repr(v.evidence),repr(v.issues))) for v in groups[domain].values()}
        if len(semantic)>1:
            conflicts.append(domain);reasons.add('conflicting_domain_verdict:'+domain);continue
        if not semantic:missing.append(domain);continue
        v=next(iter(groups[domain].values()))
        decisions.append(v.decision);evidence.extend(v.evidence);reasons.update(v.issues)
        reasons.update(c['reason_code'] for e in v.evidence for c in e['checks'] if c['outcome']!='TRUE')
    if missing or conflicts or snapshot.completeness!='complete':decisions.append(Decision.NEEDS_REVIEW)
    reasons.update(snapshot.issues)
    if missing:reasons.update('missing_domain:'+d for d in missing)
    if conflicts:decisions.append(Decision.NEEDS_REVIEW)
    decision=finalize(decisions)
    if decision==Decision.ACCEPT:
        for domain in required:
            if not fences[domain]:decisions.append(Decision.NEEDS_REVIEW);reasons.add('missing_fence:'+domain)
            elif len({v.revision for v in fences[domain].values()})>1:abort=True;reasons.add('conflicting_fence:'+domain)
        decision=finalize(decisions)
    if missing and deadline_expired:reasons.add('deadline_expired')
    return {'decision':decision,'evidence':sorted(evidence,key=lambda e:e['record_ref']),
        'reasons':sorted(reasons),'abort':abort,'missing':missing,'conflicts':conflicts,'required_domains':required}


def build_distributed_release(store,snapshot,run_id,at,migrations,messages,deadline_expired):
    projection=project(snapshot,run_id,migrations,messages,store.domain_public_keys,store.domain_routes,deadline_expired)
    decision=projection['decision'];reasons=projection['reasons']
    state={Decision.ACCEPT:'COMMITTED',Decision.REJECT:'QUARANTINED',Decision.NEEDS_REVIEW:'ESCALATED'}[decision]
    if projection['abort'] or not store.is_current(snapshot,at):
        state='ABORTED';reasons=sorted(set(reasons+['snapshot_or_domain_changed_before_commit']))
    key=change_key(snapshot);target=target_key(snapshot)
    if state=='COMMITTED' and target in store._release_targets and store._release_targets[target]!=key:
        state='ABORTED';reasons=sorted(set(reasons+['target_version_already_authorized_with_different_content']))
    if state=='COMMITTED' and key in store._release_commits:
        state='ALREADY_COMMITTED';reasons=sorted(set(reasons+['change_already_authorized']))
    return MappedRelease(proposal_id=snapshot.proposal_id,run_id=run_id,snapshot_id=snapshot.snapshot_id,
        decision=decision,terminal_state=state,release_id=key if state in ('COMMITTED','ALREADY_COMMITTED') else None,
        reasons=reasons,evidence=projection['evidence'],state_trace=['RECEIVED','SNAPSHOT_LOCKED','DOMAIN_VERDICTS_COLLECTED','DECIDED',state],
        contract_change={'old_contract':snapshot.old_contract.model_dump(mode='json'),'new_contract':snapshot.new_contract.model_dump(mode='json')})
