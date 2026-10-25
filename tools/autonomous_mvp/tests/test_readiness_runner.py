"""6-r1 runner and baseline on real stands: the real service, real Git, the oracle out of reach."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from tools.autonomous_mvp.readiness import baseline, program, runner, scorer
from tools.autonomous_mvp.readiness.bench import ChangeBench, materialize
from tools.autonomous_mvp.transport import ScriptedTransport, TransportResult

_, _, CHANGES = program.load()
ORACLE = program.load_oracle("development")


def without_oracle(directory):
    """A copy of the program with change files only: what the runner and baseline may see."""
    base = Path(directory) / "program"
    shutil.copytree(program.PROGRAM_DIR / "changes", base / "changes")
    shutil.copy(program.PROGRAM_DIR / "program.json", base / "program.json")
    return base


class ServiceEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = without_oracle(cls.tmp.name)
        cls.ledger, cls.path = runner.run_split("development", only=["D01", "D08"], base=base,
                                                out=Path(cls.tmp.name) / "ledger.json")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_runs_without_the_oracle_and_records_both_stages_and_the_merge(self):
        self.assertFalse((Path(self.tmp.name) / "program" / "oracle").exists())
        records = {r["change_id"]: r for r in self.ledger["records"]}
        self.assertEqual(set(records), {"D01", "D08"})
        for record in records.values():
            self.assertIsNone(record["error"], record.get("traceback"))
            self.assertEqual(record["merge"]["provider_source_version"], record["merge"]["head"])
            self.assertEqual(record["costs"]["model_calls"], 0)
            self.assertEqual(record["human"]["status"], "NOT_RECORDED")
        self.assertFalse(self.ledger["manifest_current"])  # a copied program without a manifest is not frozen

    def test_one_comment_per_resource_and_redelivery_writes_nothing(self):
        for record in self.ledger["records"]:
            for stage in ("jira", "pr"):
                pub = record[stage]["publication"]
                self.assertEqual((pub["comments"], pub["creates"], pub["writes_after_redelivery"]), (1, 1, 0),
                                 (record["change_id"], stage))
                self.assertFalse(pub["lost"] or pub["duplicate"] or pub["stale"])
                self.assertTrue(record[stage]["redelivery_duplicate"])
                self.assertIsNotNone(record[stage]["latency_seconds"])

    def test_scored_against_the_oracle_the_core_path_answers_the_truncation_change(self):
        report = scorer.score(self.ledger, {k: ORACLE[k] for k in ("D01", "D08")})
        rows = {r["change_id"]: r for r in report["per_change"]}
        self.assertTrue(rows["D01"]["useful"], rows["D01"])
        self.assertEqual(report["stages"]["jira"]["revoked_leaks"] + report["stages"]["pr"]["revoked_leaks"], 0)


class PublicationCounters(unittest.TestCase):
    def test_a_second_service_comment_on_the_stand_is_reported_as_a_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            bench = ChangeBench(CHANGES["D03"], Path(tmp))
            try:
                stage = runner.run_stage(bench, "jira", lambda d: bench.deliver_jira(d))
                self.assertFalse(stage["publication"]["duplicate"])
                issue = bench.jira.comments[bench.issue_id]
                issue.append(dict(issue[0], id="9999"))
                comments = bench.jira_comments()
                pub = runner.publication(bench, bench.jira_resource(), comments, bench.jira.writes, bench.jira.writes)
                self.assertTrue(pub["duplicate"])
            finally:
                bench.close()


class HeldOutGuard(unittest.TestCase):
    def test_heldout_refuses_a_stale_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = without_oracle(tmp)
            with self.assertRaises(SystemExit) as caught:
                runner.run_split("heldout", base=base)
            self.assertIn("manifest_stale", str(caught.exception))

    def test_heldout_never_overwrites_its_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "heldout-service-no-model.json"
            path.write_text("{}")
            with self.assertRaises(SystemExit) as caught:
                runner.guard("heldout", path, manifest_current=True)
            self.assertIn("heldout_already_run", str(caught.exception))
            runner.guard("development", path, manifest_current=False)  # development may rerun


class BaselineSources(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.change = CHANGES["D08"]  # one revoked consumer
        cls.commits = materialize(cls.change, Path(cls.tmp.name) / "stand")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def workspace(self, stage):
        return baseline.Workspace(self.change, Path(self.tmp.name) / "stand", self.commits, stage)

    def test_revoked_repository_is_not_readable(self):
        revoked = self.change["grants"]["revoked"][0]
        ws = self.workspace("jira")
        self.assertNotIn(revoked, ws.call("list_repositories", {})["repositories"])
        self.assertEqual(ws.call("read_file", dict(repository=revoked, path="client.py")),
                         dict(error="repository_not_readable"))
        hits = ws.call("search", dict(pattern=ORACLE["D08"]["world"]["operation"]["route"]))["hits"]
        self.assertNotIn(revoked, {h["repository"] for h in hits})

    def test_provider_is_read_at_the_pr_head_only_on_the_pr_stage(self):
        provider = self.change["pr"]["repository"]
        facts = ORACLE["D08"]["world"]
        route = facts["operation"]["route"]
        jira = self.workspace("jira").call("read_file", dict(repository=provider, path="api.py"))["text"]
        pr = self.workspace("pr").call("read_file", dict(repository=provider, path="api.py"))["text"]
        self.assertIn(f"= {facts['defaults']['main'][route]})", jira)
        self.assertIn(f"= {facts['defaults']['change'][route]})", pr)

    def test_protocol_counts_invalid_actions_and_stops_at_the_limit(self):
        def reply(content):
            return TransportResult(ok=True, code="ok", content=content)

        transport = ScriptedTransport([reply("not json"), reply(json.dumps(dict(action="search", arguments=dict(
            pattern="client"))), ), reply(json.dumps(dict(action="finish", arguments=dict(outcome="answer",
                                                                                      impacted=[]))))])
        run = baseline.run_agent(transport, self.workspace("jira"), "task")
        self.assertEqual(run["terminal"], "finished")
        self.assertEqual([s["code"] for s in run["steps"]], ["invalid_action", "ok", "ok"])
        # The search result went back to the agent as the next user message.
        self.assertIn('"action": "search"', transport.sent[2]["messages"][-1]["content"])
        endless = ScriptedTransport([reply(json.dumps(dict(action="list_repositories", arguments={})))] * 20)
        self.assertEqual(baseline.run_agent(endless, self.workspace("jira"), "task")["terminal"], "step_limit")
        failing = ScriptedTransport([TransportResult(ok=False, code="http_unauthorized")])
        self.assertEqual(baseline.run_agent(failing, self.workspace("jira"), "task")["terminal"], "transport_error")

    def test_a_finish_without_a_valid_outcome_is_not_an_answer(self):
        bad = TransportResult(ok=True, code="ok", content=json.dumps(dict(action="finish", arguments=dict(
            outcome="maybe", impacted=[]))))
        run = baseline.run_agent(ScriptedTransport([bad] * 3), self.workspace("pr"), "task")
        self.assertEqual((run["terminal"], run["answer"]), ("invalid_actions", None))


if __name__ == "__main__":
    unittest.main()
