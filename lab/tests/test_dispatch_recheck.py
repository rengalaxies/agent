"""Authorization races are checked without executing database or broker effects."""
import tempfile
import unittest
from unittest.mock import patch
from lab.runtime.core import Stop, digest
from lab.runtime.dispatch import execute


class DispatchRecheckTests(unittest.TestCase):
    def test_financial_pass_does_not_authorize_transition(self):
        change={'environment_id':'lab','revision':1}
        context=digest({'source':'source','change':change})
        bound=digest({'change_context':context,'artifact_digest':'artifact','suite_digest':'suite'})
        grant={'grant_id':'g','expires_at':'2099-01-01T00:00:00+00:00','environment_id':'lab',
               'action_kinds':['transition'],'exact_scope':['S1'],'context_digest':bound,'issuer':'operator'}
        with tempfile.TemporaryDirectory() as tmp:
            with patch('lab.runtime.dispatch.discover',return_value={'snapshot_digest':'source'}), \
                 patch('lab.runtime.dispatch.tree_digest',return_value='artifact'), \
                 patch('lab.evaluator.verify.suite_digest',return_value='suite'), \
                 patch('lab.evaluator.verify.verify',return_value={'outcome':'PASS','accepted_properties':['R1','R2','R3','R4','R5']}), \
                 patch('lab.app.service.transition') as effect:
                with self.assertRaisesRegex(Stop,'Financial-only'):
                    execute(tmp,tmp,change,grant,tmp,'S1',authority_loader=lambda:{'grant':grant})
                effect.assert_not_called()

    def test_revocation_or_expiry_during_verification_blocks_effect(self):
        change={'environment_id':'lab','revision':1}
        context=digest({'source':'source','change':change})
        bound=digest({'change_context':context,'artifact_digest':'artifact','suite_digest':'suite'})
        for revoked,expiry in [(['g'],'2099-01-01T00:00:00+00:00'),([], '2000-01-01T00:00:00+00:00')]:
            grant={'grant_id':'g','expires_at':'2099-01-01T00:00:00+00:00','environment_id':'lab',
                   'action_kinds':['transition'],'exact_scope':['S1'],'context_digest':bound,'issuer':'operator'}
            fresh={**grant,'expires_at':expiry}
            with self.subTest(revoked=revoked,expiry=expiry), tempfile.TemporaryDirectory() as tmp:
                with patch('lab.runtime.dispatch.discover',return_value={'snapshot_digest':'source'}), \
                     patch('lab.runtime.dispatch.tree_digest',return_value='artifact'), \
                     patch('lab.evaluator.verify.suite_digest',return_value='suite'), \
                     patch('lab.evaluator.verify.verify',return_value={'outcome':'PASS','accepted_properties':['R'+str(i) for i in range(1,9)]}), \
                     patch('lab.app.service.transition') as effect:
                    with self.assertRaises(Stop):
                        execute(tmp,tmp,change,grant,tmp,'S1',authority_loader=lambda:{'grant':fresh,'revoked':revoked})
                    effect.assert_not_called()

    def test_context_changed_during_verification_blocks_effect(self):
        change={'environment_id':'lab','revision':1}
        context=digest({'source':'old','change':change})
        bound=digest({'change_context':context,'artifact_digest':'artifact','suite_digest':'suite'})
        grant={'grant_id':'g','expires_at':'2099-01-01T00:00:00+00:00','environment_id':'lab',
               'action_kinds':['transition'],'exact_scope':['S1'],'context_digest':bound,'issuer':'operator'}
        with tempfile.TemporaryDirectory() as tmp:
            with patch('lab.runtime.dispatch.discover',side_effect=[{'snapshot_digest':'old'},{'snapshot_digest':'changed'}]), \
                 patch('lab.runtime.dispatch.tree_digest',return_value='artifact'), \
                 patch('lab.evaluator.verify.suite_digest',return_value='suite'), \
                 patch('lab.evaluator.verify.verify',return_value={'outcome':'PASS','accepted_properties':['R'+str(i) for i in range(1,9)]}), \
                 patch('lab.app.service.transition') as effect:
                with self.assertRaises(Stop):
                    execute(tmp,tmp,change,grant,tmp,'S1',authority_loader=lambda:{'grant':grant})
                effect.assert_not_called()
