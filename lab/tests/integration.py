"""Real PG/RMQ suite. Run ONLY in a freshly bootstrapped isolated Compose project.

python -m lab.tests.integration --output /evidence/integration.json
Nonzero exit means FAIL or BLOCKED. Unimplemented scenarios remain NOT_RUN.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from lab.evaluator.verify import frozen_expectations, suite_digest


def run(candidate_only=False, broken_only=False):
    started = time.monotonic()
    expected = frozen_expectations()
    report = {'suite_digest': suite_digest(), 'suite_version': expected['suite_version'],
              'kind': 'REAL_POSTGRESQL_RABBITMQ_INTEGRATION', 'checks': {},
              'cases': {k:{'status':'NOT_RUN','evidence':'Not executed in this run'} for k in expected['cases']},
              'measurements': {'manual_active_seconds':'NOT_MEASURED','model_cost':'NOT_MEASURED',
                               'infrastructure_cost':'NOT_MEASURED','waiting_seconds':'NOT_MEASURED'}}
    def check(key, action):
        try:
            evidence = action()
            report['checks'][key] = {'status':'PASS','evidence': evidence}
            return True
        except Exception as exc:
            report['checks'][key] = {'status':'FAIL','evidence':{'type':type(exc).__name__,'code':getattr(exc,'code',None),'assertion':str(exc) if isinstance(exc,AssertionError) else None}}
            return False
    def need(condition, message):
        if not condition: raise AssertionError(message)
    try:
        from lab.app import service as app
        import psycopg
        from psycopg.rows import dict_row
        required = ['SOURCE_READ_DSN','BILLING_READ_DSN','SOURCE_DSN','BILLING_DSN','RABBITMQ_URL']
        if any(not os.environ.get(x) for x in required):raise RuntimeError('Missing live service DSNs')
        app.initialize()
        def rows(kind, sql, params=()):
            with psycopg.connect(os.environ[kind+'_READ_DSN'], row_factory=dict_row) as c:
                return c.execute(sql,params).fetchall()
        need(rows('SOURCE','SELECT current_state FROM lab_state')[0]['current_state']=='S0','Fresh S0 required')
        need(rows('SOURCE','SELECT count(*) n FROM orders')[0]['n']==0,'Fresh empty project required')
    except Exception as exc:
        report['checks']['live_preflight']={'status':'BLOCKED','evidence':{'type':type(exc).__name__,'reason':'Fresh isolated live PostgreSQL/RabbitMQ and verifier read-only credentials required'}}
        report['outcome']='BLOCKED';return report
    known = {}
    def business():
        source = rows('SOURCE','SELECT order_id,amount_rub FROM orders ORDER BY order_id')
        ledger = rows('BILLING','SELECT order_id,amount_minor,currency FROM ledger ORDER BY order_id')
        actual = {x['order_id']:x['amount_minor'] for x in ledger}
        need(actual==known,'Ledger differs from independent fixed inputs')
        need(len(ledger)==len(known),'Incomplete or duplicated ledger')
        need(all(x['currency']=='RUB' for x in ledger),'Wrong currency')
        need({x['order_id']:x['amount_rub']*100 for x in source}==known,'v1 business meaning changed')
        v1 = rows('SOURCE','SELECT coalesce(sum(amount_rub::numeric*100),0) n FROM analytics.orders_v1')[0]['n']
        need(int(v1)==sum(known.values()),'v1 analytics mismatch')
        state=rows('SOURCE','SELECT * FROM lab_state')[0]
        if int(state['current_state'][1:])>=3:
            v2=rows('SOURCE','SELECT coalesce(sum(amount_minor::numeric),0) n FROM analytics.orders_v2')[0]['n']
            need(int(v2)==sum(known.values()),'v2 analytics mismatch')
        return {'order_count':len(known),'expected_minor_total':sum(known.values()),'ledger':actual,'state':state['current_state']}
    def create(ident, minor, **kwargs):
        app.create_order(ident,minor//100,**kwargs);known[ident]=minor
    def drain():
        app.publish();app.consume()
    def baseline():
        for n,m in enumerate(expected['held_out_minor']):create(f'held-{n}',m)
        drain();return business()
    if not check('baseline',baseline):
        report['outcome']='FAIL';return report
    if broken_only:
        def broken():
            create('naive-broken',12500,naive=True);drain()
            observed=rows('BILLING',"SELECT amount_minor FROM ledger WHERE order_id='naive-broken'")[0]['amount_minor']
            analytics=rows('SOURCE',"SELECT amount_rub::numeric*100 minor FROM analytics.orders_v1 WHERE order_id='naive-broken'")[0]['minor']
            need(observed==1250000 and int(analytics)==1250000,'Expected semantic failure did not reproduce')
            need(observed!=12500,'Broken candidate was accepted')
            return {'expected_minor':12500,'observed_billing_minor':observed,'observed_analytics_minor':str(analytics),'independent_verdict':'REJECT'}
        check('T02',broken);report['cases']['T02']=report['checks']['T02']
        report['outcome']='PASS' if report['checks']['T02']['status']=='PASS' else 'FAIL'
        report['coverage']='deliberately incompatible v1 control, independently rejected'
        return report
    def reject_wrong_migration():
        import tempfile
        before=rows('SOURCE','SELECT order_id,amount_rub FROM orders ORDER BY order_id')
        prior=os.environ.get('LAB_EXPAND_SQL')
        with tempfile.NamedTemporaryFile(mode='w',suffix='.sql') as tmp:
            tmp.write('ALTER TABLE orders ADD COLUMN amount_minor bigint; UPDATE orders SET amount_minor=amount_rub*10000;');tmp.flush()
            os.environ['LAB_EXPAND_SQL']=tmp.name
            try:
                try:app.transition('S1')
                except app.LabError as exc:need(exc.code=='BACKFILL','Wrong candidate failure reason')
                else:raise AssertionError('Wrong migration accepted')
            finally:
                if prior is None:os.environ.pop('LAB_EXPAND_SQL',None)
                else:os.environ['LAB_EXPAND_SQL']=prior
        need(before==rows('SOURCE','SELECT order_id,amount_rub FROM orders ORDER BY order_id'),'Rejected candidate changed source')
        need(rows('SOURCE','SELECT current_state FROM lab_state')[0]['current_state']=='S0','Rejected candidate advanced state')
        need(not rows('SOURCE',"SELECT 1 FROM information_schema.columns WHERE table_name='orders' AND column_name='amount_minor'"),'Failed candidate DDL persisted')
        return {'verdict':'REJECT','source_unchanged':True,'transactional_DDL_rolled_back':True}
    check('wrong_migration_rejected',reject_wrong_migration)
    def readonly():
        for kind in ['SOURCE','BILLING']:
            value=rows(kind,"SELECT has_table_privilege(current_user,%s,'INSERT') writable",('orders' if kind=='SOURCE' else 'ledger',))[0]
            need(not value['writable'],'Verifier role can write')
        return {'source_and_billing_roles':'SELECT only'}
    check('readonly_verifier',readonly)
    def corrected():
        states=[]
        for step in range(1,6):
            app.transition(f'S{step}')
            create(f'mixed-{step}',(step+1)*100)
            if step==4:
                app.publish()
                try:app.consume(version=1)
                except app.LabError as exc:need(exc.code=='MIXED_VERSION','Unsupported version failed for wrong reason')
                else:raise AssertionError('Billing v1 incorrectly consumed v2')
                need(not rows('BILLING','SELECT order_id FROM ledger WHERE order_id=%s',(f'mixed-{step}',)),'Unsupported consumer committed ledger')
            drain()
            states.append(business())
        return {'states':states,'coverage':'R1-R5 financial transition; R6-R8 require runtime grant/context scenarios'}
    if not check('compatible_S0_S5',corrected):
        report['outcome']='FAIL';return report
    if candidate_only:
        report['outcome']='FAIL' if any(x['status']=='FAIL' for x in report['checks'].values()) else 'PASS';report['coverage']='candidate migration, R1-R5 financial invariants only'
        report['measurements']['execution_seconds']=time.monotonic()-started
        return report
    report['cases']['T03']={'status':'BLOCKED','evidence':{'financial_transition':report['checks']['compatible_S0_S5'],'remaining':'Full R6-R8 enforcement not established by application integration suite'}}
    def fault_case(ident,minor,fn,fault):
        create(ident,minor)
        if fn==app.consume:app.publish()
        try:fn(fault=fault)
        except app.LabError as exc:need(exc.code.startswith('INJECTED_'),'Unexpected failure')
        else:raise AssertionError('Fault did not trigger')
        drain()
        proof=business()
        count=rows('BILLING','SELECT count(*) n FROM ledger WHERE order_id=%s',(ident,))[0]['n']
        need(count==1,'Duplicate business record')
        return {'fault':fault, 'business':proof,'ledger_rows_for_faulted_order':count}
    for case,ident,fn,fault in [('T11','confirm-loss',app.publish,'after_publish_confirm'),('T12','ack-loss',app.consume,'after_billing_commit')]:
        check(case,lambda ident=ident,fn=fn,fault=fault:fault_case(ident,1700,fn,fault))
        report['cases'][case]=report['checks'][case]
    def outbox():
        ident='outbox-gap';known[ident]=2300
        try:app.create_order(ident,23,fault='after_order_commit')
        except app.LabError as exc:need(exc.code=='INJECTED_AFTER_ORDER_COMMIT','Wrong fault')
        need(not rows('BILLING','SELECT * FROM ledger WHERE order_id=%s',(ident,)),'Unexpected publication')
        need(rows('SOURCE','SELECT count(*) n FROM outbox WHERE order_id=%s AND published_at IS NULL',(ident,))[0]['n']==1,'No durable outbox')
        drain();return business()
    check('outbox_commit_publish_gap',outbox)
    def routing_fault():
        import pika
        ident='routing-gap';create(ident,3100)
        connection=app.rabbit();channel=connection.channel()
        channel.queue_unbind(queue='billing',exchange='orders.events',routing_key='order.created.v2')
        try:
            try:app.publish()
            except pika.exceptions.UnroutableError:pass
            else:raise AssertionError('Unroutable publication reported success')
            need(not rows('BILLING','SELECT order_id FROM ledger WHERE order_id=%s',(ident,)),'Wrongly delivered order')
            need(rows('SOURCE','SELECT count(*) n FROM outbox WHERE order_id=%s AND published_at IS NULL',(ident,))[0]['n']==1,'Unroutable outbox marked sent')
        finally:
            channel.queue_bind(queue='billing',exchange='orders.events',routing_key='order.created.v2');connection.close()
        drain()
        return {'missing_binding_detected':True,'no_ledger_before_recovery':True,'recovery':business()}
    check('T05',routing_fault);report['cases']['T05']=report['checks']['T05']
    def invalid():
        inputs=[('null',None,'RUB'),('negative',-1,'RUB'),('fractional','1.5','RUB'),('currency',1,'USD'),('overflow',str(2**63),'RUB'),('bool',True,'RUB')]
        results=[]
        for name,value,currency in inputs:
            try:app.create_order('invalid-'+name,value,currency)
            except app.LabError as exc:results.append({'class':name,'rejected':True,'code':exc.code})
            else:raise AssertionError('Invalid input accepted')
            need(not rows('SOURCE','SELECT order_id FROM orders WHERE order_id=%s',('invalid-'+name,)),'Rejected order persisted')
        return results
    check('T16',invalid);report['cases']['T16']=report['checks']['T16']
    def fractional():
        for minor in expected['coexistence_reject_minor']:
            try:app.create_order('fraction-'+str(minor),str(__import__('decimal').Decimal(minor)/100))
            except app.LabError as exc:need(exc.code=='COMPATIBILITY','Wrong rejection')
            else:raise AssertionError('Fractional legacy amount accepted')
        return {'rejected_minor':expected['coexistence_reject_minor'],'S6':'NOT_RUN; separate authorization required'}
    check('T15',fractional);report['cases']['T15']=report['checks']['T15']
    def replay():
        before=rows('SOURCE','SELECT order_id,amount_minor FROM orders ORDER BY order_id')
        effect_count=rows('SOURCE',"SELECT count(*) n FROM transition_log WHERE target='S1'")[0]['n']
        result=app.transition('S1')
        need(result['replayed'],'Retry not reconciled')
        need(before==rows('SOURCE','SELECT order_id,amount_minor FROM orders ORDER BY order_id'),'Backfill executed twice')
        need(effect_count==rows('SOURCE',"SELECT count(*) n FROM transition_log WHERE target='S1'")[0]['n'],'Duplicate step effect')
        return {'backfill_count':effect_count,'replayed':True,'limitation':'UNKNOWN journal transition not injected'}
    check('idempotent_backfill_replay',replay)
    report['outcome']='FAIL' if any(x['status']=='FAIL' for x in report['checks'].values()) else 'INCOMPLETE'
    report['measurements']['execution_seconds']=time.monotonic()-started
    report['coverage']='Live money, mixed versions, durable outbox, duplicate delivery, commit-before-ack; no cloud qualification or real LLM claim'
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--candidate-only',action='store_true');parser.add_argument('--broken-only',action='store_true')
    args=parser.parse_args();result=run(args.candidate_only,args.broken_only)
    p=Path(args.output);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(result,indent=2,default=str)+'\n')
    print(json.dumps({'outcome':result['outcome'],'output':str(p),'checks':{k:v['status'] for k,v in result['checks'].items()}}))
    raise SystemExit(1 if result['outcome'] in ('FAIL','BLOCKED') else 0)
if __name__=='__main__':main()
