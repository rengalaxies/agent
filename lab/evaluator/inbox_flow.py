"""Actual CLI user journey using explicitly historical real-agent evidence. No inference."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from lab.runtime.core import digest
from lab.runtime.inbox import replay


def main():
    root=Path.cwd();out=root/'inbox-evidence';out.mkdir(exist_ok=True)
    transcript=[];report={'outcome':'FAIL','source_commit':os.getenv('GITHUB_SHA','LOCAL'),
        'llm_calls':0,'external_notifications':0,'execution_permission':False,'vm_actions':[],
        'mode':'SAVED_REAL_AGENT_REPLAY; NO_NEW_FINANCIAL_VERIFICATION',
        'actions_run':'https://github.com/'+os.getenv('GITHUB_REPOSITORY','rengalaxies/agent')+'/actions/runs/'+os.getenv('GITHUB_RUN_ID','LOCAL')}
    def cli(store,*args,expected=0):
        command=[sys.executable,'-m','lab.runtime.inbox','--store',str(store),*args]
        p=subprocess.run(command,capture_output=True,text=True,timeout=30)
        assert p.returncode==expected
        entry={'command':command[1:],'exit_code':p.returncode}
        if expected:
            entry['reason']=p.stderr.strip();value=None
        else:
            value=json.loads(p.stdout)
            entry.update(cards=[{k:c[k] for k in ['card_id','revision','team','active','status','next_action_owner']} for c in value['cards']],
                         decisions=[{k:d[k] for k in ['decision_id','revision','decision','valid','grants_execution']} for d in value['decisions']],
                         local_notification_count=len(value['local_notifications']),snapshot_digest=digest(value))
        transcript.append(entry);return value
    def decision(store,card,kind,actor,expected=0):
        return cli(store,'decide','--card-id',card['card_id'],'--revision',str(card['revision']),
            '--assessment',card['assessment_digest'],'--team',card['team'],'--actor',actor,'--decision',kind,
            '--comment','CLI scenario decision for this exact revision; no execution permission',expected=expected)
    try:
        r=replay(root);change=copy.deepcopy(r['input']);input1=out/'change-revision-1.json';input1.write_text(json.dumps(change,indent=2))
        store=out/'team-inbox.json'
        def assess(path=store,change_file=input1,source=None):
            args=['assess','--root',str(root),'--change',str(change_file),'--initiator','orders-owner','--coordinator','stand-coordinator']
            if source:args+=['--source',str(source)]
            return cli(path,*args)
        first=assess();assert {c['team'] for c in first['cards']}=={'billing','analytics'}
        billing=next(c for c in first['cards'] if c['team']=='billing');analytics=next(c for c in first['cards'] if c['team']=='analytics')
        ack=decision(store,billing,'acknowledged','billing-reviewer')
        assert not ack['decisions'][-1]['grants_execution'] and not ack['execution_permission']
        remarks=decision(store,analytics,'request_changes','analytics-reviewer')
        assert next(c for c in remarks['cards'] if c['team']=='analytics')['status']=='заблокировано'
        duplicate=assess();assert duplicate==remarks and len(duplicate['local_notifications'])==2
        change['revision']=2;change['intent']+=' Revision 2: requirements must be assessed again.'
        input2=out/'change-revision-2.json';input2.write_text(json.dumps(change,indent=2))
        second=assess(change_file=input2)
        assert len(second['cards'])==4 and len(second['local_notifications'])==4
        assert all(not d['valid'] for d in second['decisions'])
        active=[c for c in second['cards'] if c['active']]
        assert all(c['status']=='требуется решение' and c['decision'] is None and c['independent_verification']['status']=='NOT_RUN_FOR_THIS_REVISION' for c in active)
        decision(store,billing,'reviewed','billing-reviewer',expected=2)
        assert assess(change_file=input2)==second
        acknowledged=decision(store,next(c for c in active if c['team']=='billing'),'acknowledged','billing-reviewer')
        assert not acknowledged['execution_permission'] and acknowledged['decisions'][-1]['revision']==2
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'source';shutil.copytree(r['source'],source)
            p=source/'lab/catalog/owners.json';catalog=json.loads(p.read_text())
            catalog['bindings']=[b for b in catalog['bindings'] if b.get('object_ref')!='lab/app/service.py#consume']
            p.write_text(json.dumps(catalog));(out/'unknown-owner-catalog.json').write_text(json.dumps(catalog,indent=2))
            unknown=assess(path=out/'unknown-owner-inbox.json',source=source)
            coordinator=next(c for c in unknown['cards'] if c['team']=='COORDINATOR')
            assert coordinator['responsible']=='stand-coordinator' and coordinator['status']=='заблокировано'
            assert coordinator['grounds'][0]['owner']=='UNKNOWN'
            assert len(unknown['cards'])==2
        report.update(outcome='PASS',replayed_source_commit=r['source_commit'],replayed_actions_run=r['run'],
            cases={'breaking_change':'PASS','unknown_owner_to_coordinator':'PASS','revision_and_deduplication':'PASS',
                   'stale_decision_denied':'PASS','acknowledgement_is_not_permission':'PASS'},
            discovery='supported literal AST references from saved code; declared ownership catalog; no runtime discovery',
            workflow_steps=len(transcript))
    except Exception as exc:report['error_class']=type(exc).__name__
    (out/'cli-journey.json').write_text(json.dumps(transcript,indent=2,ensure_ascii=False)+'\n')
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
    return 0 if report['outcome']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
