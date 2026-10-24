from pathlib import Path
import sys
import tempfile
import unittest

from agent_graph.contracts import GraphError
from agent_graph.engine import Graph
from agent_graph.store import Store

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples/agent_graph"))
from fixture import create_fixture  # noqa: E402


class EvidenceBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = Store(root / "state")
        self.g = Graph(create_fixture(root), self.store)
        self.c = self.g.prepare_context()
        self.citation = self.c["graph"]["dependencies"][0]["evidence"][0]

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_only_not_found_falls_through_to_the_next_context(self):
        changed = {**self.citation, "quote": self.citation["quote"] + " "}
        result = self.g.evidence_batch([
            dict(contexts=["missing-context", self.c["id"]], citation=self.citation),
            dict(contexts=[self.c["id"], "missing-context"], citation=changed),
            dict(contexts=[self.c["id"]], citation=dict(source_id="x")),
        ])["results"]
        self.assertEqual(result[0]["context_id"], self.c["id"])
        self.assertEqual(result[0]["evidence"]["quote"], self.citation["quote"])
        self.assertEqual(result[1], dict(error="evidence_mismatch"))
        self.assertEqual(result[2], dict(error="invalid_citation"))

    def test_batch_is_bounded_and_shaped(self):
        for items in ([dict(contexts=[], citation=self.citation)], [dict(contexts=["a"] * 5, citation={})],
                      "not-a-list"):
            with self.assertRaises(GraphError):
                self.g.evidence_batch(items)
        with self.assertRaises(GraphError) as caught:
            self.g.evidence_batch([dict(contexts=[self.c["id"]], citation=self.citation)] * 5001)
        self.assertEqual(caught.exception.code, "evidence_batch_limit")


if __name__ == "__main__":
    unittest.main()
