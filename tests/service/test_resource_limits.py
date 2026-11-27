"""Resource refusal must survive the real analyzer contract and short presentation."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from agent_graph.contracts import GraphError, Policy
from agent_graph.output_contracts import parse_document
from agent_service.analysis import view_from_result
from agent_service.core_analyzer import CoreAnalyzer
from agent_service.jira_presentation import summary_doc
from examples.agent_graph.fixture import create_fixture


class ResourceLimitsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.policy = create_fixture(self.root)
        data = self.policy.model_dump(); self.revisions = {}
        for repo in data['repositories']:
            def git(*args):
                return subprocess.check_output(['git','-C',repo['root'],*args],stderr=subprocess.DEVNULL,text=True).strip()
            git('init','-b','main'); git('add','.')
            git('-c','user.name=fixture','-c','user.email=fixture@example.invalid','commit','-m','fixture')
            self.revisions[repo['id']] = git('rev-parse','HEAD')
            repo.update(snapshot='git',revision=self.revisions[repo['id']])
        self.policy = Policy.model_validate(data)

    def analyzer(self, limits=None):
        data = self.policy.model_dump(); data.pop('limits')
        if limits is not None:data['limits'] = limits
        core = CoreAnalyzer(data, self.root/'state', code_version='limits-test')
        self.addCleanup(core.close)
        return core

    def request(self, core):
        return dict(schema='agent-graph-output',schema_version='2.0',kind='analysis_request',
            installation_id=self.policy.installation_id,environment=self.policy.environment,
            request_id='limit-request',trigger_kind='pr',source_event=dict(event_id='limit-event',resource_version='v1'),
            repository_revisions=dict(self.revisions),graph_version='graph-1',
            constitution_version=core.constitution_version,model_configuration_id=None,deadline='2026-11-16T12:00:00Z',
            access_scope=dict(view_id=core.policy.view_id(),repositories=[r.id for r in self.policy.repositories]),
            pr=dict(provider='github',repository='orders',pr_id=1,base_sha=self.revisions['orders'],head_sha=self.revisions['orders']))

    def test_service_materializes_the_expanded_working_profile_from_omitted_limits(self):
        core = self.analyzer()
        self.assertEqual((core.policy.limits.max_corpus_bytes,core.policy.limits.max_files,core.policy.limits.scan_seconds),
                         (8_000_000,2048,60.0))
        self.assertEqual(core.policy.limits.max_file_bytes,65_536)

    def test_old_explicit_profile_is_preserved(self):
        core = self.analyzer(dict(max_corpus_bytes=2_000_000,max_files=256,scan_seconds=15.0))
        self.assertEqual((core.policy.limits.max_corpus_bytes,core.policy.limits.max_files,core.policy.limits.scan_seconds),
                         (2_000_000,256,15.0))

    def test_actual_corpus_refusal_has_safe_diagnosis_in_result_and_short_comment(self):
        core = self.analyzer({'max_corpus_bytes':1}); request=self.request(core)
        raw=core.analyze(request,attachments={},cancelled=lambda:False)
        result=parse_document(raw)
        self.assertEqual((result.status,result.reason_code),('FAILED','budget_exhausted'))
        self.assertIn('объём', result.summary.lower())
        self.assertIn('1 байт', result.summary)
        self.assertIn('не выполнен', result.summary.lower())
        self.assertEqual(result.findings,[])
        self.assertNotIn(str(self.root),result.summary)
        view=view_from_result(raw,request)
        self.assertTrue(view.compatible)
        short=summary_doc(view,raw,kind='pr',gaps=[],earlier=[])
        self.assertIn('1 байт',short['status_line'])
        self.assertNotIn('internal_error',str(short))

    def test_file_time_and_inventory_refusals_are_not_internal_errors(self):
        for error,word in [('file_count_limit','число'),('scan_timeout','время'),('inventory_limit','обход')]:
            with self.subTest(error=error):
                core=self.analyzer(); graph,_,_=core._parts()
                with patch.object(graph,'prepare_context',side_effect=GraphError(error)):
                    raw=core.analyze(self.request(core),attachments={},cancelled=lambda:False)
                self.assertEqual((raw['status'],raw['reason_code']),('FAILED','budget_exhausted'))
                self.assertIn(word,raw['summary'].lower())
                self.assertNotIn(error,raw['summary'])

    def test_unknown_exception_code_is_not_echoed(self):
        core=self.analyzer();graph,_,_=core._parts()
        with patch.object(graph,'prepare_context',side_effect=GraphError('PRIVATE_CANARY_123')):
            raw=core.analyze(self.request(core),attachments={},cancelled=lambda:False)
        self.assertEqual(raw['reason_code'],'internal_error')
        self.assertNotIn('PRIVATE_CANARY',str(raw))

    def test_default_eight_megabyte_budget_counts_repeated_git_blobs_and_refuses(self):
        repo=self.root/'corpus/orders'
        for index in range(140):
            (repo/f'note-{index}.md').write_text('x'*60_000)
        subprocess.run(['git','-C',str(repo),'add','.'],check=True,capture_output=True)
        subprocess.run(['git','-C',str(repo),'-c','user.name=fixture','-c','user.email=fixture@example.invalid','commit','-m','large fixture'],check=True,capture_output=True)
        revision=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
        self.revisions['orders']=revision
        data=self.policy.model_dump(); data['repositories'][0]['revision']=revision
        self.policy=Policy.model_validate(data)
        core=self.analyzer(); raw=core.analyze(self.request(core),attachments={},cancelled=lambda:False)
        self.assertEqual((raw['status'],raw['reason_code']),('FAILED','budget_exhausted'))
        self.assertIn('8 000 000 байт',raw['summary'])
        self.assertEqual(raw['findings'],[])
        graph,_,_=core._parts()
        self.assertIsNone(graph.store.head(graph.view)[1])
