"""Publish only this investigation's authorized, current, unapproved hypotheses.

No model statement becomes an affected service, a relationship or a finding.
Evidence is resolved from the current core context, never from model text.
"""
from agent_graph.contracts import GraphError, digest
from agent_graph.output_contracts import ContractError, dump_document, parse_document


def append_model_hypotheses(document, graph, context, investigation):
    if (not investigation or investigation.get('context_id') != context['id']
            or document['status'] not in ('USEFUL', 'PARTIAL')):
        return document
    wanted = set(investigation.get('hypothesis_ids', []))
    if not wanted:
        return document
    rows = {r['id']: r for r in graph.proposals(context)}
    evidence = {e['id']: e for e in document['evidence']}
    for candidate in sorted(wanted):
        row = rows.get(candidate)
        if (row is None or row['status'] != 'CURRENT' or row.get('origin') != 'model'
                or row['context_id'] != context['id'] or row['proposal']['kind'] != 'hypothesis'
                or row['trust'] != 'UNAPPROVED_CANDIDATE'):
            continue
        citations = row['proposal']['citations']
        try:
            for citation in citations:
                graph.get_evidence(context['id'], citation)
        except GraphError:
            continue
        supporting, pending = [], {}
        checked = row['freshness']['assessed_at']
        for citation in citations:
            source = context['sources'][citation['source_id']]
            eid = 'ev:' + digest([citation['source_id'], citation['start_line'], citation['end_line']])[:40]
            pinned = source.get('snapshot') == 'GIT_COMMIT'
            pending[eid] = dict(id=eid, origin='code', provenance='AUTHENTIC',
                sufficiency='SUPPORTED_WITHIN_PROFILE', freshness=dict(status='CURRENT', checked_at=checked,
                    reasons=[] if pinned else ['worktree_not_reproducible']),
                visibility=[source['repository']], snapshot='GIT_COMMIT' if pinned else 'WORKTREE',
                repository=source['repository'], commit=source.get('commit') if pinned else None,
                blob=source.get('blob') if pinned else None, content_sha256=source['sha256'], path=source['path'],
                start_line=citation['start_line'], end_line=citation['end_line'])
            supporting.append(eid)
        eid = 'hyp:' + candidate[:40]
        pending[eid] = dict(id=eid, origin='model_hypothesis', provenance='AUTHENTIC',
            sufficiency='NOT_ASSESSED', freshness=dict(status='CURRENT', checked_at=checked),
            visibility=sorted({e['repository'] for e in pending.values()}),
            model_configuration_id=investigation['configuration_id'], supporting_refs=sorted(set(supporting)),
            unknowns=['model_hypothesis_unverified'])
        statement = row['proposal']['statement']
        claim = dict(id='claim:' + digest(['hypothesis', statement, [eid]])[:40], kind='hypothesis',
            statement=statement, evidence_refs=[eid], uncertainty='HIGH',
            applicability='Model candidate; never promoted automatically.', unknowns=['model_hypothesis_unverified'])
        if claim['id'] not in {c['id'] for c in document['claims']}:
            # Validate each addition atomically: optional model work must not destroy
            # an already valid deterministic result when contract capacity is exhausted.
            trial = {**document, 'claims': [*document['claims'], claim],
                     'evidence': list((evidence | pending).values())}
            unknown = dict(code='model_hypothesis_unverified', subject=None)
            if unknown not in document['unknowns']:
                trial['unknowns'] = [*document['unknowns'], unknown]
            try:
                validated = dump_document(parse_document(trial))
            except ContractError:
                continue
            document = validated
            evidence = {e['id']: e for e in document['evidence']}
    return document


def model_use(investigation):
    """ModelUse and Costs of a constitution run; unknown token counts stay None, never zero."""
    if investigation is None:
        return None, {"model_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "reserved_micro": None,
                      "currency": None}
    usage = [e.get("usage") or {} for e in investigation.get("events", [])]
    transport_failures = sum(d.get("layer") == "transport" for d in investigation.get("diagnostics", []))
    def tokens(field):
        if transport_failures or any(type(u.get(field)) is not int for u in usage):
            return None
        return sum(u[field] for u in usage)
    model = {"configuration_id": investigation["configuration_id"], "model": investigation["model"],
             "protocol": investigation["protocol"]}
    return model, {"model_calls": len(usage) + transport_failures,
                   "prompt_tokens": tokens("prompt_tokens"),
                   "completion_tokens": tokens("completion_tokens"),
                   "reserved_micro": investigation.get("budget", {}).get("reserved_micro"), "currency": None}

