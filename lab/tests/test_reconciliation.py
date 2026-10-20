import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from lab.runtime.core import Audit, Stop
from lab.runtime.dispatch import reconcile_unknown

class ReconciliationTests(unittest.TestCase):
    def intent(self, directory):
        Audit(directory).record('transition',state='INTENDED',idempotency_key='key',target='S1',artifact_digest='artifact',
                                before={'source':{'lab_state':[{'current_state':'S0'}]}})
    def actual(self,state='S1'):
        return {'source':{'lab_state':[{'current_state':state}],
                         'transition_log':[{'target':'S1','detail':{'previous':'S0'}}],
                         'orders':[{'amount_rub':125,'amount_minor':12500}]},'billing':{}}
    def test_reconciliation_only_observes_and_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.intent(tmp)
            with patch('lab.app.service.snapshot',return_value=self.actual()),patch('lab.app.service.transition') as effect:
                result=reconcile_unknown(tmp,'artifact')
                self.assertEqual(result['state'],'RECONCILED_COMMITTED_STOP')
                self.assertEqual(result['executed_actions'],[])
                effect.assert_not_called()
    def test_mismatch_or_corrupt_journal_never_executes(self):
        for corrupt in [False,True]:
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as tmp:
                self.intent(tmp)
                if corrupt:
                    p=Path(tmp)/'audit.jsonl';row=json.loads(p.read_text());row['target']='S5';p.write_text(json.dumps(row)+'\n')
                with patch('lab.app.service.snapshot',return_value=self.actual('S2')),patch('lab.app.service.transition') as effect:
                    with self.assertRaises(Stop):reconcile_unknown(tmp,'artifact')
                    effect.assert_not_called()
