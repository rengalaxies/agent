"""Independent known-candidate controls, not model performance measurements."""
import argparse
import json
import os
from pathlib import Path
import tempfile
from .verify import verify


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    os.environ['LAB_ENABLE_ISOLATED_VERIFIER'] = '1'
    controls = {}
    for name, content in [('compatible', (root/'lab/sql/expand.sql').read_text()),
                          ('wrong', 'ALTER TABLE orders ADD COLUMN amount_minor bigint; UPDATE orders SET amount_minor=amount_rub*10000;')]:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/'lab/sql/expand.sql'
            target.parent.mkdir(parents=True)
            target.write_text(content)
            controls[name] = verify(tmp)
    report = {'kind': 'INDEPENDENT_ARTIFACT_CONTROLS', 'agent_performance': 'NOT_MEASURED',
              'controls': controls, 'outcome': 'PASS' if controls['compatible']['outcome']=='PASS'
              and controls['wrong']['outcome']=='FAIL' else 'FAIL'}
    Path(args.output).write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'outcome': report['outcome'], 'controls': {k:v['outcome'] for k,v in controls.items()}}))
    raise SystemExit(0 if report['outcome']=='PASS' else 1)


if __name__ == '__main__':
    main()
