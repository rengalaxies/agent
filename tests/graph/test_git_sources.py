import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zlib

from agent_graph.contracts import GraphError, Policy, digest
from agent_graph.engine import Graph
from agent_graph.sources import collect
from agent_graph.store import Store

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples/orders_reporting"))
from stand import build_stand, git_env  # noqa: E402


def facts(context):
    """Canonical facts: no run_id, timestamps, latency or store-specific ids."""
    return digest(dict(basis=context["basis"], graph=context["graph"], inventory=context["inventory"],
                       snapshots=context["snapshots"]))


class StandCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.stand = build_stand(Path(cls.tmp.name) / "stand")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.stores = []

    def tearDown(self):
        for store in self.stores:
            store.close()
        self.work.cleanup()

    def graph(self, policy=None, name="state"):
        store = Store(Path(self.work.name) / name)
        self.stores.append(store)
        return Graph(Policy.model_validate(policy or self.stand.policy()), store)

    def git(self, repo, *args, data=None):
        env = git_env(self.stand.root / "git-home")
        return subprocess.run(["git", "--git-dir", str(self.stand.repo(repo) / ".git"), *args], input=data,
                              env=env, stdout=subprocess.PIPE, check=True).stdout.decode().strip()


class ReproducibilityTests(StandCase):
    def test_same_commit_map_gives_same_facts_in_separate_stands_and_stores(self):
        other = build_stand(Path(self.work.name) / "second")
        self.assertEqual(other.commits, self.stand.commits)
        first = self.graph().prepare_context(revisions=self.stand.revisions())
        g2 = self.graph(other.policy(), name="other")
        second = g2.prepare_context(revisions=other.revisions())
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertEqual(facts(first), facts(second))
        self.assertEqual(first["metrics"]["scan_passes"], 1)

    def test_worktree_edit_does_not_change_a_pinned_snapshot(self):
        g = self.graph()
        before = g.prepare_context(revisions=self.stand.revisions())
        (self.stand.repo("orders") / "api.py").write_text("raise SystemExit('worktree only')\n")
        self.addCleanup((self.stand.repo("orders") / "api.py").unlink)
        after = g.prepare_context(revisions=self.stand.revisions())
        self.assertEqual(facts(before), facts(after))
        op = next(o for o in after["graph"]["operations"] if o["service"] == "orders")
        self.assertEqual(op["page_size_default"], 100)
        api = next(s for s in after["sources"].values() if s["repository"] == "orders" and s["path"] == "api.py")
        self.assertEqual((api["snapshot"], api["commit"]), ("GIT_COMMIT", self.stand.head()))

    def test_pinned_context_stays_current_without_rescanning(self):
        g = self.graph()
        c = g.prepare_context(revisions=self.stand.revisions())
        self.assertEqual(g.freshness(c)["status"], "CURRENT")
        self.assertEqual(g.freshness(c)["comparison_basis"], "PINNED_COMMITS")

    def test_repository_unavailable_since_prepare_keeps_the_context_current(self):
        # Reported by mvp-2b-prep on dde1f90: a repository root missing at prepare time
        # made every later freshness check UNKNOWN, so investigations failed stale_context.
        policy = self.stand.policy(repositories=["orders", "reporting"])
        policy["repositories"][1]["root"] = str(Path(self.work.name) / "missing")
        g = self.graph(policy)
        pins = {k: v for k, v in self.stand.revisions().items() if k in ("orders", "reporting")}
        c = g.prepare_context(revisions=pins)
        self.assertIn(dict(code="commit_unavailable", repository="reporting"), c["graph"]["gaps"])
        self.assertEqual(g.freshness(c)["status"], "CURRENT")
        self.assertEqual(g.freshness(c)["reasons"], ["partial_coverage"])
        g._current(c)  # the investigation precondition holds

    def test_repository_lost_after_prepare_is_not_current(self):
        copy = Path(self.work.name) / "reporting-copy"
        shutil.copytree(self.stand.repo("reporting"), copy)
        policy = self.stand.policy(repositories=["orders", "reporting"])
        policy["repositories"][1]["root"] = str(copy)
        g = self.graph(policy)
        pins = {k: v for k, v in self.stand.revisions().items() if k in ("orders", "reporting")}
        c = g.prepare_context(revisions=pins)
        self.assertEqual(g.freshness(c)["status"], "CURRENT")
        shutil.rmtree(copy, onexc=lambda f, path, _: (os.chmod(path, stat.S_IWRITE), f(path)))
        self.assertEqual(g.freshness(c)["status"], "UNKNOWN")


class CommitIdentityTests(StandCase):
    def orders(self, context):
        return [o for o in context["graph"]["operations"] if o["service"] == "orders"]

    def test_missing_or_foreign_commit_is_a_gap_not_the_current_branch(self):
        g = self.graph()
        for commit in ("f" * 40, self.stand.head("billing")):
            with self.subTest(commit=commit):
                c = g.prepare_context(revisions=self.stand.revisions() | {"orders": commit})
                self.assertIn(dict(code="commit_unavailable", repository="orders"), c["graph"]["gaps"])
                self.assertEqual(self.orders(c), [])
                self.assertEqual(c["coverage"], "PARTIAL")

    def test_commit_must_be_reachable_from_an_allowed_ref(self):
        tree = self.git("orders", "rev-parse", self.stand.head("orders", "pr-7") + "^{tree}")
        dangling = self.git("orders", "commit-tree", tree, "-m", "unreferenced")
        policy = self.stand.policy()
        g = self.graph(policy)
        c = g.prepare_context(revisions=self.stand.revisions() | {"orders": dangling})
        self.assertIn(dict(code="commit_unavailable", repository="orders"), c["graph"]["gaps"])
        policy["repositories"][0]["allowed_refs"] = ["refs/heads/main"]
        g = self.graph(policy, name="narrow")
        c = g.prepare_context(revisions=self.stand.revisions(orders="pr-7"))
        self.assertEqual(self.orders(c), [])
        c = g.prepare_context(revisions=self.stand.revisions())
        self.assertEqual(len(self.orders(c)), 1)

    def test_revision_map_is_validated(self):
        g = self.graph()
        for revisions, code in (({"orders": "main"}, "revision_required"),
                                ({"orders": "HEAD~1"}, "revision_required"),
                                ({"payments": "1" * 40}, "repository_not_allowed")):
            with self.subTest(revisions=revisions):
                with self.assertRaises(GraphError) as caught:
                    g.prepare_context(revisions=revisions)
                self.assertEqual(caught.exception.code, code)


class SafeReadTests(StandCase):
    def two(self):
        return {k: v for k, v in self.stand.revisions().items() if k in ("orders", "reporting")}

    def test_links_submodules_lfs_binary_and_large_files_are_visible_gaps(self):
        c = self.graph().prepare_context(revisions=self.stand.revisions(orders="hazards"))
        gaps = {(g["code"], g.get("path")) for g in c["graph"]["gaps"] if g.get("repository") == "orders"}
        self.assertLessEqual({("symlink_omitted", "link.py"), ("submodule_omitted", "vendor/lib"),
                              ("lfs_pointer_omitted", "data/orders.json"), ("binary_omitted", "data/blob.json"),
                              ("file_limit", "docs/big.md")}, gaps)
        paths = {s["path"] for s in c["sources"].values() if s["repository"] == "orders"}
        self.assertEqual(paths, {"README.md", "api.py", "docs/notes.md"})
        notes = [x for x in c["graph"]["candidates"] if x["kind"] == "UNTRUSTED_NOTE"]
        self.assertTrue(notes, "injection text stays an untrusted note")

    def test_repository_hooks_filters_and_fsmonitor_never_run(self):
        repo = self.stand.repo("orders")
        marker = Path(self.work.name) / "executed"
        command = f'"{sys.executable}" -c "open(r\'{marker}\', \'w\').write(\'x\')"'
        for key, value in (("core.fsmonitor", command), ("filter.evil.smudge", command),
                           ("filter.evil.process", command), ("core.pager", command),
                           ("diff.external", command)):
            self.git("orders", "config", key, value)
        self.addCleanup(lambda: [self.git("orders", "config", "--unset", k) for k in (
            "core.fsmonitor", "filter.evil.smudge", "filter.evil.process", "core.pager", "diff.external")])
        (repo / ".git/info/attributes").write_text("* filter=evil diff=evil\n")
        self.addCleanup((repo / ".git/info/attributes").unlink)
        hook = repo / ".git/hooks/post-checkout"
        hook.write_text(f"#!/bin/sh\n{command}\n")
        hook.chmod(0o755)  # executable, so a hook that ran would really leave the marker
        self.addCleanup(hook.unlink)
        c = self.graph().prepare_context(revisions=self.stand.revisions(orders="pr-7"))
        self.assertTrue(c["sources"])
        self.assertFalse(marker.exists())

    def test_partial_fetch_missing_blob_is_a_gap(self):
        copy = Path(self.work.name) / "partial"
        shutil.copytree(self.stand.repo("reporting"), copy)
        oid = self.git("reporting", "rev-parse", self.stand.head("reporting") + ":client.py")
        loose = copy / ".git/objects" / oid[:2] / oid[2:]
        os.chmod(loose, stat.S_IWRITE)
        loose.unlink()
        policy = self.stand.policy(repositories=["orders", "reporting"])
        policy["repositories"][1]["root"] = str(copy)
        c = self.graph(policy).prepare_context(revisions=self.two())
        self.assertIn(dict(code="object_unavailable", repository="reporting", path="client.py"), c["graph"]["gaps"])
        self.assertEqual(c["coverage"], "PARTIAL")

    def test_object_whose_content_does_not_match_its_id_is_rejected(self):
        copy = Path(self.work.name) / "tampered"
        shutil.copytree(self.stand.repo("reporting"), copy)
        oid = self.git("reporting", "rev-parse", self.stand.head("reporting") + ":client.py")
        loose = copy / ".git/objects" / oid[:2] / oid[2:]
        body = b"import requests\nrequests.get('https://orders.test/orders', params={'page_size': 1000})\n"
        os.chmod(loose, stat.S_IWRITE)
        loose.write_bytes(zlib.compress(b"blob %d\0" % len(body) + body))
        policy = self.stand.policy(repositories=["orders", "reporting"])
        policy["repositories"][1]["root"] = str(copy)
        with self.assertRaises(GraphError) as caught:
            collect(Policy.model_validate(policy), self.two())
        self.assertEqual(caught.exception.code, "object_hash_mismatch")


class ChangeTests(StandCase):
    def analyze(self, branch):
        g = self.graph()
        base = g.prepare_context(revisions=self.stand.revisions())
        return g.analyze_change(base["id"], revisions=self.stand.revisions(orders=branch))

    def test_pr_default_change_finds_reporting_and_not_lookalikes(self):
        r = self.analyze("pr-7")
        orders = [d for d in r["deltas"] if d["code"] == "PAGE_DEFAULT_CHANGED"]
        self.assertEqual([(d["before"], d["after"]) for d in orders], [(100, 20)])
        findings = {f["consumer"]: f for f in r["findings"]}
        self.assertEqual(findings["reporting"]["code"], "POSSIBLE_TRUNCATION")
        self.assertEqual(findings["reporting"]["requirement_ids"], ["reporting-complete"])
        self.assertEqual(findings["archive"]["code"], "RECHECK_REQUIRED")
        self.assertEqual(findings["archive"]["usage"], "CURSOR_LOOP_OBSERVED")
        self.assertNotIn("audit", findings, "audit calls billing's /orders")
        heads = {s["repository"]: s["commit"] for s in r["head_snapshots"]}
        bases = {s["repository"]: s["commit"] for s in r["base_snapshots"]}
        self.assertEqual((bases["orders"], heads["orders"]),
                         (self.stand.head(), self.stand.head("orders", "pr-7")))

    def test_tracked_operation_change_outside_known_deltas_is_unclassified(self):
        r = self.analyze("unclassified")
        self.assertEqual([d["code"] for d in r["deltas"]], ["UNCLASSIFIED_OPERATION_CHANGE"])
        delta = r["deltas"][0]
        self.assertEqual((delta["before"], delta["after"]), ("TRACKED_BASIS_CHANGED", "TRACKED_BASIS_CHANGED"))
        findings = {f["consumer"]: f for f in r["findings"]}
        self.assertEqual({f["code"] for f in findings.values()}, {"UNCLASSIFIED_CHANGE_RECHECK"})
        self.assertEqual(set(findings), {"reporting", "archive"})
        self.assertIn("unclassified_change", " ".join(r["unknowns"]))

    def test_readme_edit_has_no_delta_and_removal_is_reported(self):
        self.assertEqual(self.analyze("readme-only")["deltas"], [])
        removed = self.analyze("removed")
        self.assertEqual({d["code"] for d in removed["deltas"]}, {"OPERATION_REMOVED"})


if __name__ == "__main__":
    unittest.main()
