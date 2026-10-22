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
        # Core conservatively counts FastAPI decorators as unknown clients: do not hide this limitation.
        self.assertEqual(g["coverage"], "PARTIAL")
        self.assertTrue(any(gap["code"] == "unknown_http_client" for gap in g["gaps"]))

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
        self.assertEqual(j["status"], "PARTIAL")
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
