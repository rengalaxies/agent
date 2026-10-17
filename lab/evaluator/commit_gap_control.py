"""Host-owned fresh CI controller. Frozen expected values predate implementation."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
from lab.runtime.core import digest


def main():
    root=Path.cwd();out=root/'commit-gap-evidence';out.mkdir(exist_ok=True);out.chmod(0o777)
    raw=(root/'lab/evaluator/commit-gap-expectations.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest()==(root/'lab/evaluator/COMMIT-GAP-FREEZE.sha256').read_text().split()[0]
    expected=json.loads(raw);(out/'frozen-expectations.json').write_bytes(raw)
    project='dm-commit-gap-'+secrets.token_hex(6)
    env=dict(os.environ,LAB_APP_IMAGE=project+':trusted')
    for key in ['ORDERS_PASSWORD','BILLING_PASSWORD','VERIFIER_PASSWORD','PG_ADMIN_PASSWORD','RABBIT_PASSWORD']:env[key]=secrets.token_hex(24)
    base=['docker','compose','-p',project,'-f','lab/compose.yaml']
    report={'scenario':expected['scenario'],'outcome':'FAIL','source_commit':os.environ['GITHUB_SHA'],
            'actions_run':'https://github.com/'+os.environ['GITHUB_REPOSITORY']+'/actions/runs/'+os.environ['GITHUB_RUN_ID'],
            'expectations_sha256':hashlib.sha256(raw).hexdigest(),'compose_project':project,
            'automatic_application':'BLOCKED','llm_calls':0,'vm_actions':[], 'processes':[]}
    def command(args,timeout=180):
        p=subprocess.run(base+args,env=env,capture_output=True,text=True,timeout=timeout)
        if p.returncode:raise RuntimeError('COMPOSE_STEP_FAILED')
        return p.stdout
    def worker(mode,service='app',crash=False):
        mount=str(out)+':/evidence'+(':ro' if service=='verifier' else '')
        p=subprocess.run(base+['run','--rm','--entrypoint','python','-v',mount,service,'-m','lab.evaluator.commit_gap_worker',mode],
                         env=env,capture_output=True,text=True,timeout=150)
        report['processes'].append({'mode':mode,'service':service,'exit_code':p.returncode,'new_container_process':True})
        if crash:
            assert p.returncode==expected['exit_code'];return
        if p.returncode:raise RuntimeError('WORKER_'+mode.upper()+'_FAILED')
        value=json.loads(p.stdout);(out/(mode+'.json')).write_text(json.dumps(value,indent=2)+'\n');return value
    try:
        command(['build','app'],600)
        report['image_id']=subprocess.check_output(['docker','image','inspect','--format','{{.Id}}',env['LAB_APP_IMAGE']],text=True).strip()
        command(['up','-d','--wait','--wait-timeout','120','postgres','rabbitmq'])
        command(['run','--rm','bootstrap'])
        worker('prepare')
        before=worker('readonly','verifier');(out/'before.json').write_text(json.dumps(before,indent=2))
        assert len(before['billing']['ledger'])==expected['delivered_before_fault']
        worker('fault',crash=True)
        journal=out/'journal/audit.jsonl';prior=journal.read_text();(out/'journal-after-crash.jsonl').write_text(prior)
        rows=[json.loads(line) for line in prior.splitlines()]
        assert len(rows)==1 and rows[0]['state']=='INTENDED'
        crashed=worker('readonly','verifier');(out/'after-crash.json').write_text(json.dumps(crashed,indent=2))
        recovered=worker('recover')
        assert recovered['state']==expected['expected_recovery'] and recovered['reason']==expected['expected_reason']
        assert recovered['retry']['state']==expected['blind_retry'] and not recovered['executed_actions']
        after=worker('readonly','verifier');(out/'after-recovery.json').write_text(json.dumps(after,indent=2))
        assert after==crashed, 'recovery/retry changed durable business state'
        drained=worker('drain')
        final=worker('readonly','verifier');(out/'final.json').write_text(json.dumps(final,indent=2))
        # Independent expected order/money map, never the action's self-reported success.
        wanted={k:v*100 for k,v in expected['input_rubles'].items()}
        for snapshot in [crashed,after,final]:
            source=snapshot['source'];assert source['lab_state'][0]['current_state']=='S1'
            assert len(source['transition_log'])==expected['expected_transition_log_rows']
            assert source['transition_log'][0]['target']=='S1' and source['transition_log'][0]['detail']['previous']=='S0'
            assert {r['order_id']:r['amount_minor'] for r in source['orders']}==wanted
            assert all(r['amount_rub']*100==r['amount_minor'] for r in source['orders'])
            assert snapshot['instrumentation']['transition_invocations']==expected['expected_transition_invocations']
            updates=snapshot['instrumentation']['backfill_updates']
            assert len(updates)==expected['expected_backfill_update_rows'] and sorted(r['order_id'] for r in updates)==sorted(wanted)
        ledger=final['billing']['ledger'];assert len(ledger)==expected['expected_final_ledger_count']
        assert {r['order_id']:r['amount_minor'] for r in ledger}==wanted
        assert sum(r['amount_minor'] for r in ledger)==expected['expected_minor_total']
        assert len(final['billing']['processed_events'])==expected['expected_processed_events']
        assert len({r['event_id'] for r in final['billing']['processed_events']})==expected['expected_processed_events']
        assert all(r['published_at'] is not None and r['attempts']==1 for r in final['source']['outbox'])
        assert len(final['source']['outbox'])==expected['expected_order_count']
        assert drained['first']['handled']==expected['pending_before_fault'] and drained['second']['handled']==0
        assert drained['publish']['published']==0 and drained['queue_ready']==expected['expected_queue_ready']
        rows=[json.loads(line) for line in journal.read_text().splitlines()]
        previous='0'*64
        for row in rows:
            assert row['previous_digest']==previous and digest({k:v for k,v in row.items() if k!='record_digest'})==row['record_digest']
            previous=row['record_digest']
        assert [r['state'] for r in rows]==['INTENDED','RECONCILED_COMMITTED_STOP']
        assert rows[1]['intended_record_digest']==rows[0]['record_digest']
        assert rows[1]['observed_effect']=={k:v for k,v in crashed.items() if k!='instrumentation'}
        report.update(outcome='PASS',recovery=recovered,independent_checks={
            'normalized_money_total':expected['expected_minor_total'],'orders_and_ledger':5,
            'transition_invocations':1,'actual_backfill_updates':5,'remaining_messages_delivered':1,
            'blind_retry':'DENIED_BEFORE_EFFECT','journal_matches_durable_state':True,
            'journal_states':[r['state'] for r in rows]},coverage=expected['coverage'])
    except Exception as exc:report['error_class']=type(exc).__name__
    finally:
        try:command(['down','--volumes','--remove-orphans'],120);report['cleanup']='PASS'
        except Exception:report.update(outcome='FAIL',cleanup='BLOCKED')
        (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))
    return 0 if report['outcome']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
