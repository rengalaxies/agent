"""Structural v2 binding regressions on real pinned output and counterexamples."""
import copy,unittest
from tests.performance.normalization_fixture import BindingFixture
from tools.impactmap_eval.normalizer import normalize_core

class BindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.single=BindingFixture();cls.merged=BindingFixture(('/orders','/invoices'))
        cls.removed=BindingFixture(replacement=False);cls.self_service=BindingFixture(self_service=True)
    @classmethod
    def tearDownClass(cls):
        for x in (cls.single,cls.merged,cls.removed,cls.self_service):x.close()
    def prediction(self,raw=None,fixture=None):
        x=fixture or self.single
        return normalize_core(copy.deepcopy(x.raw if raw is None else raw),x.case,x.registry,configuration='1'*64)
    def routes(self,p):return sorted(c['key']['route'] for c in p['candidates'])
    def test_real_replacement_uses_old_delta_in_every_formulation(self):
        p=self.prediction();self.assertTrue(p['output_valid'])
        self.assertEqual(self.routes(p),['/orders']);self.assertEqual(p['invalid_candidates'],[])
        self.assertTrue(all(w['phase']=='head' for c in p['candidates'] for w in c['witnesses']))
    def test_merged_current_edge_keeps_two_old_targets_and_isolated_call_lines(self):
        p=self.prediction(fixture=self.merged)
        self.assertEqual(self.routes(p),['/invoices','/orders']);self.assertEqual(p['invalid_candidates'],[])
        for c in p['candidates']:
            expected=2 if c['key']['route']=='/orders' else 3
            self.assertEqual({(w['line_start'],w['line_end']) for w in c['witnesses']},{(expected,expected)})
    def test_finding_without_explicit_old_proof_retains_unbound_instead_of_new_route(self):
        raw=copy.deepcopy(self.single.raw);raw.update(checks=[],claims=[])
        p=self.prediction(raw);self.assertEqual(p['candidates'],[]);self.assertEqual(len(p['invalid_candidates']),1)
    def test_wrong_service_method_or_scope_subject_is_not_guessed(self):
        for field,value in [('service','other'),('method','POST'),('environment','other')]:
            with self.subTest(field=field):
                raw=copy.deepcopy(self.single.raw)
                for c in raw['claims']:
                    if c['kind']=='hypothesis':c['subject'][field]=value
                p=self.prediction(raw);self.assertEqual(p['candidates'],[]);self.assertEqual(len(p['invalid_candidates']),1)
    def test_invalid_provider_hash_cannot_bless_an_explicit_old_target(self):
        raw=copy.deepcopy(self.single.raw);old=raw['deltas'][0]['operation']
        provider=raw['deltas'][0]['evidence_refs'][0]
        for e in raw['evidence']:
            if e['id']==provider:e['content_sha256']='0'*64
        raw['relationships'][0]['target']=old
        p=self.prediction(raw);self.assertEqual(p['candidates'],[]);self.assertEqual(len(p['invalid_candidates']),1)
    def test_unlinked_typed_subject_cannot_borrow_another_callsite_witness(self):
        raw=copy.deepcopy(self.merged.raw)
        # Switch one check's explicit hypothesis to the other call's evidence.
        risks=[c for c in raw['claims'] if c['kind']=='hypothesis']
        a,b=risks;original_line=2 if a['subject']['route']=='/orders' else 3;consumer_refs={e['id'] for e in raw['evidence'] if e['repository']=='c'}
        a['evidence_refs']=[r for r in a['evidence_refs'] if r not in consumer_refs]+[r for r in b['evidence_refs'] if r in consumer_refs]
        p=self.prediction(raw,fixture=self.merged)
        for c in p['candidates']:
            if c['key']['route']==a['subject']['route']:
                self.assertTrue(all(w['line_start']!=original_line for w in c['witnesses']))
        self.assertTrue(p['invalid_candidates'])
    def test_each_addressed_channel_works_without_findings(self):
        for channel in ('checks','claims','affected'):
            with self.subTest(channel=channel):
                raw=copy.deepcopy(self.single.raw);raw['findings']=[]
                if channel=='claims':raw['checks']=[];raw['affected']=[]
                elif channel=='checks':raw['affected']=[]
                # affected-only still retains claims as structural proof, not separate claims output.
                p=self.prediction(raw);self.assertEqual(self.routes(p),['/orders'])
                self.assertEqual(p['invalid_candidates'],[])
                self.assertTrue(any(ref.startswith('/'+channel+'/') for c in p['candidates'] for ref in c['raw_refs']))
    def test_off_delta_calls_are_unbound_in_actual_pr(self):
        raw=copy.deepcopy(self.removed.raw);raw['deltas'][0]['operation']['route']='/unrelated'
        p=self.prediction(raw,fixture=self.removed)
        self.assertEqual(p['candidates'],[]);self.assertEqual(len(p['invalid_candidates']),1)
    def test_no_delta_pr_does_not_invent_a_changed_target(self):
        raw=copy.deepcopy(self.removed.raw);raw['deltas']=[]
        p=self.prediction(raw,fixture=self.removed);self.assertEqual(p['candidates'],[]);self.assertTrue(p['invalid_candidates'])
    def test_regular_removed_target_still_binds_without_subject(self):
        p=self.prediction(fixture=self.removed);self.assertEqual(self.routes(p),['/orders'])
    def test_malformed_first_entry_does_not_erase_later_warning(self):
        raw=copy.deepcopy(self.single.raw);raw['findings'].insert(0,None)
        p=self.prediction(raw);self.assertFalse(p['output_valid']);self.assertEqual(self.routes(p),['/orders'])
    def test_historical_or_wrong_hash_call_is_never_upgraded_to_head_witness(self):
        raw=copy.deepcopy(self.single.raw)
        for e in raw['evidence']:
            if e['repository']=='c':e['content_sha256']='0'*64
        p=self.prediction(raw)
        self.assertTrue(p['candidates'] or p['invalid_candidates'])
        self.assertFalse(any(c['witnesses'] for c in p['candidates']))
        self.assertTrue(any(l['code']=='invalid_citation' for l in p['limitations']))
    def test_old_consumer_commit_cannot_borrow_current_witness_for_another_target(self):
        raw=copy.deepcopy(self.merged.raw)
        for e in raw['evidence']:
            if e['repository']=='c' and e['start_line']==3 and e['end_line']==3:e['commit']='f'*40
        p=self.prediction(raw,fixture=self.merged)
        by_route={c['key']['route']:c for c in p['candidates']}
        self.assertEqual(set(by_route),{'/orders','/invoices'})
        self.assertEqual(by_route['/invoices']['witnesses'],[])
        self.assertEqual({w['line_start'] for w in by_route['/orders']['witnesses']},{2})
        self.assertTrue(any(l['code']=='invalid_citation' for l in p['limitations']))
    def test_check_for_another_consumer_cannot_relabel_current_call(self):
        raw=copy.deepcopy(self.single.raw)
        for check in raw['checks']:check['consumer']['service']='other'
        p=self.prediction(raw)
        self.assertEqual(p['candidates'],[])
        self.assertEqual({c['consumer_designation'] for c in p['invalid_candidates']},{'service:c','unmapped:other'})
    def test_missing_provider_support_is_not_rescued_by_a_convenient_relationship(self):
        raw=copy.deepcopy(self.single.raw);provider_ids={e['id'] for e in raw['evidence'] if e['repository']=='p'}
        for claim in raw['claims']:
            if claim['subject']:claim['evidence_refs']=[r for r in claim['evidence_refs'] if r not in provider_ids]
        raw['relationships'][0]['target']=raw['deltas'][0]['operation']
        p=self.prediction(raw);self.assertEqual(p['candidates'],[]);self.assertTrue(p['invalid_candidates'])
    def test_malformed_check_does_not_hide_an_orphan_addressed_claim(self):
        raw=copy.deepcopy(self.single.raw);raw['findings']=[];raw['affected']=[]
        for check in raw['checks']:check['consumer']=None
        p=self.prediction(raw);self.assertFalse(p['output_valid']);self.assertEqual(self.routes(p),['/orders'])
    def test_explicit_check_subject_can_bind_when_calls_edge_is_missing(self):
        raw=copy.deepcopy(self.single.raw);raw.update(findings=[],affected=[],relationships=[])
        p=self.prediction(raw);self.assertEqual(self.routes(p),['/orders']);self.assertFalse(p['invalid_candidates'])
    def test_preliminary_named_relationship_without_delta_is_retained(self):
        raw=copy.deepcopy(self.removed.raw);raw.update(trigger_kind='jira',deltas=[],findings=[],checks=[],claims=[])
        p=self.prediction(raw,fixture=self.removed);self.assertEqual(self.routes(p),['/orders'])

    def test_off_delta_alternative_cannot_be_pruned_to_force_finding_binding(self):
        raw=copy.deepcopy(self.removed.raw)
        other=copy.deepcopy(raw['relationships'][0]);other['id']='rel:other';other['target']['route']='/unrelated'
        raw['relationships'].append(other);raw['affected'][0]['relationship_refs'].append(other['id'])
        p=self.prediction(raw,fixture=self.removed)
        self.assertTrue(any('/findings/0' in c['raw_refs'] for c in p['invalid_candidates']))
        self.assertFalse(any('/findings/0' in c['raw_refs'] for c in p['candidates']))

    def test_same_service_provider_declarations_are_not_caller_witnesses(self):
        p=self.prediction(fixture=self.self_service)
        self.assertEqual(self.routes(p),['/orders'])
        self.assertEqual({w['repository'] for c in p['candidates'] for w in c['witnesses']},{'c'})
        self.assertEqual({w['line_start'] for c in p['candidates'] for w in c['witnesses']},{2})
    def test_same_service_without_caller_role_does_not_borrow_provider_quotes(self):
        raw=copy.deepcopy(self.self_service.raw);raw['findings']=[]
        p=self.prediction(raw,fixture=self.self_service)
        self.assertTrue(p['candidates'] or p['invalid_candidates'])
        self.assertFalse(any(c['witnesses'] for c in p['candidates']))

    def test_contradictory_caller_blob_is_invalid_and_cannot_score_strict_tp(self):
        from tests.performance.test_evaluation_tooling import reference
        from tools.impactmap_eval.scoring import score_case
        raw=copy.deepcopy(self.single.raw)
        for e in raw['evidence']:
            if e['repository']=='c':e['blob']='0'*40
        p=self.prediction(raw)
        self.assertFalse(any(c['witnesses'] for c in p['candidates']))
        self.assertTrue(any(l['code']=='invalid_citation' for l in p['limitations']))
        # Synthetic scorer guard only, not a semantic/expert label for replacement.
        gold=reference();gold['case_id']=self.single.case['case_id'];gold['keys'][0]['key']['route']='/orders'
        commit=next(r['head_sha'] for r in self.single.case['repositories'] if r['repository_id']=='c')
        gold['keys'][0]['witnesses']=[self.single.registry.witness('c','head',commit,'client.py',2,2)]
        self.assertEqual(score_case(p,gold,self.single.registry,development=True)['strict']['tp'],0)

    def test_conflicting_direct_claims_on_one_anchor_are_unbound(self):
        raw=copy.deepcopy(self.merged.raw);claims=[c for c in raw['claims'] if c['kind']=='hypothesis']
        refs={e['id'] for e in raw['evidence'] if e['repository']=='c'}
        shared=next(r for r in claims[0]['evidence_refs'] if r in refs)
        for claim in claims:claim['evidence_refs']=[r for r in claim['evidence_refs'] if r not in refs]+[shared]
        check=copy.deepcopy(raw['checks'][0]);check['claim_refs']=[c['id'] for c in claims]
        raw.update(findings=[],affected=[],claims=claims,checks=[check])
        p=self.prediction(raw,fixture=self.merged)
        self.assertEqual(p['candidates'],[]);self.assertEqual(len(p['invalid_candidates']),1)
        self.assertIn('/checks/0',p['invalid_candidates'][0]['raw_refs'])

    def test_direct_conflict_does_not_discard_independent_valid_anchor(self):
        x=BindingFixture(('/orders','/invoices','/orders'));self.addCleanup(x.close)
        raw=copy.deepcopy(x.raw);evidence={e['id']:e for e in raw['evidence']}
        claims=[c for c in raw['claims'] if c['kind']=='hypothesis']
        call=lambda c:next(r for r in c['evidence_refs'] if evidence[r]['repository']=='c')
        shared=next(call(c) for c in claims if evidence[call(c)]['start_line']==2)
        for claim in claims:
            if claim['subject']['route']=='/invoices':claim['evidence_refs']=[r for r in claim['evidence_refs'] if evidence[r]['repository']!='c']+[shared]
        check=copy.deepcopy(raw['checks'][0]);check['claim_refs']=[c['id'] for c in claims]
        raw.update(findings=[],affected=[],claims=claims,checks=[check])
        p=self.prediction(raw,fixture=x)
        self.assertEqual(self.routes(p),['/orders']);self.assertTrue(p['invalid_candidates'])
        self.assertEqual({w['line_start'] for c in p['candidates'] for w in c['witnesses']},{4})

    def test_named_affected_without_usable_refs_is_not_dropped(self):
        for value in ([],None,[None,{}]):
            with self.subTest(value=value):
                raw=copy.deepcopy(self.single.raw);raw.update(findings=[],checks=[],claims=[])
                raw['affected'][0]['relationship_refs']=value
                p=self.prediction(raw);self.assertEqual(len(p['invalid_candidates']),1)
                self.assertIn('/affected/0',p['invalid_candidates'][0]['raw_refs'])

    def test_malformed_repository_metadata_does_not_erase_addressed_warnings(self):
        for value in ([],{},1):
            for field in ('unused','caller','provider'):
                with self.subTest(value=value,field=field):
                    raw=copy.deepcopy(self.single.raw)
                    if field=='unused':raw['evidence'].insert(0,dict(id='bad',origin='code',repository=value))
                    else:
                        e=next(e for e in raw['evidence'] if e['repository']==('c' if field=='caller' else 'p'))
                        e['repository']=value
                    p=self.prediction(raw)
                    self.assertFalse(p['output_valid']);self.assertTrue(p['candidates'] or p['invalid_candidates'])

class VersionTests(unittest.TestCase):
    def test_v2_freeze_identifies_protocol_and_rejects_old_normalization_version(self):
        from tools.impactmap_eval.common import EVAL,sha
        from tools.impactmap_eval.registration import components,candidate_freeze,readiness
        identity=components()
        self.assertEqual(identity['normalization_version'],'impactmap-normalization-2')
        self.assertEqual(identity['protocol_sha256'],sha((EVAL/'protocol-v2.md').read_bytes()))
        self.assertNotEqual(identity['protocol_sha256'],sha((EVAL/'protocol-v1.md').read_bytes()))
        frozen=candidate_freeze();self.assertEqual(frozen['normalization_version'],identity['normalization_version'])
        frozen['normalization_version']='impactmap-normalization-1'
        self.assertIn('normalization_version',readiness(frozen)['missing'])
