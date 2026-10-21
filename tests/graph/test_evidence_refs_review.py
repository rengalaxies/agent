"""Independent synthetic controls: new names, addresses, method, paths and files."""
from pathlib import Path
import tempfile
import unittest

from agent_graph.contracts import GraphError, Policy
from agent_graph.engine import Graph
from agent_graph.evidence_refs import EvidenceSession
from agent_graph.store import Store


class RenamedControls(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        provider = 'from fastapi import FastAPI\nrouter = FastAPI()\n\n@router.post("/widgets")\ndef ingest():\n    return {"ok": True}\n'
        files = {"producer_repo": ("endpoints_alt.py", provider), "decoy_repo": ("unrelated_name.py", provider),
                 "batch_repo": ("send_batch.py", 'import requests as wire\nTARGET = "https://violet.example:9443/v2"\n\ndef submit():\n    return wire.post(TARGET + "/widgets", json={"x": 1})\n')}
        services = dict(producer_repo="svc_zeta", decoy_repo="svc_eta", batch_repo="job_beta")
        for repo, (name, content) in files.items():
            (self.root / repo).mkdir()
            (self.root / repo / name).write_text(content)
        policy = Policy.model_validate(dict(
            installation_id="independent-test-data", environment="offline", subject="scripted-control",
            capabilities=["read_context", "maintain", "propose"],
            repositories=[dict(id=r, service=services[r], root=str(self.root/r), revision="test-data-v1") for r in files],
            addresses=[dict(service="svc_zeta", base_url="https://violet.example:9443/v2"),
                       dict(service="svc_eta", base_url="https://amber.example:8443/v2")]))
        self.graph = Graph(policy, Store(self.root / "state"))
        self.context = self.graph.prepare_context("EXPLICIT OFFLINE TEST DATA")
        self.session = EvidenceSession(self.graph, self.context["id"])
        self.refs = {s["repository"]: self.session.read(s["id"], 1, len(s["text"].splitlines()))["evidence_ref"]
                     for s in self.context["sources"].values()}
        self.claim = dict(consumer_repository="batch_repo", consumer_service="job_beta", provider_service="svc_zeta",
                          method="POST", path_template="/widgets")

    def tearDown(self):
        self.graph.store.close()
        self.tmp.cleanup()

    def p(self, refs, **updates):
        return dict(claim={**self.claim, **updates}, evidence_refs=[self.refs[r] for r in refs])

    def test_other_names_method_port_and_base_path_are_supported(self):
        p = self.p(["batch_repo", "producer_repo"])
        first = self.session.propose(p)
        again = self.session.propose(p)  # Legitimate same-session reuse, no new authority.
        self.assertEqual(first["candidate"]["id"], again["candidate"]["id"])
        self.assertEqual(len(self.graph.store.proposals(self.graph.view)), 1)
        self.assertEqual(first["candidate"]["trust"], "UNAPPROVED_CANDIDATE")
        self.assertEqual(first["assessment"]["sufficiency"]["scope"], "STATIC_PROFILE_ONLY")
        # Candidates do not add parser edges or runtime verification.
        self.assertEqual(len(self.graph.dependencies(self.context["id"])["dependencies"]), 1)
        self.assertFalse(first["assessment"]["sufficiency"]["runtime_verified"])

    def test_byte_identical_exact_decoy_provider_does_not_establish_identity(self):
        for p in [self.p(["batch_repo", "decoy_repo"]),
                  self.p(["batch_repo", "decoy_repo"], provider_service="svc_eta"),
                  self.p(["producer_repo", "batch_repo"], consumer_repository="producer_repo", consumer_service="svc_zeta", provider_service="job_beta")]:
            result = self.session.assess(p)
            self.assertEqual(result["provenance"]["status"], "AUTHENTIC_AUTHORIZED_CURRENT")
            self.assertEqual(result["sufficiency"]["status"], "INSUFFICIENT")
            with self.assertRaisesRegex(GraphError, "insufficient_dependency_evidence"):
                self.session.propose(p)

    def test_exact_unrelated_span_in_correct_file_is_not_enough(self):
        source = next(s for s in self.context["sources"].values() if s["repository"] == "batch_repo")
        irrelevant = self.session.read(source["id"], 1, 2)["evidence_ref"]
        p = dict(claim=self.claim, evidence_refs=[irrelevant, self.refs["producer_repo"]])
        result = self.session.assess(p)
        self.assertEqual(result["provenance"]["status"], "AUTHENTIC_AUTHORIZED_CURRENT")
        self.assertEqual(result["sufficiency"]["status"], "INSUFFICIENT")

    def test_source_changes_after_read_before_proposal(self):
        path = self.root / "batch_repo/send_batch.py"
        path.write_text(path.read_text().replace("violet.example:9443", "amber.example:8443"))
        result = self.session.assess(self.p(["batch_repo", "producer_repo"]))
        self.assertEqual(result["provenance"], dict(status="REJECTED", reason="stale_context"))
        self.assertEqual(result["sufficiency"]["status"], "NOT_ASSESSED")

    def test_unsupported_wrapper_does_not_prove_absence(self):
        path = self.root / "batch_repo/send_batch.py"
        path.write_text('def submit():\n    return opaque_client.send("https://violet.example:9443/v2/widgets")\n')
        context = self.graph.prepare_context()
        session = EvidenceSession(self.graph, context["id"])
        refs = [session.read(s["id"], 1, len(s["text"].splitlines()))["evidence_ref"] for s in context["sources"].values()]
        result = session.assess(dict(claim=self.claim, evidence_refs=refs))
        self.assertEqual(result["sufficiency"]["status"], "INSUFFICIENT")
        self.assertEqual(result["sufficiency"]["dependency_absence"], "NOT_ESTABLISHED")
