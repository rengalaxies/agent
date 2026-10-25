"""graph_* tools of the actions-v3 executor: scope, limits, and no promotion of hypotheses."""
import json
from pathlib import Path

import yaml

from agent_graph.constitution import DEFAULT_PATH
from agent_graph.contracts import Policy
from agent_graph.engine import Graph
from agent_graph.graph_query import GraphQuery
from agent_graph.graph_store import GraphStore, OwnershipMapping
from agent_graph.executor import run_investigation
from agent_graph.store import Store
from tests.graph.test_action_diagnostics import ENDPOINT, ExecutorCase, Script, act, refs

MODEL = dict(endpoint=ENDPOINT, allowed_endpoints=[ENDPOINT], model="OFFLINE-SCRIPT", configuration_id="script-v3",
             protocol="actions-v3", allow_source_transfer=True, max_prompt_bytes=60000, context_tokens=131072,
             run_token_cap=10_000_000, installation_token_cap=10_000_000)
NARROW = ["orders", "billing", "audit", "archive"]


def tool_result(messages):
    return json.loads(messages[-1]["content"])["tool_result"]


class GraphToolCase(ExecutorCase):
    def setUp(self):
        super().setUp()
        self.gs = GraphStore(self.store)
        self.gs.sync_code(self.context)
        self.gs.sync_ownership("acme", "prod", OwnershipMapping(
            source="installation_mapping", version="ownership-1", services=dict(reporting="team-reporting")))
        query = GraphQuery.for_policy(self.gs, self.policy)
        self.orders_op = next(h["id"] for h in query.find("orders GET /orders", "operation"))
        self.reporting_rel = next(r["id"] for r in query._rels.values() if r["kind"] == "calls"
                                  and query._entities[r["source"]]["service"] == "reporting")
        self.bases = [b["id"] for b in self.gs.bases(query.scope)]

    def run_graph(self, steps, graph=None, context_id=None, **kwargs):
        return run_investigation(graph or self.graph, context_id or self.context["id"], model=Script(steps),
                                 graph_store=self.gs, **kwargs)

    def constitution(self, change):
        data = yaml.safe_load(Path(DEFAULT_PATH).read_text(encoding="utf-8"))
        change(data["actions"])
        path = Path(self.work.name) / "constitution.yaml"
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        return path


class GraphToolTests(GraphToolCase):
    def test_graph_answers_impact_but_its_ids_cannot_back_a_proposal(self):
        seen = {}
        steps = [
            act(name="graph_find", text="orders GET /orders", kind="operation", limit=10),
            lambda m: seen.update(find=tool_result(m)) or act(name="graph_impact", entity_id=self.orders_op, depth=2,
                                                               limit=20),
            lambda m: seen.update(impact=tool_result(m)) or act(
                name="propose_dependency", evidence_refs=self.bases[:2], claim=dict(
                    consumer_repository="reporting", consumer_service="reporting", provider_service="orders",
                    method="GET", path_template="/orders")),
            act(name="propose_hypothesis", evidence_refs=[self.reporting_rel], unknowns=["helper_semantics_unknown"],
                claim=dict(consumer_service="reporting", provider_service="orders", method="GET", route="/orders",
                           statement="The graph says so.")),
            act(name="finish", outcome="abstain", reason="insufficient_evidence")]
        report = self.run_graph(steps)
        self.assertEqual([h["id"] for h in seen["find"]["result"]], [self.orders_op])
        impact = seen["impact"]
        self.assertEqual((impact["graph_ids_are_not_evidence_refs"], impact["confirms_hypotheses"]), (True, False))
        self.assertEqual({p["consumer"] for p in impact["result"]["paths"]}, {"reporting", "archive"})
        owners = {a["service"]: (a["owner_status"], a["teams"]) for a in impact["result"]["affected"]}
        self.assertEqual(owners, {"reporting": ("KNOWN", ["team-reporting"]), "archive": ("UNKNOWN", [])})
        self.assertNotIn("text", json.dumps(impact))  # no source text in graph results
        self.assertEqual([(d["layer"], d["action"]) for d in report["diagnostics"]],
                         [("evidence", "propose_dependency"), ("evidence", "propose_hypothesis")])
        self.assertEqual((report["candidate_ids"], report["hypothesis_ids"]), ([], []))
        self.assertEqual(report["graph_version"], "graph-2")

    def test_hypothesis_made_after_a_graph_answer_stays_unverified(self):
        steps = [act(name="graph_impact", entity_id=self.orders_op, depth=1, limit=10),
                 self.read("reporting", "client.py", 1, 9),
                 lambda m: act(name="propose_hypothesis", evidence_refs=refs(m), unknowns=["requirement_unknown"],
                               claim=dict(consumer_service="reporting", provider_service="orders", method="GET",
                                          route="/orders", statement="Reporting may lose rows.")),
                 act(name="finish", outcome="complete", reason="done")]
        report = self.run_graph(steps)
        self.assertEqual((report["outcome"], report["status"]), ("hypotheses_only", "PARTIAL"))
        stored = self.graph.proposals(self.graph.context(self.context["id"]))
        self.assertEqual([p["trust"] for p in stored], ["UNAPPROVED_CANDIDATE"])

    def test_snapshot_is_the_callers_scope_and_does_not_change_during_the_run(self):
        narrow = Graph(Policy.model_validate(self.stand.policy(repositories=NARROW, model=MODEL)), self.store)
        context = narrow.prepare_context("ORD-12", revisions={k: v for k, v in self.stand.revisions(
            orders="hazards").items() if k in NARROW})
        seen = []
        steps = [act(name="graph_find", text="reporting", kind=None, limit=10),
                 lambda m: seen.append(tool_result(m)) or act(name="graph_relationship",
                                                              relationship_id=self.reporting_rel),
                 act(name="finish", outcome="abstain", reason="insufficient_evidence")]
        report = self.run_graph(steps, graph=narrow, context_id=context["id"])
        self.assertEqual(seen[0]["result"], [])
        self.assertEqual([(d["layer"], d["reason_code"]) for d in report["diagnostics"]], [("evidence", "not_found")])
        # A sync that lands while the model runs is not visible in this run's snapshot.
        other = Store(Path(self.work.name) / "other")
        try:
            removed = Graph(self.policy, other).prepare_context("ORD-12",
                                                                revisions=self.stand.revisions(orders="removed"))
        finally:
            other.close()
        statuses = []
        steps = [lambda m: self.gs.sync_code(removed) and act(name="graph_relationship",
                                                              relationship_id=self.reporting_rel),
                 lambda m: statuses.append(tool_result(m)["result"]["status"]) or act(
                     name="finish", outcome="abstain", reason="insufficient_evidence")]
        self.run_graph(steps, graph=self.graph, context_id=self.context["id"])
        self.assertEqual(statuses, ["ACTIVE"])


class GraphToolLimitTests(GraphToolCase):
    def test_constitution_limits_allowlist_and_missing_graph_are_tool_rejections(self):
        def tighter(actions):
            actions["graph_impact"]["max_depth"] = 1
            del actions["graph_owner"]
        steps = [act(name="graph_impact", entity_id=self.orders_op, depth=2, limit=10),
                 act(name="graph_find", text="orders", kind=None, limit=50),
                 act(name="graph_owner", service="reporting"),
                 act(name="finish", outcome="abstain", reason="insufficient_evidence")]
        report = self.run_graph(steps, constitution_path=self.constitution(tighter))
        self.assertEqual([(d["layer"], d["reason_code"], d["field_path"]) for d in report["diagnostics"]],
                         [("tool", "tool_limit", "action.depth"), ("tool", "tool_limit", "action.limit"),
                          ("tool", "tool_not_permitted", None)])
        self.assertEqual(report["outcome"], "invalid_actions")
        unconfigured = run_investigation(self.graph, self.context["id"], model=Script([
            act(name="graph_owner", service="reporting"),
            act(name="finish", outcome="abstain", reason="insufficient_evidence")]))
        self.assertEqual([(d["layer"], d["reason_code"]) for d in unconfigured["diagnostics"]],
                         [("tool", "graph_unavailable")])
        self.assertIsNone(unconfigured["graph_version"])

    def test_malformed_graph_calls_are_schema_rejections(self):
        steps = [act(name="graph_impact", entity_id="../../etc", depth=2, limit=10),
                 act(name="graph_find", text="orders", kind="team", limit=5),
                 act(name="finish", outcome="abstain", reason="insufficient_evidence")]
        report = self.run_graph(steps)
        self.assertEqual([(d["layer"], d["field_path"]) for d in report["diagnostics"]],
                         [("schema", "action.graph_impact.entity_id"), ("schema", "action.graph_find.kind")])
