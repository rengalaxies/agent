import copy
import json
from pathlib import Path
import tempfile
import unittest
from tools.impactmap_eval import scoring
from tools.impactmap_eval.common import digest,sha

KEY=dict(provider_service='p',method='GET',route='/items',consumer_service='c')
W=dict(repository='c',phase='head',commit='1'*40,path='client.py',line_start=2,line_end=2,quote_sha256=sha(b'call()'))

class Source:
    repos={'c':{'service':'c'}}
    def valid(self,w):return w==W


def prediction(candidates=None,valid=True):
    return dict(schema_version='impactmap-normalized-prediction-1.0',lifecycle='complete',case_id='DEV',method='impactmap_static',
        attempt=dict(id=1,kind='primary'),configuration_sha256='1'*64,raw_artifact_sha256='2'*64,output_valid=valid,status='USEFUL',error_code=None,
        candidates=candidates or [],invalid_candidates=[],limitations=[],explicit_claims=dict(compatibility_confirmed=False,tests_executed=False,no_consumers=False))


def candidate(w=W,key=KEY):return dict(key=key,witnesses=[copy.deepcopy(w)] if w else [],raw_refs=['/findings/0'],notes='test')

def reference():
    return dict(schema_version='impactmap-reference-label-1.0',lifecycle='draft',case_id='DEV',stage='adjudicated',expert_id=None,completed_at=None,
        profile=dict(membership='IN_PROFILE',boundary='none',rationale='synthetic only'),
        keys=[dict(key=KEY,label='AFFECTED',rationale='synthetic fixture',expectation=dict(description='fixture',artifact_ref='fixture',artifact_sha256='3'*64,basis='expert_contract_witness'),witnesses=[W])],
        scope_completeness=dict(search_complete=True,inventory_sha256='4'*64,rationale='synthetic'),source_labels=[],disagreements=[],
        attestation=dict(confirmed_by_human=False,independent_before_outputs=False,conflicts_of_interest='No humans; unit fixture'))


class ScoringTests(unittest.TestCase):
    def score(self,p,g=None):return scoring.score_case(p,g or reference(),Source(),development=True)
    def test_exact_pair_and_source_witness_required(self):
        self.assertEqual(self.score(prediction([candidate()]))['strict'],dict(tp=1,fp=0,fn=0))
        wrong={**W,'phase':'base'}
        r=self.score(prediction([candidate(wrong)]));self.assertEqual(r['strict'],dict(tp=0,fp=1,fn=1))
        self.assertEqual(r['identity'],dict(tp=1,fp=0,fn=0))
    def test_invalid_output_keeps_candidates_but_never_true_positive(self):
        self.assertEqual(self.score(prediction([candidate()],valid=False))['strict'],dict(tp=0,fp=1,fn=1))
    def test_duplicate_bundles_do_not_increase_counts(self):
        r=self.score(prediction([candidate(),candidate()]));self.assertEqual(r['strict']['tp'],1);self.assertGreater(r['duplicates'],0)
    def test_unbound_bucket_deduplicates_by_consumer_not_arbitrary_id(self):
        p=prediction();p['invalid_candidates']=[dict(candidate_id='a'*64,consumer_designation='service:c',raw_refs=['x'],reason='ambiguous')]*3
        self.assertEqual(self.score(p)['strict'],dict(tp=0,fp=1,fn=1))
    def test_empty_is_na_precision_and_all_gold_fn(self):
        r=self.score(prediction());self.assertEqual(r['strict'],dict(tp=0,fp=0,fn=1))
        self.assertIsNone(scoring.metrics(r['strict'])['precision']);self.assertEqual(scoring.metrics(r['strict'])['recall'],0)
    def test_unseen_plausible_key_requests_gold_audit(self):
        r=self.score(prediction([candidate(key={**KEY,'route':'/new'})]));self.assertTrue(r['gold_audit_required'])
    def test_diagnostic_attempt_cannot_replace_primary(self):
        p=prediction([candidate()]);p['attempt']['kind']='diagnostic'
        with self.assertRaisesRegex(ValueError,'primary'):self.score(p)
    def test_unsigned_labels_rejected_outside_development(self):
        with self.assertRaises(ValueError):scoring.score_case(prediction(),reference(),Source())
    def test_far_denominator_is_negative_cases_not_all40(self):
        records=[];catalogue=[]
        for i in range(40):
            cid='C'+str(i);p=prediction([candidate()] if i in (20,21) else []);p['case_id']=cid
            g=reference();g['case_id']=cid
            if i>=20:g['keys'][0]['label']='UNAFFECTED'
            r=scoring.score_case(p,g,Source(),development=True);records.append(r)
            stratum='BREAKING_IN_PROFILE' if i<20 else ('COMPATIBLE_IN_PROFILE' if i<30 else ('NO_CONSUMERS_IN_PROFILE' if i<34 else 'OUT_OF_PROFILE'))
            catalogue.append(dict(case_id=cid,stratum=stratum,origin_group='family',provenance='controlled_author',split='development'))
        a=scoring.aggregate(records,catalogue)
        self.assertEqual(a['false_alert_cases'],2);self.assertEqual(a['negative_cases'],14)
        self.assertEqual(a['false_alert_case_rate'],2/14);self.assertEqual(a['decision'],'NOT_REGISTERED')

class NormalizerTests(unittest.TestCase):
    def test_findings_bind_to_callsite_not_delta_cartesian_product(self):
        from tools.impactmap_eval.normalizer import normalize_core
        class R(Source):
            sources={('c','head','1'*40,'client.py'):dict(repository='c',path='client.py',commit='1'*40,text='x\ncall()\n',sha256=sha(b'x\ncall()\n'))}
            def witness(self,*a):return copy.deepcopy(W)
        evidence=[dict(id='e',origin='code',repository='c',commit='1'*40,path='client.py',start_line=2,end_line=2,content_sha256=sha(b'x\ncall()\n'))]
        rel=lambda route,ev:dict(id=route,kind='calls',source=dict(service='c'),target=dict(kind='operation',service='p',method='GET',route=route),evidence_refs=ev)
        raw=dict(status='PARTIAL',findings=[dict(consumer=dict(service='c'),callsite=dict(repository='c',path='client.py',line=2),evidence_refs=['e'])],
                 deltas=[dict(operation=dict(service='p',method='GET',route='/one')),dict(operation=dict(service='p',method='GET',route='/two'))],
                 relationships=[rel('/one',['e']),rel('/two',['other'])],evidence=evidence,checks=[],claims=[],affected=[],gaps=[])
        p=normalize_core(raw,{'case_id':'DEV'},R(),configuration='1'*64)
        self.assertEqual([x['key']['route'] for x in p['candidates']],['/one'])
        raw['relationships'][1]['evidence_refs']=['e']
        p=normalize_core(raw,{'case_id':'DEV'},R(),configuration='1'*64)
        self.assertEqual(len(p['invalid_candidates']),1);self.assertFalse(p['candidates'])
    def test_affected_without_finding_is_still_a_candidate(self):
        from tools.impactmap_eval.normalizer import normalize_core
        raw=dict(status='PARTIAL',findings=[],checks=[],claims=[],deltas=[],evidence=[],gaps=[],
                 relationships=[dict(id='r',kind='calls',source=dict(service='c'),target=dict(kind='operation',service='p',method='GET',route='/items'),evidence_refs=[])],
                 affected=[dict(service=dict(service='c'),relationship_refs=['r'])])
        p=normalize_core(raw,{'case_id':'DEV'},Source(),configuration='1'*64)
        self.assertEqual(len(p['candidates']),1)
    def test_unbound_id_exact_nfc_whitespace_and_refs_preserved(self):
        from tools.impactmap_eval.normalizer import unbound
        a=unbound('CASE','  name  x  ',['a','b'],mapped=False)
        self.assertEqual(a['consumer_designation'],'unmapped:name x')
        import hashlib
        expected=hashlib.sha256(json.dumps(['CASE','unmapped:name x','UNBOUND'],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        self.assertEqual(a['candidate_id'],expected)

class RunnerTests(unittest.TestCase):
    def test_empty_hints_do_not_invent_search_query(self):
        from tools.impactmap_eval.runner import lexical
        class RegistryStub:
            sources={};gaps=[];provider='p'
        with tempfile.TemporaryDirectory() as t:
            p,raw=lexical({'case_id':'DEV','operation_hints':[]},RegistryStub(),Path(t),'1'*64)
        self.assertEqual(p['status'],'ABSTAINED');self.assertEqual(p['candidates'],[])
        self.assertEqual(raw['reason'],'query_not_identified')
    def test_readme_lexical_hit_is_retained_without_ast_filter(self):
        from tools.impactmap_eval.runner import lexical
        class R:
            provider='p';gaps=[]
            sources={('c','head','1'*40,'README.md'):dict(service='c',text='mention /items only\n')}
            def witness(self,repo,phase,commit,path,start,end):return dict(repository=repo,phase=phase,commit=commit,path=path,line_start=start,line_end=end,quote_sha256=sha(b'mention /items only'))
        with tempfile.TemporaryDirectory() as t:
            p,raw=lexical({'case_id':'DEV','operation_hints':[dict(provider_service='p',method='GET',route='/items')]},R(),Path(t),'1'*64)
        self.assertEqual(len(p['candidates']),1);self.assertEqual(p['candidates'][0]['witnesses'][0]['path'],'README.md')
        self.assertEqual(raw['runs'][0]['exit_code'],0)
    def test_unregistered_run_cannot_be_mislabelled_heldout(self):
        from tools.impactmap_eval.runner import run_method
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaisesRegex(ValueError,'registration'):
                run_method('unused','unused','impactmap_static',Path(t)/'out')

class RegistrationTests(unittest.TestCase):
    def test_empty_freeze_is_not_registered_and_never_fills_humans(self):
        from tools.impactmap_eval.registration import readiness,candidate_freeze
        f=candidate_freeze();r=readiness(f)
        self.assertEqual(r['status'],'NOT_REGISTERED');self.assertIn('case_ids',r['missing'])
        self.assertFalse(f['experts']);self.assertIsNone(f['curator']);self.assertIsNone(f['thresholds']['approved_by'])
    def test_authored_diagnostics_cannot_become_independent_success(self):
        from tools.impactmap_eval.registration import decision
        r=dict(decision='NOT_REGISTERED',per_case=[dict(development=True)])
        self.assertEqual(decision(r,{'status':'REGISTERED_READY'},{}),'NOT_REGISTERED')

    def test_statement_containment_not_arbitrary_line_tolerance(self):
        from tools.impactmap_eval.scoring import _inside
        accepted={**W,'line_start':2,'line_end':4}
        self.assertTrue(_inside({**W,'line_start':3,'line_end':3},accepted))
        self.assertFalse(_inside({**W,'line_start':1,'line_end':3},accepted))

class BoundaryTests(unittest.TestCase):
    def test_generic_limitation_does_not_pass_outside_profile_boundary(self):
        p=prediction();p['status']='ABSTAINED';p['limitations']=[dict(code='requirement_unknown',scope='consumer')]
        g=reference();g['profile'].update(membership='OUT_OF_PROFILE',boundary='access')
        r=scoring.score_case(p,g,Source(),development=True);self.assertFalse(r['limited_result_success'])
    def test_known_access_gap_can_pass_boundary_without_success_claims(self):
        p=prediction();p['status']='PARTIAL';p['limitations']=[dict(code='commit_unavailable',scope='consumer')]
        g=reference();g['profile'].update(membership='OUT_OF_PROFILE',boundary='access')
        self.assertTrue(scoring.score_case(p,g,Source(),development=True)['limited_result_success'])
    def test_invalid_gold_is_detected_even_for_empty_output(self):
        g=reference();g['keys'][0]['witnesses'][0]={**W,'quote_sha256':'a'*64}
        self.assertTrue(scoring.score_case(prediction(),g,Source(),development=True)['gold_audit_required'])

class OutsideAccountingTests(unittest.TestCase):
    def test_outside_does_not_invent_zero_false_negatives(self):
        g=reference();g['profile'].update(membership='OUT_OF_PROFILE',boundary='access')
        r=scoring.score_case(prediction(),g,Source(),development=True)
        self.assertIsNone(r['strict']);self.assertFalse(r['primary_eligible'])

class ReviewRegressionTests(unittest.TestCase):
    def test_failed_and_superseded_outputs_never_primary_tp(self):
        for status in ('FAILED','SUPERSEDED'):
            p=prediction([candidate()]);p['status']=status
            self.assertEqual(scoring.score_case(p,reference(),Source(),development=True)['strict'],dict(tp=0,fp=1,fn=1))
    def test_leak_cannot_also_receive_boundary_success(self):
        p=prediction([candidate({**W,'repository':'forbidden'})]);p['status']='PARTIAL';p['limitations']=[dict(code='commit_unavailable',scope='c')]
        g=reference();g['profile'].update(membership='OUT_OF_PROFILE',boundary='access')
        r=scoring.score_case(p,g,Source(),development=True)
        self.assertTrue(r['access_leak']);self.assertFalse(r['limited_result_success'])
    def test_unused_raw_evidence_outside_rights_is_a_leak(self):
        from tools.impactmap_eval.normalizer import normalize_core
        raw=dict(status='ABSTAINED',evidence=[dict(id='unused',origin='code',repository='forbidden',path='secret.py',commit='1'*40)],findings=[],checks=[],claims=[],relationships=[],affected=[],gaps=[])
        p=normalize_core(raw,{'case_id':'DEV'},Source(),configuration='1'*64)
        self.assertTrue(any(l['code']=='access_leak_detected' for l in p['limitations']))
    def test_malformed_entry_does_not_erase_later_addressed_candidate(self):
        from tools.impactmap_eval.normalizer import normalize_core
        raw=dict(status='PARTIAL',findings=[dict(consumer=None)],checks=[],claims=[],deltas=[],evidence=[],gaps=[],
                 relationships=[dict(id='r',kind='calls',source=dict(service='c'),target=dict(kind='operation',service='p',method='GET',route='/items'),evidence_refs=[])],
                 affected=[dict(service=dict(service='c'),relationship_refs=['r'])])
        p=normalize_core(raw,{'case_id':'DEV'},Source(),configuration='1'*64)
        self.assertFalse(p['output_valid']);self.assertEqual(len(p['candidates']),1)
    def test_one_frozen_ledger_rejects_primary_reset_and_out_of_order(self):
        from tools.impactmap_eval.registration import claim_attempt
        with tempfile.TemporaryDirectory() as t:
            f=dict(attempt_ledger_ref=str(Path(t)/'ledger.sqlite3'),method_case_order=[dict(case_id='A',method='impactmap_static',attempt_id=1),dict(case_id='A',method='lexical_search_ls1',attempt_id=1)])
            with self.assertRaises(ValueError):claim_attempt(f,'A','lexical_search_ls1')
            claim_attempt(f,'A','impactmap_static')
            with self.assertRaisesRegex(ValueError,'assigned'):claim_attempt(f,'A','impactmap_static')

class PacketIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tools.prepare_impactmap_corpora import generate_corpus
        from tools.impactmap_eval.common import EVAL,Registry,read,write
        from tools.impactmap_eval.packets import curator_manifest,write_packet
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        generated=generate_corpus(cls.root/'git',repositories=5,python_lines=300)
        policy=copy.deepcopy(generated['policy'])
        for repo in policy['repositories']:repo['root']=str(cls.root/'git'/repo['root'])
        cls.policy=policy;write(cls.root/'policy.json',policy)
        case=read(EVAL/'templates/case-input.template.json');case.update(lifecycle='ready',case_id='DEV-UNIT',task='Review GET /items/0',operation_hints=[],
            repositories=[dict(repository_id=r['id'],service=r['service'],role='provider' if r['id']=='r00' else 'consumer',source_ref=r['id'],base_sha=generated['base_revisions'][r['id']],head_sha=generated['scenarios']['baseline']['head_revisions'][r['id']],tree_sha256='0'*64,read_authorized=True) for r in policy['repositories']],
            policy_sha256=sha((cls.root/'policy.json').read_bytes()),budget=dict(wall_time_cap_seconds=60,freeze_manifest_ref='DEVELOPMENT'))
        registry=Registry(case,policy)
        for repo in case['repositories']:
            snapshots=[('base',repo['base_sha']),('head',repo['head_sha'])] if repo['role']=='provider' else [('head',repo['head_sha'])]
            path=next(r['root'] for r in policy['repositories'] if r['id']==repo['repository_id'])
            rows=curator_manifest(path,snapshots);repo['tree_sha256']=sha(json.dumps(rows,ensure_ascii=False,separators=(',',':')).encode())
        case['input_packet_sha256']=write_packet(cls.root/'input-packet.tar',case,(cls.root/'policy.json').read_bytes(),registry)
        write(cls.root/'case.json',case);cls.case=case
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_archive_bytes_and_full_tracked_manifest_match_guide(self):
        from tools.impactmap_eval.common import load_input,packet_hash
        from tools.impactmap_eval.packets import curator_manifest
        c,p,r=load_input(self.root/'case.json',self.root/'policy.json')
        self.assertEqual(packet_hash(self.root/'input-packet.tar'),c['input_packet_sha256'])
        repo=c['repositories'][0]
        rows=curator_manifest(p['repositories'][0]['root'],[('base',repo['base_sha']),('head',repo['head_sha'])])
        self.assertTrue(all(len(x)==6 and x[3]=='100644' and x[4]=='blob' for x in rows))
        self.assertEqual(repo['tree_sha256'],sha(json.dumps(rows,ensure_ascii=False,separators=(',',':')).encode()))
    def test_packet_with_added_label_file_is_refused_even_if_hash_updated(self):
        import io,tarfile
        from tools.impactmap_eval.common import load_input,write
        target=self.root/'tampered';target.mkdir()
        (target/'input-packet.tar').write_bytes((self.root/'input-packet.tar').read_bytes())
        with tarfile.open(target/'input-packet.tar','a') as archive:
            raw=b'gold';info=tarfile.TarInfo('reference-label.json');info.size=len(raw);archive.addfile(info,io.BytesIO(raw))
        c=copy.deepcopy(self.case);c['input_packet_sha256']=sha((target/'input-packet.tar').read_bytes());write(target/'case.json',c)
        with self.assertRaisesRegex(ValueError,'unexpected_packet_entries'):load_input(target/'case.json',self.root/'policy.json')
    def test_denied_repository_is_refused_before_any_collect(self):
        from tools.impactmap_eval import common
        from unittest.mock import patch
        c=copy.deepcopy(self.case);c['repositories'][1]['read_authorized']=False
        with patch.object(common,'collect') as collect:
            with self.assertRaisesRegex(ValueError,'authorization'):common.Registry(c,self.policy)
            collect.assert_not_called()
    def test_timeout_keeps_immutable_attempt_envelope_and_no_overwrite(self):
        from tools.impactmap_eval import runner
        from unittest.mock import patch
        import subprocess
        out=self.root/'timeout'
        with patch.object(runner.subprocess,'run',side_effect=subprocess.TimeoutExpired(['worker'],60,output='partial stdout',stderr='partial stderr')):
            receipt=runner.run_method(self.root/'case.json',self.root/'policy.json','impactmap_static',out,development=True)
        raw=json.loads((out/'raw.json').read_text());p=json.loads((out/'normalized.json').read_text())
        self.assertEqual(raw['error_code'],'wall_time_cap_exceeded');self.assertIn('started_at',raw);self.assertEqual(raw['stdout'],'partial stdout');self.assertEqual(raw['stderr'],'partial stderr')
        self.assertEqual(p['raw_artifact_sha256'],sha((out/'raw.json').read_bytes()));self.assertFalse(p['output_valid'])
        with self.assertRaises(FileExistsError):runner.run_method(self.root/'case.json',self.root/'policy.json','impactmap_static',out,development=True)
    def test_real_core_packet_smoke_without_reference_access(self):
        from tools.impactmap_eval.runner import run_method
        out=self.root/'real-core';r=run_method(self.root/'case.json',self.root/'policy.json','impactmap_static',out,development=True)
        self.assertIsNone(r['error_code']);self.assertFalse(r['gold_received']);self.assertTrue(r['input_validated'])
        self.assertEqual(len(json.loads((out/'normalized.json').read_text())['candidates']),3)


class FreezeCompletenessTests(unittest.TestCase):
    def test_missing_mandatory_freeze_controls_are_reported(self):
        from tools.impactmap_eval.registration import candidate_freeze,readiness
        f=candidate_freeze();f.update(environment={},random_seed=None,primary_attempt_rule='pick_best')
        f['budgets']['retry_policy_sha256']=None;f['baseline']['argv_policy_sha256']=None;f['thresholds']['approved_at']='anything'
        missing=readiness(f)['missing']
        for key in ('environment','random_seed','primary_attempt_rule','retry_policy','baseline_argv_policy','threshold_approval_date'):
            self.assertIn(key,missing)

class HumanAuditGateTests(unittest.TestCase):
    def test_structural_registration_alone_cannot_certify_gold_and_prose(self):
        from tools.impactmap_eval.registration import decision
        r=dict(per_case=[dict(development=False)],protocol_issues=[],gold_audits=0,manual_audits=0,precision=1,recall=1,false_alert_case_rate=0,
               strict=dict(tp=20,fp=0,fn=0),false_alert_cases=0,negative_cases=14,technical_errors_supported=0,outside_boundary_success=6,outside_cases=6,access_leaks=0,false_certainty=0)
        t=dict(strict_recall_min=.9,strict_precision_min=.85,negative_case_far_max=.1)
        self.assertEqual(decision(r,{'status':'REGISTERED_READY'},t),'INDETERMINATE')
    def test_raw_unused_excluded_path_inside_allowed_repository_is_detected(self):
        from tools.impactmap_eval.normalizer import normalize_core
        class Scope(Source):sources={('c','head','1'*40,'client.py'):dict(text='call()')}
        raw=dict(status='ABSTAINED',evidence=[dict(id='unused',origin='code',repository='c',commit='1'*40,path='excluded/private.py')])
        p=normalize_core(raw,{'case_id':'DEV'},Scope(),configuration='1'*64)
        self.assertTrue(any(x['code']=='access_leak_detected' for x in p['limitations']))

class OutsideAuditTests(unittest.TestCase):
    def test_visible_warning_in_O_is_not_a_defect_of_primary_gold(self):
        g=reference();g['keys']=[];g['profile'].update(membership='OUT_OF_PROFILE',boundary='grammar')
        r=scoring.score_case(prediction([candidate()]),g,Source(),development=True)
        self.assertFalse(r['gold_audit_required']);self.assertIsNone(r['strict'])
        self.assertEqual(r['predicted_count'],1)

class CuratorSideTests(unittest.TestCase):
    def test_author_draft_cannot_pass_closed_gold_verifier(self):
        from tools.impactmap_eval.curator import verify_reference
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'author.json';p.write_text(json.dumps(reference()))
            with self.assertRaisesRegex(ValueError,'complete_human_gold'):
                verify_reference(t,p,gold_frozen_at='2026-11-14T10:00:00Z',first_output_at='2026-11-14T11:00:00Z',registry=Source())
    def test_closed_reference_path_escape_is_refused_without_read(self):
        from tools.impactmap_eval.curator import _artifact
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaisesRegex(ValueError,'outside_root'):_artifact(t,'../other.json','a'*64)
