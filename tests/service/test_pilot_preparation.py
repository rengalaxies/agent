"""Author pilot delivery checks; not independent held-out evaluation."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from agent_graph.contracts import Policy
from agent_graph.engine import Graph
from agent_graph.store import Store
from examples.pilot_orders_reporting.prepare import prepare


class PilotPreparationTest(unittest.TestCase):
    def test_partial_configuration_is_blocked_and_rendered_shape_uses_real_box_contract(self):
        root = Path(__file__).resolve().parents[2]
        path = root / "docs/implementation/autonomous-mvp/m2-a-2026-10-28"
        spec = importlib.util.spec_from_file_location("pilot_config", path / "render_config.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with self.assertRaisesRegex(ValueError, "missing_non_secret_identifiers"):
            module.render(json.loads((path / "inputs.json").read_text()))
        # Test-only surrogate identifiers: schema proof, never an installable artifact.
        config = module.render(dict(github_app_id="123", github_installation_id=456,
            github_bot_login="schema-test[bot]", jira_api_base_url="https://schema-test.atlassian.net",
            jira_project_key="PILOT", jira_bot_account_id="schema-only"))
        self.assertEqual(config["publication"], "dry_run")
        self.assertNotIn("model", config)
        self.assertNotIn("testing", config)
        self.assertEqual({r["name"] for r in config["github"]["repositories"]},
                         {"rengalaxies/agent-pilot-orders", "rengalaxies/agent-pilot-reporting"})

    def test_repeated_preparation_has_the_same_commits_and_bundles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(prepare(root / "a"), prepare(root / "b"))

    def test_authored_git_scenario_has_supported_static_evidence_and_negative_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepared = prepare(root / "repositories")
            pins = {name: item["commits"]["main"] for name, item in prepared["repositories"].items()}
            source = Path(__file__).resolve().parents[2] / "examples/pilot_orders_reporting/reporting/export-requirement.md"
            requirement = dict(id="R-pilot-export-all", repository="reporting", path="export-requirement.md",
                sha256=hashlib.sha256(source.read_bytes()).hexdigest(), issuer="M2-A author test condition",
                consumer="reporting", service="orders", path_template="/orders", predicate="complete_collection")
            document = dict(installation_id="agent-pilot", environment="test", subject="author-preparation",
                capabilities=["read_context", "maintain"],
                repositories=[dict(id=name, service=name, root=str(root / "repositories" / name),
                                   snapshot="git", revision=sha) for name, sha in pins.items()],
                addresses=[dict(service="orders", base_url="https://orders.pilot.invalid")], requirements=[])
            store = Store(root / "state")
            self.addCleanup(store.close)
            no_requirement = Graph(Policy.model_validate(document), store).prepare_context()
            self.assertEqual([(d["consumer"], d["usage"]) for d in no_requirement["graph"]["dependencies"]],
                             [("reporting", "SINGLE_REQUEST_OBSERVED")])
            self.assertEqual(no_requirement["graph"]["requirements"], [])
            graph = Graph(Policy.model_validate({**document, "requirements": [requirement]}), store)
            base = graph.prepare_context()
            branches = prepared["repositories"]["orders"]["commits"]
            limit = graph.analyze_change(base["id"], revisions={**pins, "orders": branches["pilot-page-limit"]})
            self.assertEqual([(f["consumer"], f["code"], f["test_executed"]) for f in limit["findings"]],
                             [("reporting", "POSSIBLE_TRUNCATION", False)])
            repaired = graph.analyze_change(base["id"], revisions={"orders": branches["pilot-page-limit"],
                "reporting": prepared["repositories"]["reporting"]["commits"]["pilot-explicit-limit"]})
            self.assertTrue(repaired["findings"])
            self.assertNotIn("POSSIBLE_TRUNCATION", {f["code"] for f in repaired["findings"]})
            for branch in ("pilot-restored", "pilot-docs-only"):
                with self.subTest(branch=branch):
                    result = graph.analyze_change(base["id"], revisions={**pins, "orders": branches[branch]})
                    self.assertEqual((result["deltas"], result["findings"]), ([], []))


if __name__ == "__main__":
    unittest.main()
