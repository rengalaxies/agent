from datetime import timedelta
import unittest
from test_knowledge import fixture, T
from datamesh_release_protocol.evidence_graph import project_evidence_graph


class EvidenceGraphTests(unittest.TestCase):
    def setUp(self):
        self.store, self.old, self.new = fixture()

    def snapshot(self):
        return self.store.build_snapshot('graph', self.old, self.new, T + timedelta(seconds=4))

    def test_owner_requirement_path_and_reproducibility(self):
        snapshot = self.snapshot()
        graph = project_evidence_graph(snapshot, ['active'])
        self.assertEqual(graph, project_evidence_graph(snapshot, ['active']))
        self.assertEqual(graph['impacts'][0]['requirements'], ['obligation'])
        self.assertEqual(graph['impacts'][0]['owner'], 'risk')
        self.assertIn(dict(source='obligation', target='usage', relation='requires_usage',
                           evidence='obligation'), graph['edges'])

    def test_narrowing_does_not_imply_completeness(self):
        self.store.revoke_record('coverage', 'registry', 'revoked', T + timedelta(seconds=2))
        graph = project_evidence_graph(self.snapshot(), ['unrelated'])
        self.assertEqual(graph['impacts'], [])
        self.assertNotEqual(graph['completeness'], 'complete')
        self.assertTrue(graph['issues'])

    def test_explicit_empty_diff_and_semantic_product_change(self):
        snapshot = self.snapshot()
        self.assertEqual(project_evidence_graph(snapshot, [])['impacts'], [])
        self.assertEqual(len(project_evidence_graph(snapshot)['impacts']), 1)

    def test_tampered_snapshot_fails(self):
        snapshot = self.snapshot()
        snapshot.records[0].evidence_ref = 'tampered'
        with self.assertRaises(ValueError):
            project_evidence_graph(snapshot)
