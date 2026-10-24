import time

from agent_graph_demo.contracts import DemoError
from agent_graph_demo.graph_cli import GraphCLI
from .helpers import DemoCase


class CLITests(DemoCase):
    def test_actual_cli_risk_identity_export_and_history(self):
        base = self.prepare()
        s = self.store.session(self.sid)
        a = self.store.get_artifact(self.sid, s["graph_ref"])
        self.assertEqual(len(a["dependencies"]), 3)
        op = {o["id"]: o for o in a["operations"]}
        health = next(d for d in a["dependencies"] if d["consumer"] == "Health")
        self.assertEqual(op[health["operation_id"]]["service"], "Status")
        self.assertEqual(op[health["operation_id"]]["path"], "/orders")
        for d in a["dependencies"]:
            if d["consumer"] != "Health":
                self.assertEqual(op[d["operation_id"]]["service"], "Orders")
        b = self.run_job("analyze_change", target_version="B", base_context_id=base)
        result = self.store.get_artifact(self.sid, b["result_ref"])
        risky = [
            f["consumer"]
            for f in result["findings"]
            if f["code"] == "POSSIBLE_TRUNCATION"
        ]
        self.assertEqual(risky, ["Reporting"])
        self.assertFalse(
            any(
                f["test_executed"] or f["compatibility_confirmed"]
                for f in result["findings"]
            )
        )
        evidence = result["deltas"][0]["evidence"]
        self.assertTrue(all(e.get("evidence_id") for e in evidence))
        self.run_job(
            "analyze_change",
            target_version="D",
            base_context_id=self.store.session(self.sid)["current_context_id"],
        )
        self.run_job(
            "analyze_change",
            target_version="E",
            base_context_id=self.store.session(self.sid)["current_context_id"],
        )
        g = self.store.get_artifact(self.sid, self.store.session(self.sid)["graph_ref"])
        self.assertEqual(
            {d["consumer"] for d in g["dependencies"]},
            {"Reporting", "Billing", "Health", "Export"},
        )
        self.assertEqual(
            len(self.store.get_artifact(self.sid, s["graph_ref"])["dependencies"]), 3
        )
        self.assertEqual(g["profile"], a["profile"])
        # The core used to count FastAPI route decorators as unknown clients (noise).
        # The shipped core leaves declarations to the provider pass: no such gap remains,
        # and every scenario file has an explicit coverage status instead.
        self.assertEqual(g["coverage"], "COMPLETE_WITHIN_PROFILE")
        self.assertFalse(any(gap["code"] == "unknown_http_client" for gap in g["gaps"]))
        statuses = {(f["repository"], f["path"]): f["status"] for f in g["file_coverage"]}
        self.assertEqual(statuses[("orders", "app.py")], "EXTRACTED")
        self.assertEqual(statuses[("reporting", "requirement.md")], "NOT_CODE")

    def test_actual_evidence_and_human_correction_do_not_create_edges(self):
        base = self.prepare()
        s = self.store.session(self.sid)
        graph = self.store.get_artifact(self.sid, s["graph_ref"])
        e = self.store.get_artifact(
            self.sid, graph["dependencies"][0]["evidence"][0]["evidence_id"]
        )
        proposal = dict(
            key="independent-note",
            kind="human_correction",
            statement="Human diagnostic note, not approval",
            citations=[e["citation"]],
            supersedes=None,
        )
        b = dict(
            action="propose",
            expected_revision=1,
            idempotency_key="note",
            payload=dict(context_id=base, proposal=proposal),
        )
        j = self.store.enqueue(self.sid, "operator", b)
        self.worker.run_once()
        j = self.store.job(j["id"])
        self.assertEqual(j["status"], "SUCCEEDED")  # no decorator noise gap any more
        g = self.store.get_artifact(self.sid, self.store.session(self.sid)["graph_ref"])
        self.assertEqual(len(g["dependencies"]), 3)
        self.assertEqual(g["proposals"][0]["trust"], "HUMAN_CORRECTION")
        self.assertEqual(g["proposals"][0]["actor"], "operator")
        first = g["proposals"][0]["id"]
        proposal.update(statement="Superseding human note", supersedes=first)
        self.store.enqueue(
            self.sid,
            "operator",
            {
                **b,
                "idempotency_key": "note-2",
                "payload": dict(context_id=base, proposal=proposal),
            },
        )
        self.worker.run_once()
        g = self.store.get_artifact(self.sid, self.store.session(self.sid)["graph_ref"])
        self.assertEqual(
            next(p for p in g["proposals"] if p["id"] == first)["status"], "SUPERSEDED"
        )
        self.run_job("analyze_change", target_version="B", base_context_id=base)
        g = self.store.get_artifact(self.sid, self.store.session(self.sid)["graph_ref"])
        self.assertTrue(any(p["status"] == "STALE" for p in g["proposals"]))

    def test_correction_on_b_does_not_fail_later_rescan_and_analysis(self):
        # Audit 2026-10-22 (PR #40 CI): the B correction's citation exists only in the
        # B context, so a D rescan and the D->E analysis failed with not_found.
        base = self.prepare()
        self.run_job("analyze_change", target_version="B", base_context_id=base)
        s = self.store.session(self.sid)
        b_context = s["current_context_id"]
        graph = self.store.get_artifact(self.sid, s["graph_ref"])
        reporting = next(d for d in graph["dependencies"] if d["consumer"] == "Reporting")
        cited = self.store.get_artifact(self.sid, reporting["evidence"][0]["evidence_id"])
        self.store.enqueue(
            self.sid,
            "operator",
            dict(
                action="propose",
                expected_revision=s["revision"],
                idempotency_key="b-note",
                payload=dict(
                    context_id=b_context,
                    proposal=dict(
                        key=reporting["id"],
                        kind="human_correction",
                        statement="Reporting owner notified about the B limit",
                        citations=[cited["citation"]],
                        supersedes=None,
                    ),
                ),
            ),
        )
        self.worker.run_once()
        self.run_job("analyze_change", target_version="D", base_context_id=b_context)
        self.run_job("prepare_context")
        self.run_job(
            "analyze_change",
            target_version="E",
            base_context_id=self.store.session(self.sid)["current_context_id"],
        )
        g = self.store.get_artifact(self.sid, self.store.session(self.sid)["graph_ref"])
        note = next(p for p in g["proposals"] if p["trust"] == "HUMAN_CORRECTION")
        self.assertEqual(note["status"], "STALE")
        evidence = self.store.get_artifact(
            self.sid, note["proposal"]["citations"][0]["evidence_id"]
        )
        self.assertEqual(
            (evidence["context_id"], evidence["scenario_version"]), (b_context, "B")
        )

    def test_invalid_output_overflow_deadline_and_cancel_safe(self):
        for script, expected in [
            ("print('not-json')", "cli_invalid_json"),
            ("print('x'*2200000)", "cli_output_limit"),
            ("import time; time.sleep(20)", "deadline_exceeded"),
            (
                'print(\'{"status":"ERROR","code":"denied"}\');raise SystemExit(2)',
                "denied",
            ),
        ]:
            path = self.root / "fake-python"
            path.write_text("#!/usr/bin/env python3\n" + script + "\n")
            path.chmod(0o755)
            cli = GraphCLI(self.settings.core_root, path)
            with self.assertRaisesRegex(DemoError, expected):
                cli.invoke(
                    self.snap.session_root(self.sid),
                    "prepare_context",
                    deadline=time.monotonic() + 0.4,
                    cancelled=lambda: False,
                )
        with self.assertRaisesRegex(DemoError, "cancelled"):
            self.cli.invoke(
                self.snap.session_root(self.sid),
                "prepare_context",
                deadline=time.monotonic() + 1,
                cancelled=lambda: True,
            )

    def test_core_pin_and_model_commands_fail_closed(self):
        with self.assertRaisesRegex(DemoError, "core_pin_mismatch"):
            GraphCLI(self.root)
        with self.assertRaisesRegex(DemoError, "model_unavailable"):
            self.cli.invoke(
                self.snap.session_root(self.sid),
                "investigate",
                deadline=time.monotonic() + 1,
                cancelled=lambda: False,
            )
