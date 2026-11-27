"""Curator-side strict scoring. Never imported by method worker; no system calls."""
from __future__ import annotations
from collections import Counter,defaultdict
import hashlib,json,unicodedata
from .common import canonical,pair,validate


def metrics(counts):
    t,f,n=counts['tp'],counts['fp'],counts['fn']
    return dict(precision=t/(t+f) if t+f else None,recall=t/(t+n) if t+n else None,
                f1=2*t/(2*t+f+n) if 2*t+f+n else None)


def _inside(w,accepted):
    return (all(w[k]==accepted[k] for k in ('repository','phase','commit','path'))
            and accepted['line_start']<=w['line_start']<=w['line_end']<=accepted['line_end'])


def score_case(prediction,reference,registry,*,development=False):
    validate('normalized-prediction',prediction);validate('reference-label',reference)
    if prediction['attempt']!={'id':1,'kind':'primary'}:raise ValueError('first_assigned_primary_required')
    if prediction['case_id']!=reference['case_id'] or prediction['lifecycle']!='complete':raise ValueError('case_or_lifecycle_mismatch')
    if not development:
        sources=reference['source_labels'];attest=reference['attestation']
        if (reference['lifecycle']!='complete' or reference['stage']!='adjudicated'
                or not attest['confirmed_by_human'] or not attest['independent_before_outputs']
                or len({s['expert_id'] for s in sources})<2):raise ValueError('independent_human_gold_required')
    usable=prediction['output_valid'] and prediction['status'] not in ('FAILED','SUPERSEDED') and prediction['error_code'] is None
    gold={pair(k['key']):k for k in reference['keys']}
    if len(gold)!=len(reference['keys']):raise ValueError('duplicate_gold_key')
    positive={k for k,v in gold.items() if v['label']=='AFFECTED'}
    unresolved=any(v['label']=='UNRESOLVED' for v in gold.values())
    bundles={};raw_count=0
    for candidate in prediction['candidates']:
        k=pair(candidate['key']);raw_count+=len(candidate['raw_refs'])
        b=bundles.setdefault(k,dict(witnesses={},refs=set()))
        for w in candidate['witnesses']:b['witnesses'][canonical(w)]=w
        b['refs'].update(candidate['raw_refs'])
    invalid=set();normalization_errors=[]
    for c in prediction['invalid_candidates']:
        parts=c['consumer_designation'].split(':',1)
        designation=parts[0]+':'+ ' '.join(unicodedata.normalize('NFC',parts[1]).split()) if len(parts)==2 else c['consumer_designation']
        expected=hashlib.sha256(json.dumps([prediction['case_id'],designation,'UNBOUND'],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        if designation!=c['consumer_designation'] or c['candidate_id']!=expected:normalization_errors.append('noncanonical_unbound_bucket')
        invalid.add(designation)
    if normalization_errors:usable=False;identity=set()
    observed_identity=set(bundles)&positive;identity=observed_identity if usable else set();matched=set();valid_citations=0;citation_count=0;gold_defect=any(not v['witnesses'] or any(not registry.valid(w) for w in v['witnesses']) for k,v in gold.items() if k in positive);unseen=[]
    details=[]
    for k,b in sorted(bundles.items()):
        accepted=gold.get(k,{}).get('witnesses',[])
        if k in positive and any(not registry.valid(w) for w in accepted):gold_defect=True
        good=[]
        for w in b['witnesses'].values():
            citation_count+=1
            valid=registry.valid(w) and registry.repos.get(w['repository'],{}).get('service')==k[3]
            valid_citations+=bool(valid)
            if valid and any(registry.valid(a) and _inside(w,a) for a in accepted):good.append(w)
        strict=bool(k in identity and good and usable)
        if strict:matched.add(k)
        if k not in gold and any(registry.valid(w) for w in b['witnesses'].values()):unseen.append(list(k))
        details.append(dict(key=list(k),identity_correct=k in identity,strict_match=strict,valid_witnesses=good,
                            all_witnesses=list(b['witnesses'].values()),raw_refs=sorted(b['refs'])))
    bad_refs={x['scope'] for x in prediction['limitations'] if x['code']=='invalid_citation'}
    citation_count+=len(bad_refs)
    strict=dict(tp=len(matched),fp=len(bundles)-len(matched)+len(invalid),fn=len(positive)-len(matched))
    technical=(bool(normalization_errors) or not prediction['output_valid'] or prediction['status'] in ('FAILED','SUPERSEDED') or prediction['error_code'] is not None)
    claims=prediction['explicit_claims']
    boundary_codes={
        'access':{'commit_unavailable','source_unavailable','object_unavailable','directory_unreadable'},
        'grammar':{'unknown_http_client','dynamic_or_unsupported_call','unsupported_url','ambiguous_mapping','openapi_ref_unsupported','dynamic_parameters','provider_route_unsupported'},
        'semantics':{'unclassified_change','helper_semantics_unknown','page_size_default_unresolved'},
        'none':set(),'unresolved':set()}
    actual_boundary=any(l['code'] in boundary_codes[reference['profile']['boundary']] for l in prediction['limitations'])
    limited=(prediction['output_valid'] and prediction['status'] in ('PARTIAL','ABSTAINED') and actual_boundary
             and not any(claims.values()) and not technical)
    leak=any(l['code']=='access_leak_detected' for l in prediction['limitations']) or any(w['repository'] not in registry.repos for b in bundles.values() for w in b['witnesses'].values())
    limited=limited and not leak
    return dict(case_id=prediction['case_id'],method=prediction['method'],
        primary_eligible=reference['profile']['membership']=='IN_PROFILE',
        strict=strict if reference['profile']['membership']=='IN_PROFILE' else None,
        identity=dict(tp=len(identity),fp=len(bundles)-len(identity)+len(invalid),fn=len(positive)-len(identity)) if reference['profile']['membership']=='IN_PROFILE' else None,
        gold_count=len(positive),predicted_count=len(bundles),unbound_count=len(invalid),
        duplicates=max(0,raw_count-len(bundles))+len(prediction['invalid_candidates'])-len(invalid),
        localization=dict(numerator=len(matched),denominator=len(identity)),
        citation_validity=dict(numerator=valid_citations,denominator=citation_count),
        status=prediction['status'],technical_error=technical,full_abstention=not bundles and not invalid,
        limited_result_success=limited,access_leak=leak,false_certainty=any(claims.values()),
        gold_audit_required=(bool(unseen) or gold_defect or unresolved) if reference['profile']['membership']=='IN_PROFILE' else False,
        unseen_keys=unseen,per_key=details,missing_gold_keys=[list(k) for k in sorted(positive-matched)],
        normalization_errors=normalization_errors,development=development,reference_profile=reference['profile'],search_complete=reference['scope_completeness']['search_complete'],
        manual_audit_required=any(l['code']=='manual_claim_audit_required' for l in prediction['limitations']))


def aggregate(records,catalogue):
    mapping={r['case_id']:r for r in catalogue}
    if len(mapping)!=len(catalogue) or len(records)!=len(mapping) or {r['case_id'] for r in records}!=set(mapping):
        raise ValueError('assigned_case_set_mismatch')
    if len({r['case_id'] for r in records})!=len(records):raise ValueError('duplicate_case_result')
    supported=[r for r in records if mapping[r['case_id']]['stratum']!='OUT_OF_PROFILE']
    negative=[r for r in supported if mapping[r['case_id']]['stratum'] in ('COMPATIBLE_IN_PROFILE','NO_CONSUMERS_IN_PROFILE')]
    outside=[r for r in records if mapping[r['case_id']]['stratum']=='OUT_OF_PROFILE']
    def sums(items,kind='strict'):return {k:sum(r[kind][k] for r in items if r[kind] is not None) for k in ('tp','fp','fn')}
    issues=[]
    quotas=Counter(mapping[r['case_id']]['stratum'] for r in records)
    if dict(quotas)!=dict(BREAKING_IN_PROFILE=20,COMPATIBLE_IN_PROFILE=10,NO_CONSUMERS_IN_PROFILE=4,OUT_OF_PROFILE=6):issues.append('catalogue_quotas')
    for r in records:
        stratum=mapping[r['case_id']]['stratum']
        if r['normalization_errors']:issues.append('normalization_contract:'+r['case_id'])
        if stratum!='OUT_OF_PROFILE' and (stratum=='BREAKING_IN_PROFILE')!=(r['gold_count']>0):issues.append('gold_stratum_mismatch:'+r['case_id'])
        if (stratum=='OUT_OF_PROFILE')!=(r['reference_profile']['membership']=='OUT_OF_PROFILE'):issues.append('profile_stratum_mismatch:'+r['case_id'])
        if stratum!='OUT_OF_PROFILE' and not r['search_complete']:issues.append('incomplete_gold_scope:'+r['case_id'])
    counts=sums(supported);identity=sums(supported,'identity')
    alerts=sum(r['predicted_count']+r['unbound_count']>0 for r in negative)
    groups=defaultdict(list);strata=defaultdict(list);provenance=defaultdict(list)
    for r in records:
        c=mapping[r['case_id']];groups[c['origin_group']].append(r);strata[c['stratum']].append(r);provenance[c['provenance']].append(r)
    loo=[]
    for group in groups:
        subset=[r for r in supported if mapping[r['case_id']]['origin_group']!=group]
        loo.append(dict(excluded_origin_group=group,**metrics(sums(subset))))
    proposed=(counts['tp']+counts['fn']>0 and counts['tp']+counts['fp']>0 and len(negative)>0
              and 10*counts['fn']<=counts['tp']+counts['fn'] and 17*counts['fp']<=3*counts['tp'] and 10*alerts<=len(negative))
    positives=[r for r in supported if mapping[r['case_id']]['stratum']=='BREAKING_IN_PROFILE']
    macro=[r['strict']['tp']/r['gold_count'] for r in positives if r['gold_count']]
    return dict(positive_case_hit=dict(numerator=sum(r['strict']['tp']>0 for r in positives),denominator=len(positives)),
        complete_positive_case=dict(numerator=sum(r['strict']['fn']==r['strict']['fp']==0 for r in positives),denominator=len(positives)),
        macro_recall_positive=sum(macro)/len(macro) if macro else None,macro_recall_defined_cases=len(macro),case_count=len(records),supported_cases=len(supported),outside_cases=len(outside),negative_cases=len(negative),
        strict=counts,**metrics(counts),identity=dict(counts=identity,**metrics(identity)),false_alert_cases=alerts,
        false_alert_case_rate=alerts/len(negative) if negative else None,
        technical_errors_supported=sum(r['technical_error'] for r in supported),technical_errors_all=sum(r['technical_error'] for r in records),
        full_abstentions=sum(r['full_abstention'] for r in records),partial=sum(r['status']=='PARTIAL' for r in records),
        outside_boundary_success=sum(r['limited_result_success'] for r in outside),
        access_leaks=sum(r['access_leak'] for r in records),false_certainty=sum(r['false_certainty'] for r in records),
        gold_audits=sum(r['gold_audit_required'] for r in records),manual_audits=sum(r['manual_audit_required'] for r in records),protocol_issues=issues,origin_groups=len(groups),
        by_stratum={k:dict(cases=len(v),counts=sums(v) if k!='OUT_OF_PROFILE' else None) for k,v in strata.items()},
        by_provenance={k:dict(cases=len(v),counts=sums(v)) for k,v in provenance.items()},
        leave_one_origin_group_out=loo,population_ci=None,human_output_audit='NOT_PERFORMED_BY_TOOL',proposed_numeric_gates=proposed,
        decision='NOT_REGISTERED',decision_reason='Registration and human custody/approval are separate; author diagnostics never establish independent criteria.',
        per_case=records)


def paired(left,right):
    a={r['case_id']:r for r in left['per_case']};b={r['case_id']:r for r in right['per_case']}
    if set(a)!=set(b):raise ValueError('unpaired_case_set')
    counts=Counter()
    for cid in a:
        if not a[cid]['primary_eligible']:continue
        ga={tuple(x) for x in a[cid]['missing_gold_keys']}|{tuple(x['key']) for x in a[cid]['per_key'] if x['strict_match']}
        ta={tuple(x['key']) for x in a[cid]['per_key'] if x['strict_match']};tb={tuple(x['key']) for x in b[cid]['per_key'] if x['strict_match']}
        for k in ga:counts['both' if k in ta&tb else 'impactmap_only' if k in ta else 'ls1_only' if k in tb else 'neither']+=1
    return dict(gold_key_hits=dict(counts),metric_differences={k:(left[k]-right[k] if left[k] is not None and right[k] is not None else None) for k in ('precision','recall','false_alert_case_rate')},statistical_superiority_claim=False)
