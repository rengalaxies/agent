"""Default overrides must not hide unrelated changes or invent consumer alerts."""
import json
from pathlib import Path
import tempfile
import unittest

from agent_graph.engine import Graph
from agent_graph.store import Store
from agent_graph.output_contracts import parse_document
from agent_graph.results import change_result
from examples.agent_graph.fixture import create_fixture

API = '''from fastapi import FastAPI
app = FastAPI()
@app.get("/orders")
def orders(page_size: int = 100):
    return list(range(60))[:page_size]
'''


class DefaultChangeScopeTests(unittest.TestCase):
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
        # Isolate the one consumer under test, without mocks or scorer filtering.
        (self.root / 'corpus/export/client.py').write_text('value = 1\n')
        (self.root / 'corpus/health/client.py').write_text('value = 1\n')

    def analyze(self, client, after=None, before=API):
        self.api.write_text(before)
        self.client.write_text(client)
        base = self.graph.prepare_context()
        self.api.write_text(after or before.replace('= 100', '= 20'))
        return self.graph.analyze_change(base['id'])

    def result(self, analysis):
        request = parse_document(dict(schema='agent-graph-output', schema_version='2.0', kind='analysis_request',
            installation_id=self.policy.installation_id, environment=self.policy.environment,
            request_id='scope-test', trigger_kind='pr', source_event=dict(event_id='event', resource_version='v1'),
            repository_revisions={r.id: 'b'*40 for r in self.policy.repositories}, graph_version='graph-1',
            constitution_version='agent-service-v1.0:test', model_configuration_id=None, deadline='2026-11-16T12:00:00Z',
            access_scope=dict(view_id=self.graph.view, repositories=[r.id for r in self.policy.repositories]),
            pr=dict(provider='github', repository='orders', pr_id=1, base_sha='a'*40, head_sha='b'*40)))
        return change_result(self.graph, request, analysis, code_version='scope-test',
            constitution_version='agent-service-v1.0:test', correlation_id='scope-test')

    def test_explicit_size_exempts_only_the_default_delta_including_loop(self):
        cases = [
            'requests.get("https://orders.test/orders", params={"page_size": 40})',
            'requests.get("https://orders.test/orders", {"page_size": 40})',
            'requests.get("https://orders.test/orders?page_size=40")',
            'for page in range(4):\n    requests.get("https://orders.test/orders", params={"page": page, "page_size": 40})',
        ]
        for call in cases:
            with self.subTest(call=call):
                analysis = self.analyze('import requests\n' + call + '\n')
                self.assertEqual(analysis['findings'], [])
                head = self.graph.context(analysis['context_used_id'])
                self.assertEqual([d['consumer'] for d in head['graph']['dependencies']], ['reporting'])
                self.assertEqual([d['code'] for d in analysis['deltas']], ['PAGE_DEFAULT_CHANGED'])
                result = self.result(analysis)
                self.assertEqual(result.findings, [])
                self.assertEqual(result.checks, [])
                self.assertEqual(result.affected, [])
                self.assertNotEqual(result.reason_code, 'no_consumer_found_within_profile')
                self.assertIn('explicit', result.summary.lower())
                self.assertFalse(result.usefulness_confirmed)

    def test_none_dynamic_and_loop_without_override_keep_alerts(self):
        cases = [
            'requests.get("https://orders.test/orders")',
            'requests.get("https://orders.test/orders", params={"page_size": None})',
            'requests.get("https://orders.test/orders", params={"page_size": []})',
            'requests.get("https://orders.test/orders", params={"page_size": size})',
            'requests.get("https://orders.test/orders", **options)',
            'requests.get("https://orders.test/orders?page_size=")',
            'requests.get("https://orders.test/orders", json={"page_size": 40})',
            'for page in range(4):\n    requests.get("https://orders.test/orders", params={"page": page})',
        ]
        for call in cases:
            with self.subTest(call=call):
                analysis = self.analyze('import requests\n' + call + '\n')
                self.assertTrue(analysis['findings'])
                self.assertEqual(analysis['findings'][0]['consumer'], 'reporting')

    def test_default_and_body_change_still_requires_explicit_consumer_review(self):
        analysis = self.analyze('import requests\nrequests.get("https://orders.test/orders", params={"page_size": 40})\n',
            after=API.replace('= 100', '= 20').replace('list(range(60))', '[]'))
        self.assertTrue(analysis['findings'])
        self.assertIn('unclassified_change', [u.code for u in self.result(analysis).unknowns])

    def test_removal_alerts_even_when_consumer_sends_size(self):
        analysis = self.analyze('import requests\nrequests.get("https://orders.test/orders", params={"page_size": 40})\n',
            after='from fastapi import FastAPI\napp = FastAPI()\n')
        self.assertEqual([f['code'] for f in analysis['findings']], ['OPERATION_REMOVED'])

    def test_mixed_callsites_keep_only_implicit_call_alert(self):
        client = '''import requests
requests.get("https://orders.test/orders", params={"page_size": 40})
requests.get("https://orders.test/orders")
'''
        analysis = self.analyze(client)
        self.assertEqual([f['callsite']['line'] for f in analysis['findings']], [3])

    def test_opaque_helper_edit_is_semantic_boundary_without_invented_consumer(self):
        helper = self.root / 'corpus/orders/helper.py'
        helper.write_text('def build_page():\n    return list(range(100))\n')
        self.api.write_text(API.replace('from fastapi', 'from helper import build_page\nfrom fastapi').replace('list(range(60))[:page_size]', 'build_page()'))
        self.client.write_text('import requests\nrequests.get("https://orders.test/orders")\n')
        base = self.graph.prepare_context()
        helper.write_text('def build_page():\n    return list(range(20))\n')
        analysis = self.graph.analyze_change(base['id'])
        result = self.result(analysis)
        self.assertEqual(result.status, 'PARTIAL')
        self.assertIn('helper_semantics_unknown', [u.code for u in result.unknowns])
        self.assertEqual(result.findings, [])
        self.assertEqual(result.affected, [])

    def test_comment_only_helper_edit_does_not_invent_semantic_change(self):
        helper = self.root / 'corpus/orders/helper.py'
        helper.write_text('def helper():\n    return 1\n')
        base = self.graph.prepare_context()
        helper.write_text('# editorial comment\ndef helper():\n    return 1\n')
        result = self.result(self.graph.analyze_change(base['id']))
        self.assertEqual((result.status, result.reason_code), ('ABSTAINED', 'no_supported_delta'))

    def test_default_plus_opaque_change_does_not_exempt_explicit_call(self):
        helper = self.root / 'corpus/orders/helper.py'
        helper.write_text('value = 1\n')
        self.client.write_text('import requests\nrequests.get("https://orders.test/orders", params={"page_size": 40})\n')
        base = self.graph.prepare_context()
        self.api.write_text(API.replace('= 100', '= 20'))
        helper.write_text('value = 2\n')
        result = self.result(self.graph.analyze_change(base['id']))
        self.assertTrue(result.findings)
        self.assertIn('helper_semantics_unknown', [u.code for u in result.unknowns])

    def test_openapi_default_override_does_not_hide_response_contract_change(self):
        self.api.unlink()
        self.client.write_text('import requests\nrequests.get("https://orders.test/orders", params={"page_size": 40})\n')
        path = self.root / 'corpus/orders/api.json'
        doc = dict(openapi='3.0.0', paths={'/orders': dict(get=dict(
            parameters=[dict(name='page_size', **{'in': 'query'}, schema=dict(type='integer', default=100))],
            responses={'200': {'description': 'rows'}}))})
        path.write_text(json.dumps(doc))
        base = self.graph.prepare_context()
        op = doc['paths']['/orders']['get']
        op['parameters'][0]['schema']['default'] = 20
        path.write_text(json.dumps(doc))
        self.assertEqual(self.graph.analyze_change(base['id'])['findings'], [])
        op['responses']['200']['description'] = 'different response'
        path.write_text(json.dumps(doc))
        result = self.result(self.graph.analyze_change(base['id']))
        self.assertTrue(result.findings)
        self.assertIn('unclassified_change', [u.code for u in result.unknowns])

    def test_multiple_provider_declarations_all_constrain_default_exemption(self):
        self.client.write_text('import requests\nrequests.get("https://orders.test/orders", params={"page_size": 40})\n')
        path = self.root / 'corpus/orders/api.json'
        spec = dict(openapi='3.0.0', paths={'/orders': dict(get=dict(parameters=[
            dict(name='page_size', **{'in': 'query'}, schema=dict(default=100))]))})
        path.write_text(json.dumps(spec))
        base = self.graph.prepare_context()
        self.api.write_text(API.replace('= 100', '= 20').replace('list(range(60))', '[]'))
        spec['paths']['/orders']['get']['parameters'][0]['schema']['default'] = 20
        path.write_text(json.dumps(spec))
        result = self.result(self.graph.analyze_change(base['id']))
        self.assertTrue(result.findings, 'An unchanged JSON body must not hide a changed Python handler')
        self.assertIn('unclassified_change', [u.code for u in result.unknowns])

    def test_same_line_calls_keep_the_implicit_size_alert_in_either_order(self):
        implicit = 'requests.get("https://orders.test/orders")'
        explicit = 'requests.get("https://orders.test/orders", params={"page_size": 40})'
        for calls in [implicit + '; ' + explicit, explicit + '; ' + implicit]:
            with self.subTest(calls=calls):
                analysis = self.analyze('import requests\n' + calls + '\n')
                self.assertEqual([f['code'] for f in analysis['findings']], ['POSSIBLE_TRUNCATION'])
                head = self.graph.context(analysis['context_used_id'])
                self.assertEqual(len({d['id'] for d in head['graph']['dependencies']}), 2)

    def test_fastapi_alias_body_and_non_scalar_annotations_cannot_prove_query_override(self):
        for annotation in ["Annotated[int, Query(alias='limit')]", 'Annotated[int, Body()]', 'list[int]']:
            with self.subTest(annotation=annotation):
                before = API.replace('from fastapi import FastAPI', 'from typing import Annotated\nfrom fastapi import FastAPI, Query, Body')
                before = before.replace('page_size: int', 'page_size: ' + annotation)
                analysis = self.analyze('import requests\nrequests.get("https://orders.test/orders", params={"page_size": 40})\n', before=before)
                self.assertTrue(analysis['findings'])
                self.assertNotIn('Default-only', self.result(analysis).summary)

    def test_referenced_response_schema_change_prevents_default_only_exemption(self):
        self.api.unlink()
        self.client.write_text('import requests\nrequests.get("https://orders.test/orders", params={"page_size": 40})\n')
        path = self.root / 'corpus/orders/api.json'
        doc = dict(openapi='3.0.0', paths={'/orders': dict(get=dict(
            parameters=[dict(name='page_size', **{'in': 'query'}, schema=dict(default=100))],
            responses={'200': {'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Orders'}}}}}))},
            components=dict(schemas=dict(Orders=dict(type='array', items=dict(type='integer')))))
        path.write_text(json.dumps(doc))
        base = self.graph.prepare_context()
        doc['paths']['/orders']['get']['parameters'][0]['schema']['default'] = 20
        doc['components']['schemas']['Orders']['items']['type'] = 'string'
        path.write_text(json.dumps(doc))
        result = self.result(self.graph.analyze_change(base['id']))
        self.assertTrue(result.findings)
        self.assertIn('unclassified_change', [u.code for u in result.unknowns])

    def test_other_handler_used_as_helper_disqualifies_default_only_exemption(self):
        before = API.replace('list(range(60))[:page_size]', 'rows()[:page_size]') + '\n@app.get("/all-rows")\ndef rows():\n    return list(range(60))\n'
        analysis = self.analyze('import requests\nrequests.get("https://orders.test/orders?page_size=40")\n',
            before=before, after=before.replace('= 100', '= 20').replace('return list(range(60))', 'return []'))
        result = self.result(analysis)
        self.assertTrue(result.findings)
        self.assertIn('helper_semantics_unknown', [u.code for u in result.unknowns])

    def test_empty_dict_and_url_query_values_both_keep_alert(self):
        for call in ['requests.get("https://orders.test/orders", params={"page_size": ""})',
                     'requests.get("https://orders.test/orders?page_size=")']:
            with self.subTest(call=call):
                self.assertTrue(self.analyze('import requests\n' + call + '\n')['findings'])

    def test_exempted_default_does_not_hide_unclassified_delta_without_callers(self):
        health = self.root / 'corpus/health/api.py'
        health.write_text('from fastapi import FastAPI\napp = FastAPI()\n@app.get("/ping")\ndef ping():\n    return 1\n')
        self.client.write_text('import requests\nrequests.get("https://orders.test/orders?page_size=40")\n')
        base = self.graph.prepare_context()
        health.write_text(health.read_text().replace('return 1', 'return 2'))
        self.api.write_text(API.replace('= 100', '= 20'))
        result = self.result(self.graph.analyze_change(base['id']))
        self.assertEqual(result.status, 'PARTIAL')
        self.assertEqual(result.reason_code, 'unclassified_change')
        self.assertNotIn('Default-only', result.summary)

    def test_selected_operation_ignores_opaque_edit_in_other_provider_repository(self):
        health = self.root / 'corpus/health/api.py'
        health.write_text('from fastapi import FastAPI\napp = FastAPI()\n@app.get("/ping")\ndef ping():\n    return 1\n')
        ctx = self.graph.prepare_context()
        operation = next(o['id'] for o in ctx['graph']['operations'] if o['service'] == 'orders')
        base = self.graph.prepare_context(operation_id=operation)
        (health.parent / 'shared.py').write_text('def unrelated():\n    return 2\n')
        result = self.result(self.graph.analyze_change(base['id']))
        self.assertEqual((result.status, result.reason_code), ('ABSTAINED', 'no_supported_delta'))
        self.assertNotIn('helper_semantics_unknown', [u.code for u in result.unknowns])
