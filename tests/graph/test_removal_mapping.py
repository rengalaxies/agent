"""A removed declaration needs current caller evidence, not unconditional base callers."""
from pathlib import Path
import tempfile
import unittest

from agent_graph.engine import Graph
from agent_graph.results import change_result
from agent_graph.output_contracts import parse_document
from agent_graph.store import Store
from examples.agent_graph.fixture import create_fixture

API = 'from fastapi import FastAPI\napp = FastAPI()\n@app.get("/orders")\ndef orders():\n    return []\n'
EMPTY_API = 'from fastapi import FastAPI\napp = FastAPI()\n'
CALL = 'import requests\nrequests.get("https://orders.test/orders")\n'


class RemovalMappingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.policy = create_fixture(self.root)
        self.store = Store(self.root / 'state')
        self.addCleanup(self.store.close)
        self.graph = Graph(self.policy, self.store)
        self.api = self.root / 'corpus/orders/api.py'
        self.client = self.root / 'corpus/reporting/client.py'
        self.api.write_text(API)
        self.client.write_text(CALL)
        for name in ('export', 'health'):
            (self.root / 'corpus' / name / 'client.py').write_text('value = 1\n')

    def compare(self, before=CALL, after=CALL, *, api=API):
        self.api.write_text(api)
        self.client.write_text(before)
        base = self.graph.prepare_context()
        self.api.write_text(EMPTY_API)
        self.client.write_text(after)
        analysis = self.graph.analyze_change(base['id'])
        return base, analysis

    def result(self, analysis):
        request = parse_document(dict(schema='agent-graph-output', schema_version='2.0', kind='analysis_request',
            installation_id=self.policy.installation_id, environment=self.policy.environment,
            request_id='removed', trigger_kind='pr', source_event=dict(event_id='event', resource_version='v1'),
            repository_revisions={r.id: 'b'*40 for r in self.policy.repositories}, graph_version='graph-1',
            constitution_version='agent-service-v1.0:test', model_configuration_id=None, deadline='2026-11-16T12:00:00Z',
            access_scope=dict(view_id=self.graph.view, repositories=[r.id for r in self.policy.repositories]),
            pr=dict(provider='github', repository='orders', pr_id=1, base_sha='a'*40, head_sha='b'*40)))
        return change_result(self.graph, request, analysis, code_version='removed-test',
            constitution_version='agent-service-v1.0:test', correlation_id='removed-test')

    def test_existing_call_is_verified_at_head_while_head_only_scan_stays_partial(self):
        base, analysis = self.compare()
        self.assertEqual([f['dependency_freshness'] for f in analysis['findings']], ['CURRENT'])
        head = self.graph.context(analysis['context_used_id'])
        self.assertEqual(head['coverage'], 'PARTIAL')
        self.assertEqual([g['code'] for g in head['graph']['gaps']], ['unmapped_call'])
        self.assertEqual(analysis['gaps'], [])
        self.assertEqual(len(analysis['resolved_removed_calls']), 1)
        self.assertEqual(analysis['coverage'], 'COMPLETE_WITHIN_PROFILE')
        self.assertEqual(self.graph.context(base['id']), base)
        self.assertEqual(self.graph.context(head['id']), head)
        result = self.result(analysis)
        self.assertEqual([f.code for f in result.findings], ['OPERATION_REMOVED'])
        self.assertEqual(result.gaps, [])
        self.assertEqual([r.status for r in result.relationships], ['ACTIVE'])

    def test_new_head_consumer_of_removed_operation_is_not_omitted(self):
        base, analysis = self.compare(before='value = 1\n')
        self.assertEqual([(f['consumer'], f['code']) for f in analysis['findings']], [('reporting', 'OPERATION_REMOVED')])
        self.assertEqual(analysis['findings'][0]['dependency_freshness'], 'CURRENT')
        result = self.result(analysis)
        head = self.graph.context(analysis['context_used_id'])
        source = next(s for s in head['sources'].values() if s['repository'] == 'reporting' and s['path'] == 'client.py')
        self.assertTrue(any(e.repository == 'reporting' and e.content_sha256 == source['sha256'] for e in result.evidence))

    def test_deleted_call_is_not_warned_about_as_a_current_consumer(self):
        _, analysis = self.compare(after='value = 1\n')
        self.assertEqual([d['code'] for d in analysis['deltas']], ['OPERATION_REMOVED'])
        self.assertEqual(analysis['findings'], [])

    def test_moved_call_uses_its_head_location_and_source_quote(self):
        _, analysis = self.compare(after='# shifted\n# twice\n' + CALL)
        self.assertEqual([f['callsite']['line'] for f in analysis['findings']], [4])
        self.assertEqual(analysis['findings'][0]['dependency_freshness'], 'CURRENT')
        self.result(analysis)  # Validates real citations and relationships.

    def test_retargeted_host_or_method_retains_its_unresolved_gap_without_old_alert(self):
        for call in ['requests.get("https://unknown.test/other")', 'requests.post("https://orders.test/orders")']:
            with self.subTest(call=call):
                _, analysis = self.compare(after='import requests\n' + call + '\n')
                self.assertEqual(analysis['findings'], [])
                self.assertIn('unmapped_call', [g['code'] for g in analysis['gaps']])
                self.assertEqual(analysis['coverage'], 'PARTIAL')

    def test_same_line_unknown_call_is_not_cleared_with_the_resolved_removed_target(self):
        _, analysis = self.compare(after='import requests\nrequests.get("https://orders.test/orders"); requests.get("https://unknown.test/other")\n')
        self.assertEqual(len(analysis['findings']), 1)
        self.assertEqual([g['code'] for g in analysis['gaps']], ['unmapped_call'])
        self.assertEqual(len(analysis['resolved_removed_calls']), 1)
        self.assertEqual(analysis['coverage'], 'PARTIAL')

    def test_opaque_caller_keeps_stale_base_evidence_and_visible_boundary(self):
        _, analysis = self.compare(after='import httpx\nhttpx.get("https://orders.test/orders")\n')
        self.assertEqual([f['dependency_freshness'] for f in analysis['findings']], ['STALE'])
        self.assertIn('unknown_http_client', [g['code'] for g in analysis['gaps']])

    def test_unavailable_caller_keeps_stale_base_evidence(self):
        base = self.graph.prepare_context()
        self.api.write_text(EMPTY_API)
        self.client.parent.rename(self.root / 'unavailable-reporting')
        analysis = self.graph.analyze_change(base['id'])
        self.assertEqual([f['dependency_freshness'] for f in analysis['findings']], ['STALE'])
        self.assertTrue(analysis['gaps'])

    def test_unparseable_provider_cannot_prove_operation_removal(self):
        base = self.graph.prepare_context()
        self.api.write_text('def broken(\n')
        analysis = self.graph.analyze_change(base['id'])
        self.assertEqual(analysis['deltas'], [])
        self.assertIn('python_parse_error', [g['code'] for g in analysis['gaps']])

    def test_template_call_can_be_verified_against_removed_base_declaration(self):
        before = CALL.replace('/orders"', '/orders/42"')
        _, analysis = self.compare(before=before, after=before, api=API.replace('/orders"', '/orders/{order_id}"'))
        self.assertEqual([f['code'] for f in analysis['findings']], ['OPERATION_REMOVED'])
        self.assertEqual(analysis['findings'][0]['dependency_freshness'], 'CURRENT')
        self.assertEqual(analysis['gaps'], [])

    def test_selected_scope_does_not_clear_other_removed_operation_gap(self):
        self.api.write_text(API + '@app.get("/other")\ndef other():\n    return []\n')
        self.client.write_text(CALL.replace('/orders"', '/other"'))
        ctx = self.graph.prepare_context()
        selected = next(o['id'] for o in ctx['graph']['operations'] if o['path'] == '/orders')
        base = self.graph.prepare_context(operation_id=selected)
        self.api.write_text(API)
        analysis = self.graph.analyze_change(base['id'])
        self.assertEqual(analysis['deltas'], [])
        self.assertIn('unmapped_call', [g['code'] for g in analysis['gaps']])

    def test_new_consumer_in_another_repository_is_found_at_head(self):
        self.client.write_text('value = 1\n')
        base = self.graph.prepare_context()
        self.api.write_text(EMPTY_API)
        (self.root / 'corpus/health/new.py').write_text(CALL)
        analysis = self.graph.analyze_change(base['id'])
        self.assertEqual([(f['consumer'], f['dependency_freshness']) for f in analysis['findings']], [('health', 'CURRENT')])
        self.result(analysis)

    def test_current_replacement_route_is_not_forced_back_to_removed_declaration(self):
        base = self.graph.prepare_context()
        self.api.write_text(API.replace('/orders"', '/{resource}"'))
        analysis = self.graph.analyze_change(base['id'])
        self.assertEqual([d['code'] for d in analysis['deltas']], ['OPERATION_REMOVED'])
        self.assertEqual([f['code'] for f in analysis['findings']], ['UNCLASSIFIED_CHANGE_RECHECK'])
        self.assertEqual(analysis['findings'][0]['dependency_freshness'], 'CURRENT')
        result = self.result(analysis)
        self.assertEqual((result.status, result.reason_code), ('PARTIAL', 'unclassified_change'))
        head = self.graph.context(analysis['context_used_id'])
        source = next(s for s in head['sources'].values() if s['repository'] == 'orders')
        self.assertTrue(any(e.repository == 'orders' and e.content_sha256 == source['sha256'] for e in result.evidence))
        self.assertEqual(analysis['gaps'], [])

    def test_ambiguous_current_mapping_does_not_become_a_verified_removed_call(self):
        base = self.graph.prepare_context()
        self.api.write_text(API.replace('/orders"', '/{resource}"') + '@app.get("/{other}")\ndef other():\n    return []\n')
        analysis = self.graph.analyze_change(base['id'])
        self.assertIn('ambiguous_mapping', [g['code'] for g in analysis['gaps']])
        self.assertTrue(all(f['dependency_freshness'] == 'STALE' for f in analysis['findings']))
        self.assertFalse(analysis.get('resolved_removed_calls'))

    def test_dynamic_parameters_revealed_during_remap_remain_visible(self):
        _, analysis = self.compare(after='import requests\nrequests.get("https://orders.test/orders", **options)\n')
        self.assertEqual([f['usage'] for f in analysis['findings']], ['UNKNOWN_USAGE'])
        self.assertEqual([f['dependency_freshness'] for f in analysis['findings']], ['CURRENT'])
        self.assertIn('dynamic_parameters', [g['code'] for g in analysis['gaps']])
        self.assertEqual(analysis['coverage'], 'PARTIAL')

    def test_retained_exact_base_route_prevents_false_removed_template_mapping(self):
        self.api.write_text(API + '@app.get("/{resource}")\ndef fallback():\n    return []\n')
        base = self.graph.prepare_context()
        self.api.write_text(API)
        analysis = self.graph.analyze_change(base['id'])
        self.assertEqual([d['code'] for d in analysis['deltas']], ['OPERATION_REMOVED'])
        self.assertEqual(analysis['findings'], [])
        self.assertEqual(analysis['resolved_removed_calls'], [])

    def test_deleted_caller_file_is_not_kept_as_stale(self):
        base = self.graph.prepare_context()
        self.api.write_text(EMPTY_API)
        self.client.unlink()
        analysis = self.graph.analyze_change(base['id'])
        self.assertEqual(analysis['findings'], [])

    def test_stale_public_fact_is_explicitly_historical(self):
        _, analysis = self.compare(after='import httpx\nhttpx.get("https://orders.test/orders")\n')
        result = self.result(analysis)
        facts = [c.statement for c in result.claims if c.kind == 'fact']
        self.assertTrue(any('previously called (current use unverified)' in text for text in facts))

    def test_mixed_current_and_stale_calls_keep_live_edge_and_separate_witnesses(self):
        (self.client.parent / 'second.py').write_text(CALL)
        base = self.graph.prepare_context()
        calls = sorted(base['graph']['dependencies'], key=lambda d: d['id'])
        stale_path = calls[-1]['path']
        (self.client.parent / stale_path).write_text('import httpx\nhttpx.get("https://orders.test/orders")\n')
        self.api.write_text(EMPTY_API)
        analysis = self.graph.analyze_change(base['id'])
        self.assertEqual({f['dependency_freshness'] for f in analysis['findings']}, {'CURRENT', 'STALE'})
        for findings in (analysis['findings'], list(reversed(analysis['findings']))):
            result = self.result(dict(analysis, findings=findings))
            self.assertEqual([r.status for r in result.relationships], ['ACTIVE'])
            evidence = {e.id: e for e in result.evidence}
            paths = {evidence[ref].path for ref in result.relationships[0].evidence_refs
                     if evidence[ref].repository == 'reporting'}
            self.assertEqual(paths, {d['path'] for d in calls if d['path'] != stale_path})
            self.assertTrue(any(f.dependency_freshness == 'STALE' for f in result.findings))

    def test_multiple_current_calls_aggregate_all_live_relationship_witnesses(self):
        (self.client.parent / 'second.py').write_text(CALL)
        base = self.graph.prepare_context()
        self.api.write_text(EMPTY_API)
        result = self.result(self.graph.analyze_change(base['id']))
        evidence = {e.id: e for e in result.evidence}
        paths = {evidence[ref].path for ref in result.relationships[0].evidence_refs
                 if evidence[ref].repository == 'reporting'}
        self.assertEqual(paths, {'client.py', 'second.py'})

    def add_same_service_repository(self):
        from agent_graph.contracts import Policy
        root = self.root / 'corpus/other-orders'
        root.mkdir()
        (root / 'api.py').write_text('value = 1\n')
        data = self.policy.model_dump()
        data['repositories'].append(dict(id='orders-other', service='orders', root=str(root), revision='fixture-1'))
        self.policy = Policy.model_validate(data)
        self.graph = Graph(self.policy, self.store)
        return root

    def test_missing_head_repository_of_same_provider_service_prevents_proven_removal(self):
        other = self.add_same_service_repository()
        base = self.graph.prepare_context()
        self.api.write_text(EMPTY_API)
        other.rename(self.root / 'unavailable-other-orders')
        analysis = self.graph.analyze_change(base['id'])
        self.assertEqual(analysis['deltas'], [])
        self.assertEqual(analysis['findings'], [])
        self.assertEqual(analysis['coverage'], 'PARTIAL')

    def test_unsupported_head_route_in_same_service_repository_prevents_removal(self):
        other = self.add_same_service_repository()
        base = self.graph.prepare_context()
        self.api.write_text(EMPTY_API)
        (other / 'api.py').write_text('from fastapi import APIRouter\nrouter = APIRouter()\n@router.get("/orders")\ndef orders():\n    return []\n')
        analysis = self.graph.analyze_change(base['id'])
        self.assertEqual(analysis['deltas'], [])
        self.assertIn('provider_route_unsupported', [g['code'] for g in analysis['gaps']])

    def test_incomplete_base_provider_catalogue_does_not_prove_unique_template_target(self):
        self.api.write_text(API.replace('/orders"', '/{resource}"'))
        hidden = self.api.parent / 'hidden.py'
        hidden.write_text('def broken(\n')
        self.client.write_text('value = 1\n')
        base = self.graph.prepare_context()
        hidden.unlink()
        self.api.write_text(EMPTY_API)
        self.client.write_text(CALL)
        analysis = self.graph.analyze_change(base['id'])
        self.assertEqual(analysis['findings'], [])
        self.assertFalse(analysis['resolved_removed_calls'])
        self.assertIn('unmapped_call', [g['code'] for g in analysis['gaps']])

    def test_dynamic_head_registration_cannot_be_called_a_proven_removal(self):
        base = self.graph.prepare_context()
        self.api.write_text(EMPTY_API + 'def handler():\n    return []\napp.add_api_route("/orders", handler, methods=["GET"])\n')
        analysis = self.graph.analyze_change(base['id'])
        self.assertEqual(analysis['deltas'], [])
        self.assertIn('provider_route_unsupported', [g['code'] for g in analysis['gaps']])
        self.assertEqual((self.result(analysis).status, self.result(analysis).reason_code), ('PARTIAL', 'unclassified_change'))

    def test_unchanged_opaque_base_registration_keeps_catalogue_uncertain(self):
        extra = 'def handler():\n    return []\napp.add_api_route("/orders", handler, methods=["GET"])\n'
        self.api.write_text(API.replace('/orders"', '/{resource}"') + extra)
        base = self.graph.prepare_context()
        self.api.write_text(EMPTY_API + extra)
        analysis = self.graph.analyze_change(base['id'])
        self.assertEqual(analysis['findings'], [])
        self.assertIn('provider_route_unsupported', [g['code'] for g in analysis['gaps']])

    def test_deleting_a_complete_provider_file_still_proves_removal(self):
        base = self.graph.prepare_context()
        self.api.unlink()
        analysis = self.graph.analyze_change(base['id'])
        self.assertEqual([f['code'] for f in analysis['findings']], ['OPERATION_REMOVED'])
        self.assertEqual(analysis['findings'][0]['dependency_freshness'], 'CURRENT')

    def test_replacement_hypothesis_explicitly_names_old_changed_operation(self):
        base = self.graph.prepare_context()
        self.api.write_text(API.replace('/orders"', '/{resource}"'))
        result = self.result(self.graph.analyze_change(base['id']))
        risks = [c for c in result.claims if c.kind == 'hypothesis']
        self.assertEqual([c.subject.route if c.subject else None for c in risks], ['/orders'])
        self.assertTrue(any('GET /orders' in c.statement for c in risks))
        self.assertEqual([r.target.route for r in result.relationships], ['/{resource}'])
