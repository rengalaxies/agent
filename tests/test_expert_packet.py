import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
spec=importlib.util.spec_from_file_location('expert_analysis',Path('expert/analyze_responses.py'))
analysis=importlib.util.module_from_spec(spec);spec.loader.exec_module(analysis)
class ExpertPacketTests(unittest.TestCase):
    def export(self,eid,label):
        return dict(schema_version='expert-1',catalog_hash='h',complete=True,consent=True,expert_id=eid,role='Architect',answers=[dict(scenario_id='s',decision=label,reason='reason',confidence='4',realism='3',missing_information='clarify')])
    def test_agreement_disagreement_preserved(self):
        with TemporaryDirectory() as d:
            paths=[]
            for eid,label in [('a','ACCEPT'),('b','REJECT')]:
                p=Path(d)/f'{eid}.json';p.write_text(json.dumps(self.export(eid,label)));paths.append(p)
            r=analysis.analyze(paths,'h',['s']);self.assertEqual(r['expert_count'],2)
            self.assertTrue(r['cases'][0]['requires_adjudication']);self.assertEqual(r['pairwise_agreement'][0]['observed_agreement'],0)
    def test_duplicate_expert_rejected(self):
        with TemporaryDirectory() as d:
            p=Path(d)/'a.json';p.write_text(json.dumps(self.export('a','ACCEPT')))
            with self.assertRaises(ValueError):analysis.analyze([p,p],'h',['s'])
    def test_wrong_catalog_rejected(self):
        with TemporaryDirectory() as d:
            p=Path(d)/'a.json';p.write_text(json.dumps(self.export('a','ACCEPT')))
            with self.assertRaises(ValueError):analysis.analyze([p],'wrong',['s'])
    def test_blind_builder_has_no_scoring_dependency(self):
        source=Path('expert/build_questionnaire.py').read_text()
        self.assertNotIn('load_oracle',source);self.assertNotIn('expected_decision',Path('expert/questionnaire.html').read_text())
