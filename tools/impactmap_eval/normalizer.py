"""Bind addressed raw warnings without consulting truth or constructing a delta product."""
from __future__ import annotations
import json
import unicodedata
from agent_graph.output_contracts import parse_document
from .common import canonical,sha,pair,validate
from .operation_binding import OperationBindings

NORMALIZATION_VERSION = "impactmap-normalization-2"


def unbound(case_id,consumer,refs,*,mapped=True):
    name=' '.join(unicodedata.normalize('NFC',consumer).split())
    designation=('service:' if mapped else 'unmapped:')+name
    id=sha(json.dumps([case_id,designation,'UNBOUND'],ensure_ascii=False,separators=(',',':')).encode())
    return dict(candidate_id=id,consumer_designation=designation,raw_refs=sorted(set(refs)),reason='target_not_uniquely_bound')


def empty_prediction(case_id,method,configuration,raw_sha):
    return dict(schema_version='impactmap-normalized-prediction-1.0',lifecycle='complete',case_id=case_id,method=method,
        attempt=dict(id=1,kind='primary'),configuration_sha256=configuration,raw_artifact_sha256=raw_sha,
        output_valid=True,status='ABSTAINED',error_code=None,candidates=[],invalid_candidates=[],limitations=[],
        explicit_claims=dict(compatibility_confirmed=False,tests_executed=False,no_consumers=False))


def normalize_core(raw,case,registry,*,configuration,raw_sha=None):
    p=empty_prediction(case['case_id'],'impactmap_static',configuration,raw_sha or sha(json.dumps(raw,ensure_ascii=False,allow_nan=True).encode()))
    try:parse_document(raw)
    except Exception:p['output_valid']=False;p['error_code']='invalid_analysis_document'
    if not isinstance(raw,dict):p['status']='FAILED';return p
    p['status']=raw.get('status') if raw.get('status') in ('USEFUL','PARTIAL','ABSTAINED','FAILED','SUPERSEDED') else 'FAILED'
    def obj(value):return value if isinstance(value,dict) else {}
    def names(value):
        if isinstance(value,dict):return names(value.get('service'))
        if isinstance(value,str):return [value] if value.strip() else []
        if isinstance(value,list):return [name for item in value for name in names(item)]
        return []
    def refs_safe(value):return [x for x in value if isinstance(x,str)] if isinstance(value,list) else []
    for field in ('evidence','relationships','claims','findings','affected','checks','gaps','unknowns'):
        if not isinstance(raw.get(field,[]),list):raw={**raw,field:[]}
    evidence={e['id']:e for e in raw.get('evidence',[]) if isinstance(e,dict) and isinstance(e.get('id'),str)}
    rels={r['id']:r for r in raw.get('relationships',[]) if isinstance(r,dict) and r.get('kind')=='calls' and isinstance(r.get('id'),str)}
    claims={c['id']:c for c in raw.get('claims',[]) if isinstance(c,dict) and isinstance(c.get('id'),str)}
    bundles={};unbounds={};invalid_citations=set();seen_claims=set()
    # Inspect every structured citation and visibility entry, not just selected candidates.
    for ref,e in evidence.items():
        rid=e.get('repository')
        if rid is None:continue
        if not isinstance(rid,str):
            invalid_citations.add(ref)
            p['limitations'].append(dict(code='access_leak_detected',scope='/evidence/'+ref))
            continue
        known=rid in registry.repos
        visibility=refs_safe(e.get('visibility',[]))
        source_known=(not hasattr(registry,'sources') or any(k[0]==rid and k[2]==e.get('commit') and k[3]==e.get('path') for k in registry.sources))
        if not known or not source_known or any(v not in registry.repos for v in visibility):
            p['limitations'].append(dict(code='access_leak_detected',scope='/evidence/'+str(ref)))
    for kind in ('relationships',):
        for i,r in enumerate(raw.get(kind,[])):
            if isinstance(r,dict) and any(v not in registry.repos for v in refs_safe(r.get('visibility',[]))):
                p['limitations'].append(dict(code='access_leak_detected',scope=f'/{kind}/{i}/visibility'))
    bindings=OperationBindings(raw,registry)
    consumer_refs=bindings.consumer_refs
    def witnesses(refs,consumer):
        result={}
        for ref in consumer_refs(refs,consumer):
            if not bindings.valid_evidence(ref):
                invalid_citations.add(ref);continue
            e=evidence[ref];source=None;phase=None
            for key,s in getattr(registry,'sources',{}).items():
                if key[0]==e.get('repository') and key[2]==e.get('commit') and key[3]==e.get('path'):
                    source=s;phase=key[1]
                    if phase=='head':break
            if not source or source['sha256']!=e.get('content_sha256'):
                invalid_citations.add(ref);continue
            try:w=registry.witness(e['repository'],phase,e['commit'],e['path'],e['start_line'],e['end_line'])
            except (ValueError,KeyError,TypeError):invalid_citations.add(ref);continue
            result[canonical(w)]=w
        return list(result.values())
    def add(consumer,operation,refs,rawref):
        if not isinstance(consumer,str) or not consumer.strip():return
        keys=set()
        if operation is not None:
            try:keys.add(pair(dict(provider_service=operation['service'],method=operation['method'],route=operation['route'],consumer_service=consumer)))
            except (KeyError,TypeError,ValueError):pass
        if len(keys)!=1:
            p['limitations'].append(dict(code='manual_claim_audit_required',scope=rawref))
            bucket=unbound(case['case_id'],consumer,[rawref],mapped=consumer in {r['service'] for r in registry.repos.values()});old=unbounds.setdefault(bucket['consumer_designation'],bucket)
            old['raw_refs']=sorted(set(old['raw_refs']+[rawref]));return
        k=next(iter(keys));b=bundles.setdefault(k,dict(key=dict(zip(('provider_service','method','route','consumer_service'),k)),witnesses=[],raw_refs=[],notes='All formulations retained in raw artifact; no gold-based filtering.'))
        b['raw_refs']=sorted(set(b['raw_refs']+[rawref]));allw={canonical(w):w for w in b['witnesses']+witnesses(refs,consumer)};b['witnesses']=list(allw.values())
    for i,f in enumerate(raw.get('findings',[])):
        if not isinstance(f,dict):continue
        refs=refs_safe(f.get('evidence_refs',[]))
        for consumer in names(f.get('consumer')):
            for operation,support in bindings.resolve(consumer,refs,callsite=f.get('callsite')):
                add(consumer,operation,list(support),f'/findings/{i}')
        for flag in p['explicit_claims']:
            if f.get('test_executed' if flag=='tests_executed' else flag) is True:p['explicit_claims'][flag]=True
    for i,a in enumerate(raw.get('affected',[])):
        if not isinstance(a,dict):continue
        for consumer in names(a.get('service')):
            relationship_refs=refs_safe(a.get('relationship_refs',[]))
            if not relationship_refs:add(consumer,None,[],f'/affected/{i}')
            for ref in relationship_refs:
                rel=rels.get(ref)
                for operation,support in bindings.resolve(consumer,rel.get('evidence_refs',[]) if rel else [],relationship_ids=[ref],split=True):
                    add(consumer,operation,list(support),f'/affected/{i}/{ref}')
    for i,c in enumerate(raw.get('checks',[])):
        if not isinstance(c,dict):continue
        refs=[]
        ids=refs_safe(c.get('claim_refs'));consumers=names(c.get('consumer'))
        for id in ids:
            if consumers:seen_claims.add(id)
            refs+=refs_safe(claims.get(id,{}).get('evidence_refs',[]))
        for consumer in consumers:
            for operation,support in bindings.resolve(consumer,refs,claim_ids=ids):
                add(consumer,operation,list(support),f'/checks/{i}')
    for i,c in enumerate(raw.get('claims',[])):
        if not isinstance(c,dict) or c.get('id') in seen_claims:continue
        refs=refs_safe(c.get('evidence_refs',[]));consumers=bindings.consumers
        bound=False
        for consumer in consumers:
            if consumer_refs(refs,consumer):
                for operation,support in bindings.resolve(consumer,refs,claim_ids=[c.get('id')]):
                    add(consumer,operation,list(support),f'/claims/{i}')
                bound=True
        if not bound and obj(c.get('subject')).get('kind')=='service':
            for consumer in names(c.get('subject')):add(consumer,None,refs,f'/claims/{i}')
        if not bound and c.get('kind')=='hypothesis':
            p['limitations'].append(dict(code='manual_claim_audit_required',scope=f'/claims/{i}'))
    for g in raw.get('gaps',[])+raw.get('unknowns',[]):
        if isinstance(g,dict) and g.get('code'):
            p['limitations'].append(dict(code=g['code'],scope=str(g.get('repository') or g.get('subject') or 'analysis')[:200]))
    invalid_citations.update(bindings.invalid_refs)
    for ref in sorted(invalid_citations):p['limitations'].append(dict(code='invalid_citation',scope=ref))
    p['candidates']=[bundles[k] for k in sorted(bundles)];p['invalid_candidates']=[unbounds[k] for k in sorted(unbounds)]
    validate('normalized-prediction',p);return p
