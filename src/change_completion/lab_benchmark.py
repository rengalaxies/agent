"""Engineering challenge, not customer ROI or a strong-agent comparison."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import time
from .contract_profile import check_profile, generate_candidate

def run_lab(example):
    example=Path(example)
    suite=(example/'approval/suite.json').read_bytes()
    approved=(example/'approval/suite.sha256').read_text().split()[0]
    if sha256(suite).hexdigest()!=approved: raise ValueError('approval changed')
    records=[]
    with tempfile.TemporaryDirectory(prefix='change-challenge-') as directory:
        root=Path(directory)
        candidates=[('unchanged',example/'baseline','FAIL')]
        for name,changes,expected in [('scoped','changes.json','PASS'),('blanket','negative-changes.json','FAIL')]:
            output=root/name
            generate_candidate(example/'baseline',output,json.loads((example/changes).read_text()))
            candidates.append((name,output,expected))
        for name,path,expected in candidates:
            started=time.monotonic();result=check_profile(path,suite,approved)
            records.append({'variant':name,'status':result['status'],'expected_status':expected,
                'seconds':round(time.monotonic()-started,6),'checks':result['checks']})
    return {'kind':'synthetic_engineering_challenge','suite_sha256':approved,
            'qualified':all(r['status']==r['expected_status'] for r in records),'records':records,
            'strong_agent_comparison':'NOT_RUN','customer_hours':None,'supplier_hours':None,
            'commercial_advantage_established':False}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--example',required=True);a=p.parse_args()
    result=run_lab(a.example);print(json.dumps(result,indent=2));return 0 if result['qualified'] else 1
if __name__=='__main__':raise SystemExit(main())
