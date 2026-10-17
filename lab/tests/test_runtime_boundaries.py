"""Unit checks only: these do not establish live T04/T09/T10/T18 acceptance."""
import copy
import tempfile
import unittest
from pathlib import Path
from lab.runtime.core import enforce_grant, stage_candidate, Stop

class RuntimeBoundaryUnitTests(unittest.TestCase):
    def setUp(self):
        self.grant={'grant_id':'test','expires_at':'2099-01-01T00:00:00+00:00',
                    'environment_id':'lab','action_kinds':['transition'],
                    'exact_scope':['S1'],'context_digest':'pinned','issuer':'test-operator'}
    def test_grant_exact_scope_and_revision(self):
        enforce_grant(self.grant,'transition','S1','lab','pinned')
        for action,obj,env,context in [('deploy','S1','lab','pinned'),('transition','S2','lab','pinned'),('transition','S1','other','pinned'),('transition','S1','lab','changed')]:
            with self.subTest(action=action,obj=obj,env=env,context=context):
                with self.assertRaises(Stop):enforce_grant(self.grant,action,obj,env,context)
    def test_revoked_and_expired(self):
        with self.assertRaises(Stop):enforce_grant(self.grant,'transition','S1','lab','pinned',revoked=['test'])
        self.grant['expires_at']='2000-01-01T00:00:00+00:00'
        with self.assertRaises(Stop):enforce_grant(self.grant,'transition','S1','lab','pinned')
    def test_evaluator_and_traversal_patch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ['lab/evaluator/expectations.json','../lab/sql/expand.sql','lab/app/service.py']:
                with self.subTest(name=name):
                    with self.assertRaises(Stop):stage_candidate(tmp,Path(tmp)/'candidate',{'patches':[{'path':name,'content':'bad'}]})
