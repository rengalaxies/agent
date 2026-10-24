"""Batch 3 acceptance (spec section 9) on the Orders/Reporting Git stand: persistence,
per-basis invalidation, access filtering, ownership, freshness, recovery, migration."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

from agent_graph.contracts import GraphError, Policy, canonical
from agent_graph.engine import Graph
from agent_graph.graph_query import GraphQuery
from agent_graph.graph_store import GraphStore, OwnershipMapping
from agent_graph.graph_store_sync import GraphMaintainer
from agent_graph.store import Store, scope_id

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "examples/orders_reporting"))
import stand as git_stand  # noqa: E402

SCOPE = scope_id("acme", "prod")
REPORTING_SHIFTED = "# Reporting export client.\n# Reads one page.\n\n" + git_stand.REPORTING_CLIENT


def add_branch(stand, repository, branch, files, parent="main"):
    """Commit a new branch into a stand repository with the stand's own plumbing."""
    env = git_stand.git_env(stand.root / "git-home")
    repo = stand.repo(repository)
    tree = git_stand._tree(repo, env, files)
    sha = git_stand._git(repo, env, "commit-tree", tree, "-p", stand.commits[repository][parent],
                         "-m", f"{repository}: {branch}")
    git_stand._git(repo, env, "update-ref", f"refs/heads/{branch}", sha)
    stand.commits[repository][branch] = sha
    return sha


class StandCase(unittest.TestCase):
    """One Git stand per test class; every test gets fresh state directories."""

    @classmethod
    def setUpClass(cls):
        cls.stand_tmp = tempfile.TemporaryDirectory()
        cls.stand = git_stand.build_stand(Path(cls.stand_tmp.name) / "stand")
        requirements = git_stand.REPORTING_REQUIREMENTS
        add_branch(cls.stand, "reporting", "shifted", {"client.py": REPORTING_SHIFTED, "requirements.md": requirements})
        add_branch(cls.stand, "reporting", "renamed", {"exports/client.py": git_stand.REPORTING_CLIENT,
                                                       "requirements.md": requirements})

    @classmethod
    def tearDownClass(cls):
        cls.stand_tmp.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.stores = []

    def tearDown(self):
        for store in self.stores:
            store.close()
        self.tmp.cleanup()

    def open(self, name="state"):
        store = Store(self.root / name)
        self.stores.append(store)
        return store, GraphStore(store)

    def policy(self, repositories=None):
        return Policy.model_validate(self.stand.policy(repositories=repositories))

    def revisions(self, repositories=None, **branches):
        pins = self.stand.revisions(**branches)
        return {k: v for k, v in pins.items() if repositories is None or k in repositories}

    def context(self, graph, repositories=None, **branches):
        return graph.prepare_context(revisions=self.revisions(repositories, **branches))

    def citation(self, context, repository, path):
        source = next(s for s in context["sources"].values() if s["repository"] == repository and s["path"] == path)
        line = next(i for i, text in enumerate(source["text"].splitlines(), 1) if text.strip())
        return dict(source_id=source["id"], start_line=line, end_line=line, quote=source["text"].splitlines()[line - 1])

    def rel(self, query, consumer, service, route="/orders"):
        return next(r["id"] for r in query._rels.values()
                    if query._entities[r["source"]].get("service") == consumer
                    and query._entities[r["target"]].get("service") == service
                    and query._entities[r["target"]].get("route", route) == route and r["kind"] == "calls")


class RecomputeTests(StandCase):
    def setUp(self):
        super().setUp()
        self.store, _ = self.open("prepare")
        self.graph = Graph(self.policy(), self.store)
        self.base = self.context(self.graph)

    def assert_full_equals_incremental(self, head):
        _, incremental = self.open(f"incremental-{len(self.stores)}")
        incremental.sync_code(self.base)
        _, summary = incremental.sync_code(head)
        _, full = self.open(f"full-{len(self.stores)}")
        full.sync_code(head)
        self.assertEqual(incremental.canonical_facts(SCOPE), full.canonical_facts(SCOPE))
        return incremental, summary

    def test_full_and_incremental_builds_match_on_change_rename_and_deletion(self):
        changed, summary = self.assert_full_equals_incremental(self.context(self.graph, orders="pr-7"))
        self.assertEqual((summary["opened"], summary["closed"]), (1, 1))
        self.assertEqual([e["reason"] for e in changed.events(SCOPE) if e["event"] == "closed"], ["code_changed"])
        renamed, _ = self.assert_full_equals_incremental(self.context(self.graph, reporting="renamed"))
        (moved,) = [e for e in renamed.events(SCOPE) if e["event"] == "closed"]
        self.assertEqual(moved["reason"], "code_moved")
        self.assertIsNotNone(moved["successor"])
        removed, _ = self.assert_full_equals_incremental(self.context(self.graph, orders="removed"))
        reasons = sorted(e["reason"] for e in removed.events(SCOPE) if e["event"] == "closed")
        # The declaration is gone; reporting and archive still call a URL nobody declares.
        self.assertEqual(reasons, ["code_removed", "target_not_declared", "target_not_declared"])

    def test_line_shift_above_a_call_keeps_the_callsite_and_its_basis(self):
        _, gs = self.open("graph")
        gs.sync_code(self.base)
        _, summary = gs.sync_code(self.context(self.graph, reporting="shifted"))
        self.assertEqual(summary, dict(opened=0, transferred=1, reopened=0, closed=0))
        (call,) = [b for b in gs.bases(SCOPE) if b["data"].get("callsite", {}).get("service") == "reporting"]
        self.assertEqual((call["data"]["callsite"]["line"], call["data"]["callsite"]["symbol"]), (10, "load_day"))
        self.assertEqual(call["opened_version"], 1)

    def test_deleted_code_is_retracted_with_history_not_erased(self):
        _, gs = self.open("graph")
        gs.sync_code(self.base)
        gs.sync_code(self.context(self.graph, orders="removed"))
        query = GraphQuery.for_policy(gs, self.policy())
        view = query.relationship(self.rel(query, "reporting", "orders"))
        self.assertEqual(view["status"], "RETRACTED")
        self.assertEqual([h["closed_reason"] for h in view["history"]], ["target_not_declared"])
        gs.sync_code(self.base)
        self.assertEqual(GraphQuery.for_policy(gs, self.policy()).relationship(view["id"])["status"], "ACTIVE")
        self.assertIn("reopened", {e["event"] for e in gs.events(SCOPE)})


class KnowledgeTests(StandCase):
    def test_unrelated_edit_keeps_corrections_and_a_cited_change_makes_them_stale(self):
        store, _ = self.open()
        graph = Graph(self.policy(), store)
        base = self.context(graph)
        reporting = graph.propose(base["id"], dict(key="usage", kind="hypothesis", statement="Reads one page",
                                                   citations=[self.citation(base, "reporting", "client.py")]))
        orders = graph.propose(base["id"], dict(key="default", kind="hypothesis", statement="Default is 100",
                                                citations=[self.citation(base, "orders", "api.py")]))
        readme = self.context(graph, orders="readme-only")
        self.assertNotEqual(readme["basis"], base["basis"])
        statuses = {p["id"]: p["status"] for p in graph.proposals(readme)}
        self.assertEqual(statuses, {reporting["id"]: "CURRENT", orders["id"]: "CURRENT"})
        head = self.context(graph, orders="pr-7")
        result = {p["id"]: p for p in graph.proposals(head)}
        self.assertEqual(result[reporting["id"]]["status"], "CURRENT")
        self.assertEqual(result[orders["id"]]["status"], "STALE")
        self.assertIn("proposal_basis_differs", result[orders["id"]]["freshness"]["reasons"])

    def test_adding_an_allowed_repository_keeps_earlier_knowledge(self):
        store, _ = self.open()
        narrow = ["orders", "billing", "audit", "archive"]
        small = Graph(self.policy(narrow), store)
        context = self.context(small, narrow)
        made = small.propose(context["id"], dict(key="default", kind="hypothesis", statement="Default is 100",
                                                 citations=[self.citation(context, "orders", "api.py")]))
        wide = Graph(self.policy(), store)
        self.assertNotEqual(wide.view, small.view)
        statuses = {p["id"]: p["status"] for p in wide.proposals(self.context(wide))}
        self.assertEqual(statuses, {made["id"]: "CURRENT"})


class AccessTests(StandCase):
    def test_revoked_repository_disappears_from_graph_cache_counters_history_and_old_ids(self):
        store, gs = self.open()
        wide = Graph(self.policy(), store)
        base = self.context(wide)
        wide.propose(base["id"], dict(key="usage", kind="hypothesis", statement="Reads one page",
                                      citations=[self.citation(base, "reporting", "client.py")]))
        gs.sync_code(base)
        gs.sync_code(self.context(wide, orders="pr-7"))
        before = GraphQuery.for_policy(gs, self.policy())
        reporting_rel = self.rel(before, "reporting", "orders")

        narrow = ["orders", "billing", "audit", "archive"]
        query = GraphQuery.for_policy(gs, self.policy(narrow))
        self.assertEqual(query.find("reporting"), [])
        self.assertNotIn("reporting", query.summary()["services"])
        self.assertLess(query.summary()["active_bases"], before.summary()["active_bases"])
        with self.assertRaises(GraphError):
            query.relationship(reporting_rel)
        orders_op = next(h["id"] for h in query.find("orders GET /orders", "operation"))
        self.assertEqual({p["consumer"] for p in query.impact(orders_op)["paths"]}, {"archive"})
        self.assertNotIn("reporting", canonical(query.impact(orders_op)))
        # History of the remaining source survives the narrowing.
        declares = next(r for r in query._rels.values() if r["kind"] == "declares"
                        and query._entities[r["target"]]["service"] == "orders")
        self.assertEqual([h["closed_reason"] for h in query.relationship(declares["id"])["history"]], ["code_changed"])

        small = Graph(self.policy(narrow), store)
        self.assertEqual(small.proposals(self.context(small, narrow)), [])
        for call in (lambda: small.context(base["id"]),
                     lambda: small.get_evidence(base["id"], self.citation(base, "reporting", "client.py"))):
            with self.assertRaises(GraphError) as raised:
                call()
            self.assertEqual(raised.exception.code, "not_found")
        # Widening again restores the memory: nothing was deleted.
        again = GraphQuery.for_policy(gs, self.policy())
        self.assertEqual(again.relationship(reporting_rel)["status"], "ACTIVE")
        self.assertEqual(len(wide.proposals(self.context(wide))), 1)


class OwnershipTests(StandCase):
    def mapping(self, version, **services):
        return OwnershipMapping(source="installation_mapping", version=version, services=services)

    def test_owner_change_keeps_history_and_unknown_or_conflicting_owner_is_never_named(self):
        _, gs = self.open()
        gs.sync_code(self.context(Graph(self.policy(), self.stores[0])))
        original = json.loads((self.stand.root / "ownership.json").read_text())
        gs.sync_ownership("acme", "prod", OwnershipMapping.model_validate(original))
        query = GraphQuery.for_policy(gs, self.policy())
        self.assertEqual(query.owner("orders")["teams"][0]["team"], "team-orders")
        self.assertEqual(query.owner("audit"), dict(status="UNKNOWN", teams=[], source=None, source_version=None,
                                                    checked_at=None))
        gs.sync_ownership("acme", "prod", self.mapping("ownership-2", orders="team-platform",
                                                       reporting=["team-reporting", "team-finance"]))
        query = GraphQuery.for_policy(gs, self.policy())
        self.assertEqual((query.owner("orders")["status"], query.owner("orders")["teams"][0]["team"]),
                         ("KNOWN", "team-platform"))
        self.assertEqual([(h["team"], h["closed_reason"]) for h in query.owner_history("orders")],
                         [("team-orders", "ownership_changed"), ("team-platform", None)])
        conflict = query.owner("reporting")
        self.assertEqual((conflict["status"], sorted(t["team"] for t in conflict["teams"])),
                         ("CONFLICT", ["team-finance", "team-reporting"]))
        self.assertEqual(query.owner("archive")["status"], "UNKNOWN")

    def test_unreadable_ownership_source_keeps_last_owner_and_turns_stale(self):
        store, gs = self.open()
        maintainer = GraphMaintainer(Graph(self.policy(), store), gs, ownership_path=self.stand.root / "ownership.json")
        maintainer.reconcile(self.revisions())
        maintainer.ownership_path = self.root / "missing.json"
        self.assertEqual(maintainer.on_ownership_change()["status"], "UNAVAILABLE")
        query = GraphQuery.for_policy(gs, self.policy())
        self.assertEqual(query.owner("orders")["status"], "KNOWN")
        (source,) = [s for s in query.source_freshness() if s["source_kind"] == "ownership"]
        self.assertEqual((source["freshness"]["status"], source["freshness"]["reasons"]),
                         ("STALE", ["source_unavailable"]))


class RecoveryTests(StandCase):
    def test_unavailable_repository_keeps_last_snapshot_stale_and_reconcile_resumes(self):
        store, gs = self.open()
        maintainer = GraphMaintainer(Graph(self.policy(), store), gs)
        maintainer.on_code_event(self.revisions())
        repo = self.stand.repo("reporting")
        parked = repo.with_name("reporting-parked")
        repo.rename(parked)
        try:
            maintainer.reconcile(self.revisions())
            query = GraphQuery.for_policy(gs, self.policy())
            view = query.relationship(self.rel(query, "reporting", "orders"))
            self.assertEqual(view["status"], "STALE")
            self.assertEqual(view["freshness"]["reasons"], ["source_unavailable"])
            self.assertEqual(query.relationship(self.rel(query, "archive", "orders"))["status"], "ACTIVE")
        finally:
            parked.rename(repo)
        # A missed event (orders moved to pr-7 meanwhile) is picked up by reconciliation.
        results = maintainer.reconcile(self.revisions(orders="pr-7"))
        self.assertEqual(results[0]["summary"]["closed"], 1)
        query = GraphQuery.for_policy(gs, self.policy())
        self.assertEqual(query.relationship(self.rel(query, "reporting", "orders"))["status"], "ACTIVE")
        self.assertEqual({s["status"] for s in query.source_freshness()}, {"OK"})


class MigrationTests(StandCase):
    V1 = """CREATE TABLE heads(view TEXT PRIMARY KEY, generation INTEGER, id TEXT);
            CREATE TABLE artifacts(id TEXT PRIMARY KEY, view TEXT, kind TEXT, data TEXT);
            CREATE TABLE proposals(id TEXT PRIMARY KEY, view TEXT, data TEXT);
            CREATE TABLE reservations(id TEXT PRIMARY KEY, installation TEXT, run TEXT, tokens INTEGER,
                micro INTEGER, currency TEXT, until REAL, active INTEGER);"""

    def legacy_state(self):
        """A v1 state file: context, head and proposal rows exactly as v1 wrote them."""
        source, _ = self.open("source")
        graph = Graph(self.policy(), source)
        context = self.context(graph)
        proposal = graph.propose(context["id"], dict(key="usage", kind="hypothesis", statement="Reads one page",
                                                     citations=[self.citation(context, "reporting", "client.py")]))
        legacy = self.root / "legacy"
        legacy.mkdir(mode=0o700)
        db = sqlite3.connect(legacy / "graph.sqlite3")
        db.executescript(self.V1)
        for table, columns in (("heads", "view,generation,id"), ("artifacts", "id,view,kind,data"),
                               ("proposals", "id,view,data")):
            db.executemany(f"INSERT INTO {table} VALUES({','.join('?' * len(columns.split(',')))})",
                           source.db.execute(f"SELECT {columns} FROM {table}").fetchall())
        db.commit()
        db.close()
        return legacy, context, proposal

    def test_v1_state_migrates_with_backup_and_keeps_contexts_and_corrections(self):
        legacy, context, proposal = self.legacy_state()
        store = Store(legacy)
        self.stores.append(store)
        self.assertTrue((legacy / "graph.v1-backup.sqlite3").exists())
        backup = sqlite3.connect(legacy / "graph.v1-backup.sqlite3")
        self.assertEqual(backup.execute("SELECT count(*) FROM sqlite_master WHERE name='graph_bases'").fetchone()[0], 0)
        backup.close()
        self.assertEqual(store.schema_version(), 2)
        graph = Graph(self.policy(), store)
        self.assertEqual(graph.context(context["id"]), context)
        self.assertEqual([(p["id"], p["status"]) for p in graph.proposals(context)], [(proposal["id"], "CURRENT")])
        gs = GraphStore(store)
        versions = gs.import_contexts()
        self.assertEqual(len(versions), 1)
        self.assertEqual(gs.import_contexts(), [])
        query = GraphQuery.for_policy(gs, self.policy())
        self.assertEqual(query.relationship(self.rel(query, "reporting", "orders"))["change_origin"], "migration")
        # A rolled-back v1 binary appends a proposal the v1 way; v2 still reads it.
        row = store.db.execute("SELECT id,view,data FROM proposals").fetchone()
        data = json.loads(row[2])
        data["proposal"]["statement"] = "Written by v1 after migration"
        store.db.execute("INSERT INTO proposals VALUES(?,?,?)", ("v1-row", row[1], canonical(data)))
        self.assertIn("Written by v1 after migration",
                      [p["proposal"]["statement"] for p in graph.proposals(context)])

    def test_newer_store_schema_is_refused(self):
        store, _ = self.open()
        store.db.execute("UPDATE meta SET value='3' WHERE key='store_schema'")
        store.close()
        self.stores.remove(store)
        with self.assertRaises(GraphError) as raised:
            Store(self.root / "state")
        self.assertEqual(raised.exception.code, "store_schema_newer")


if __name__ == "__main__":
    unittest.main()
