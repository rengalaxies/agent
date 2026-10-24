"""The interim adapter over the real agent_graph protocol, driven by a fake transport.

Linux only: agent_graph's Store needs fcntl and its reader needs O_DIRECTORY.
"""
import json
from pathlib import Path
import tempfile
import unittest

from tools.autonomous_mvp import ledger, program as program_mod, protocol, runner
from tools.autonomous_mvp.tests.helpers import POSIX_CORE
from tools.autonomous_mvp.transport import ScriptedTransport, reply

BASE, PROGRAM, CASES = program_mod.load()
MODEL = PROGRAM["models"][0]


@unittest.skipUnless(POSIX_CORE, "agent_graph store/reader are POSIX-only")
class InterimAdapter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = protocol.load("evidence-refs-v2-interim")

    def tearDown(self):
        self.tmp.cleanup()

    def run_case(self, case_id, script_fn):
        """script_fn(payload, sources) -> TransportResult; sources from the first user message."""
        state = {}

        def respond(payload):
            if "sources" not in state:
                state["sources"] = json.loads(payload["messages"][1]["content"])["sources"]
            state.setdefault("refs", [])
            for m in payload["messages"]:
                if m["role"] == "user" and "untrusted_source" in m["content"]:
                    ref = json.loads(m["content"])["untrusted_source"]["evidence_ref"]
                    if ref not in state["refs"]:
                        state["refs"].append(ref)
            return script_fn(len([m for m in payload["messages"] if m["role"] == "assistant"]), state)
        transport = ScriptedTransport([respond] * 10)
        work = Path(self.tmp.name) / case_id
        work.mkdir()
        return runner.run_case(CASES[case_id], 1, protocol=self.p, transport=transport, model=MODEL,
                               parameters=PROGRAM["parameters"], phase_deadline=float("inf"), work=work)[1]

    @staticmethod
    def source(state, repo, suffix):
        return next(s for s in state["sources"] if s["repository"] == repo and s["path"].endswith(suffix))

    def read(self, s):
        return reply(json.dumps(dict(action="read_source", source_id=s["source_id"], start_line=1,
                                     end_line=s["lines"], proposals=[])))

    def propose(self, claim, refs):
        return reply(json.dumps(dict(action="propose", source_id=None, start_line=None, end_line=None,
                                     proposals=[dict(claim=claim, evidence_refs=refs)])))

    FINISH = json.dumps(dict(action="finish", source_id=None, start_line=None, end_line=None, proposals=[]))

    def test_read_propose_finish_admits_the_static_edge(self):
        claim = dict(consumer_repository="reporting", consumer_service="reporting", provider_service="orders",
                     method="GET", path_template="/orders")

        def script(step, state):
            if step == 0:
                return self.read(self.source(state, "reporting", "export.py"))
            if step == 1:
                return self.read(self.source(state, "orders", "api.py"))
            if step == 2:
                return self.propose(claim, state["refs"])
            return reply(self.FINISH)
        result = self.run_case("S01", script)
        self.assertEqual(result["terminal"], "FINISHED")
        self.assertEqual([c["confidence"] for c in result["claims"]], ["CONFIRMED_WITHIN_PROFILE"])

    def test_forged_refs_are_rejected_and_not_admitted(self):
        claim = dict(consumer_repository="loyalty", consumer_service="loyalty", provider_service="orders",
                     method="GET", path_template="/orders")

        def script(step, state):
            if step == 0:
                return self.propose(claim, ["1f0e3d2c4b5a69788796a5b4c3d2e1f0"])
            return reply(self.FINISH)
        result = self.run_case("D06", script)
        c = result["claims"][0]
        self.assertEqual((c["provenance"], c["admitted"]), ("REJECTED", False))
        self.assertEqual(c["provenance_reason"], "invalid_evidence_reference")

    def test_decoy_claim_with_authentic_reads_is_insufficient(self):
        claim = dict(consumer_repository="audit-trail", consumer_service="audit-trail", provider_service="orders",
                     method="GET", path_template="/orders")

        def script(step, state):
            if step == 0:
                return self.read(self.source(state, "audit-trail", "sync.py"))
            if step == 1:
                return self.read(self.source(state, "orders", "api.py"))
            if step == 2:
                return self.propose(claim, state["refs"])
            return reply(self.FINISH)
        result = self.run_case("D03", script)
        c = result["claims"][0]
        self.assertEqual((c["provenance"], c["sufficiency"], c["admitted"]),
                         ("AUTHENTIC", "INSUFFICIENT", False))

    def test_schema_violation_reports_a_path_without_echoing_model_keys(self):
        bad = json.dumps(dict(action="finish", source_id=None, start_line=None, end_line=None, proposals=[],
                              leaked_value_sk_live_123=True))
        result = self.run_case("S01", lambda step, state: reply(bad))
        first = result["steps"][0]
        self.assertEqual((first["layer"], first["errors"]), ("schema", [dict(path="*", type="extra_forbidden")]))
        self.assertNotIn("leaked_value", json.dumps(result))

    def test_unlisted_source_read_is_a_tool_admissibility_rejection(self):
        bad = json.dumps(dict(action="read_source", source_id="../../../etc/passwd", start_line=1, end_line=2,
                              proposals=[]))
        result = self.run_case("D11", lambda step, state: reply(bad if step == 0 else self.FINISH))
        self.assertEqual((result["steps"][0]["layer"], result["steps"][0]["reason_code"]),
                         ("tool_admissibility", "not_found"))
        self.assertEqual(result["terminal"], "FINISHED")

    def test_full_transport_phase_with_file_ledger(self):
        program = json.loads(json.dumps(PROGRAM))
        program["models"] = [MODEL]
        claim = dict(consumer_repository="reporting", consumer_service="reporting", provider_service="orders",
                     method="GET", path_template="/orders")
        script = []
        for _ in range(3):
            state = {}

            def respond(payload, state=state):
                if "sources" not in state:
                    state["sources"] = json.loads(payload["messages"][1]["content"])["sources"]
                refs = [json.loads(m["content"])["untrusted_source"]["evidence_ref"] for m in payload["messages"]
                        if m["role"] == "user" and "untrusted_source" in m["content"]]
                step = len([m for m in payload["messages"] if m["role"] == "assistant"])
                if step == 0:
                    return self.read(self.source(state, "reporting", "export.py"))
                if step == 1:
                    return self.read(self.source(state, "orders", "api.py"))
                if step == 2:
                    return self.propose(claim, refs)
                return reply(self.FINISH)
            script += [respond] * 4
        d = Path(self.tmp.name)
        state = runner.execute_phase(
            "transport", MODEL["id"], program=program, cases=CASES, manifest_digest="m" * 64, source_sha="a" * 40,
            transport=ScriptedTransport(script, models=[MODEL["id"]]),
            backend_for=lambda phase: ledger.FileBackend(d / f"{phase}.json"), work=d / "work", protocol=self.p)
        self.assertEqual(state["status"], "COMPLETED")
        self.assertTrue(runner.requirement_met("development", state))


if __name__ == "__main__":
    unittest.main()
