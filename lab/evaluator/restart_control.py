"""Trusted CI controller: prove DB and a pending broker message survive restart."""
import json
from pathlib import Path
import subprocess


def main():
    base=['docker','compose','-f','lab/compose.yaml']
    report={'kind':'REAL_COMPONENT_RESTART','outcome':'FAIL'}
    def cli(service,*args):
        result=subprocess.run(base+['run','--rm',service,*args],capture_output=True,text=True,timeout=90)
        if result.returncode:raise RuntimeError('SCOPED_CLI_FAILED')
        return json.loads(result.stdout)
    try:
        cli('app','create-order','--order-id','restart-control','--amount-rub','125')
        cli('app','publish')
        before=cli('verifier')
        assert not any(x['order_id']=='restart-control' for x in before['billing']['ledger'])
        subprocess.run(base+['restart','postgres','rabbitmq'],check=True,capture_output=True,timeout=90)
        subprocess.run(base+['up','-d','--wait','--wait-timeout','120','postgres','rabbitmq'],
                       check=True,capture_output=True,timeout=150)
        restored=cli('verifier')
        assert restored==before, 'Persistent database rows changed on restart'
        cli('app','consume')
        after=cli('verifier')
        matches=[x for x in after['billing']['ledger'] if x['order_id']=='restart-control']
        assert len(matches)==1 and matches[0]['amount_minor']==12500
        assert after['source']==before['source']
        old=[x for x in after['billing']['ledger'] if x['order_id']!='restart-control']
        assert old==before['billing']['ledger']
        report.update(outcome='PASS',database_rows_survived=True,pending_message_delivered_after_restart=True,
                      business_records_for_restarted_order=1,amount_minor=12500,
                      independent_operator_T19='NOT_RUN')
    except Exception as exc:
        report['error_class']=type(exc).__name__
    Path('lab-evidence/restart.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
    raise SystemExit(0 if report['outcome']=='PASS' else 1)


if __name__=='__main__':main()
