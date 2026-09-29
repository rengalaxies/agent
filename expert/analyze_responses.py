"""Validate blind expert exports; describe agreement without treating ratings as iid."""
import argparse
from collections import Counter
from itertools import combinations
import json
from pathlib import Path

LABELS={'ACCEPT','REJECT','NEEDS_REVIEW'}

def analyze(paths, catalog_hash, scenario_ids, analysis_ids=None):
    experts={}
    for path in paths:
        d=json.loads(Path(path).read_text())
        if d.get('schema_version')!='expert-1' or d.get('catalog_hash')!=catalog_hash:
            raise ValueError(f'incompatible export: {path}')
        if not d.get('consent') or not d.get('complete') or not d.get('expert_id') or not d.get('role'):
            raise ValueError(f'incomplete consent/profile/export: {path}')
        if d['expert_id'] in experts: raise ValueError('duplicate expert; select one final export explicitly')
        answers=d['answers'];ids=[a['scenario_id'] for a in answers]
        if len(ids)!=len(set(ids)) or set(ids)!=set(scenario_ids): raise ValueError('missing, duplicate or unknown cases')
        for a in answers:
            if a['decision'] not in LABELS or not a.get('reason','').strip(): raise ValueError('invalid decision/reason')
            if str(a['confidence']) not in {'1','2','3','4','5'} or str(a['realism']) not in {'1','2','3','4','5'}: raise ValueError('invalid rating')
            if a['decision']=='NEEDS_REVIEW' and not a.get('missing_information','').strip(): raise ValueError('review requires missing information')
        experts[d['expert_id']]={a['scenario_id']:a for a in answers}
    selected_ids=analysis_ids if analysis_ids is not None else scenario_ids
    cases=[]
    for sid in sorted(selected_ids):
        votes=Counter(e[sid]['decision'] for e in experts.values())
        cases.append({'scenario_id':sid,'votes':dict(votes),'agreement':len(votes)==1 and bool(votes),
            'requires_adjudication':len(votes)>1,'reasons':{eid:e[sid]['reason'] for eid,e in experts.items()},
            'realism_counts':dict(Counter(str(e[sid]['realism']) for e in experts.values()))})
    pairs=[]
    for a,b in combinations(sorted(experts),2):
        x=[experts[a][s]['decision'] for s in sorted(selected_ids)];y=[experts[b][s]['decision'] for s in sorted(selected_ids)]
        n=len(x);observed=sum(i==j for i,j in zip(x,y))/n
        px=Counter(x);py=Counter(y);expected=sum(px[k]*py[k] for k in LABELS)/(n*n)
        pairs.append({'experts':[a,b],'cases':n,'observed_agreement':observed,'cohen_kappa':(observed-expected)/(1-expected) if expected<1 else None})
    return {'schema_version':'expert-analysis-1','catalog_hash':catalog_hash,'expert_count':len(experts),
        'distinct_cases':len(selected_ids),'decision_ratings':len(experts)*len(selected_ids),
        'pairwise_agreement':pairs,'cases':cases,
        'limitations':['Ratings from one expert and ratings of one case are dependent.',
            'Agreement is not validity; adjudication must preserve original responses.',
            'No automatic majority label and no H1 significance test is performed here.']}

def main():
    p=argparse.ArgumentParser();p.add_argument('--exports',type=Path,nargs='+',required=True);p.add_argument('--catalog',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    catalog=json.loads(a.catalog.read_text())
    result=analyze(a.exports,catalog['catalog_hash'],catalog['scenario_ids'])
    result['blocks']={block:analyze(a.exports,catalog['catalog_hash'],catalog['scenario_ids'],ids) for block,ids in catalog.get('blocks',{}).items()}
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
