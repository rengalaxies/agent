"""One model attempt, two calls, independent fresh environments; preserve failures."""
import difflib
import json
import os
from pathlib import Path
import tempfile
from lab.evaluator.verify import verify
from lab.evaluator.qualify_boundaries import qualify, grounds
from lab.runtime.run import run


def main():
    root=Path.cwd();out=root/'agent-evidence';out.mkdir(exist_ok=True)
    change=json.loads((root/'lab/catalog/change.example.json').read_text())
    (out/'input.json').write_text(json.dumps(change,indent=2))
    os.environ['LAB_ENABLE_ISOLATED_VERIFIER']='1'
    summary={'source_commit':os.environ['GITHUB_SHA'],'model':os.environ.get('CLOUDRU_LLM_MODEL'),
             'actions_run':os.environ['GITHUB_SERVER_URL']+'/'+os.environ['GITHUB_REPOSITORY']+'/actions/runs/'+os.environ['GITHUB_RUN_ID'],
             'attempt':os.environ['GITHUB_RUN_ATTEMPT'],'budget':{'model_attempts':1,'calls':2,'tokens':64000,'seconds':240},
             'automatic_application':'BLOCKED','cloud_vm_actions':[]}
    try:
        summary['boundaries']=qualify(root,out/'r6-r8.json')
        # Original wrong input is executed before any model call, in its own fresh environment.
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'lab/sql/expand.sql';target.parent.mkdir(parents=True)
            target.write_text(change['proposed_files']['lab/sql/expand.sql'])
            summary['negative_control']=verify(tmp)
        (out/'negative-control.json').write_text(json.dumps(summary['negative_control'],indent=2))
        result=run(root,out/'model-attempt-1',change,max_seconds=240,max_tokens=64000)
        summary['agent']=result
        patch=out/'model-attempt-1/candidate/lab/sql/expand.sql'
        if patch.exists():
            (out/'model.patch').write_text(''.join(difflib.unified_diff(change['proposed_files']['lab/sql/expand.sql'].splitlines(True),patch.read_text().splitlines(True),fromfile='submitted/lab/sql/expand.sql',tofile='model/lab/sql/expand.sql')))
            summary['grounds_digest']=grounds(root,patch.parents[2],change,{'execution_grant':None,'automatic_application':'BLOCKED'})
        summary['outcome']='PASS' if (summary['negative_control']['outcome']=='FAIL' and result['outcome']=='VERIFIED_WITHIN_SCOPE' and summary['boundaries']['outcome']=='PASS') else 'FAIL'
    except Exception as exc:
        summary.update(outcome='FAIL',error_class=type(exc).__name__)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:summary.get(k) for k in ['outcome','source_commit','model','actions_run','automatic_application']}))
    return 0 if summary['outcome']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
