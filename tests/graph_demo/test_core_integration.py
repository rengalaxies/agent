from pathlib import Path
import shutil
import time

import agent_graph
from agent_graph.output_contracts import FindingCode
from agent_graph_demo.contracts import DemoError
from agent_graph_demo.graph_cli import GraphCLI, bundled_core_root

from .helpers import DemoCase

ROOT = Path(__file__).resolve().parents[2]


class ShippedCoreTests(DemoCase):
    def test_default_transport_runs_the_core_this_application_imports(self):
        cli = GraphCLI()
        self.assertEqual(cli.source, bundled_core_root())
        cli.invoke(self.snap.session_root(self.sid), "prepare_context", deadline=time.monotonic() + 60,
                   cancelled=lambda: False)
        self.assertTrue(cli.verified)
        self.assertEqual(cli.identity(), agent_graph.core_identity())

    def test_external_checkout_of_another_core_fails_closed(self):
        other = self.root / "old-core"
        shutil.copytree(ROOT / "src" / "agent_graph", other / "src" / "agent_graph",
                        ignore=shutil.ignore_patterns("__pycache__"))
        engine = other / "src" / "agent_graph" / "engine.py"
        engine.write_text(engine.read_text() + "\n# older core\n")
        cli = GraphCLI(other)
        with self.assertRaisesRegex(DemoError, "core_pin_mismatch"):
            cli.invoke(self.snap.session_root(self.sid), "prepare_context", deadline=time.monotonic() + 60,
                       cancelled=lambda: False)
        self.assertEqual(cli.processes, 1, "only the identity probe ran; no analysis on the foreign core")


class FanOutTests(DemoCase):
    def test_core_processes_per_job_do_not_grow_with_citations(self):
        base = self.prepare()
        before, evidence_before = self.cli.processes, len(self.store.artifacts(self.sid, "evidence"))
        self.run_job("analyze_change", target_version="B", base_context_id=base)
        processes = self.cli.processes - before
        citations = len(self.store.artifacts(self.sid, "evidence")) - evidence_before
        # analyze_change + dependencies + one evidence_batch, whatever the citation count.
        self.assertEqual(processes, 3)
        self.assertGreater(citations, processes)


class CodeCompatibilityTests(DemoCase):
    def test_unknown_core_finding_code_fails_the_job_instead_of_showing_a_result(self):
        base = self.prepare()
        original = self.cli.invoke

        def invoke(root, command, **kwargs):
            value = original(root, command, **kwargs)
            if command == "analyze_change":
                for finding in value["findings"]:
                    finding["code"] = "SAFE_TO_SHIP"
            return value

        self.cli.invoke = invoke
        j = self.store.enqueue(self.sid, "operator", self.body("analyze_change", target_version="B",
                                                              base_context_id=base))
        self.worker.run_once()
        j = self.store.job(j["id"])
        self.assertEqual((j["status"], j["error_code"]), ("FAILED", "incompatible_core_output"))

    def test_every_contract_finding_code_has_a_ui_label_and_unknown_is_not_recheck(self):
        app = (ROOT / "src/agent_graph_demo/web/app.js").read_text(encoding="utf-8")
        for code in FindingCode.__args__:
            self.assertIn(f"  {code}: [", app)
        self.assertIn("return findingLabels[code] || unknownFinding;", app)
