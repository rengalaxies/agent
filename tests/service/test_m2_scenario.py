"""Reproducible LOCAL acceptance using the real core and Orders/Reporting Git objects.

Run: python -m tests.service.test_m2_scenario --output work/m2/scenario.json
This never contacts Jira Cloud or GitHub and never calls a model.
"""
import argparse
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from agent_service.smoke import SmokeBench, post
from agent_service.stands import Fault, sign


def run_scenario(root):
    bench = SmokeBench(Path(root).resolve())
    checks, deliveries, observations = [], [], []
    rid = "github:acme/orders#7"

    def check(name, condition):
        checks.append({"check": name, "result": "PASS" if condition else "FAIL", "level": "LOCAL"})

    def send_pr(action="synchronize", *, body=None, event_id=None, event="pull_request"):
        pr = bench.github.prs[("acme/orders", 7)]
        body = body or json.dumps({"action": action, "number": 7,
                                  "repository": {"full_name": "acme/orders"}, "pull_request": pr}).encode()
        event_id = event_id or uuid.uuid4().hex
        status, reply = post(bench.receiver.url + "/webhooks/github", body, {
            "X-GitHub-Event": event, "X-GitHub-Delivery": event_id,
            "X-Hub-Signature-256": sign(bench.gh_secret, body)})
        deliveries.append({"provider": "github", "event_id": event_id, "status": status,
                           "duplicate": reply.get("duplicate"), "state": reply.get("state")})
        return body, event_id

    def observe(stage):
        jobs = bench.service.store.jobs(rid)
        observations.append({"stage": stage, "jira_comments": bench.jira_texts(),
                             "pr_comments": bench.pr_comments(),
                             "jobs": [{k: j[k] for k in ("job_id", "event_id", "resource_version", "generation",
                                                         "state", "result")} for j in jobs]})

    try:
        # Local fake clock backoff is zero only to avoid wall-clock waits on injected 503.
        bench.service.store.limits.backoff_base = 0
        status, reply = bench.deliver_jira()
        deliveries.append({"provider": "jira", "event_id": reply["event_id"], "status": status})
        bench.drain()
        jira = bench.jira_texts()[0]
        check("jira_preliminary_with_limits", status == 202 and "предварительный" in jira
              and "jira_without_diff" in jira and "reporting:" in jira)
        check("deterministic_mode_explained", "Детерминированный результат" in jira)
        observe("preliminary")

        bench.github.set_head("acme/orders", 7, bench.stand.head("orders", "pr-7"))
        breaking_body, breaking_id = send_pr("opened")
        bench.drain()
        [comment] = bench.pr_comments()
        comment_id = comment["id"]
        check("pr_refines_with_evidence_and_commits", "POSSIBLE_TRUNCATION у reporting" in comment["body"]
              and "код reporting@" in comment["body"] and "ORD-12" in comment["body"]
              and bench.stand.head("orders", "pr-7")[:12] in comment["body"])
        observe("breaking")

        # Revert the page-size behavior to 100 while retaining a neutral README change.
        bench.github.set_head("acme/orders", 7, bench.stand.head("orders", "readme-only"))
        bench.github.faults.append(Fault("PATCH", r".*/issues/comments/\d+", status=503))
        fixed_body, fixed_id = send_pr()
        bench.drain()
        [fixed] = bench.pr_comments()
        # The disappeared risk is named only in "what changed since the previous result".
        earlier, _, current = fixed["body"].partition("**Что может затронуть**")
        check("fixed_head_replaces_risk_in_same_comment", fixed["id"] == comment_id
              and "POSSIBLE_TRUNCATION" not in current and "no_supported_delta" in current
              and "POSSIBLE_TRUNCATION у reporting. В текущей версии не обнаружено." in earlier)
        check("transient_api_failure_recovers", any(h["entry"] == "intent_retry"
              and h["detail"].get("reason") == "provider_unavailable" for h in bench.service.store.history(rid)))
        observe("fixed")

        count = len(bench.service.store.jobs(rid))
        writes = len(bench.github.written)
        send_pr(body=fixed_body, event_id=fixed_id)
        send_pr(body=breaking_body, event_id=breaking_id)  # duplicate old delivery
        send_pr(body=breaking_body)  # late old payload with a new delivery id: fetch wins
        bench.drain()
        check("duplicates_and_reordering_no_extra_analysis_or_writes",
              len(bench.service.store.jobs(rid)) == count and len(bench.github.written) == writes)
        check("one_comment_create", bench.github.count("POST", r".*/issues/7/comments") == 1)

        send_pr(body=json.dumps({"action": "created", "repository": {"full_name": "acme/orders"},
                                 "issue": {"number": 7}, "comment": fixed}).encode(), event="issue_comment")
        bench.deliver_jira("comment_created", "issue_commented")
        bench.deliver_jira("jira:issue_updated", "issue_commented")
        bench.drain()
        check("own_comments_do_not_loop", len(bench.service.store.jobs(rid)) == count
              and len(bench.service.store.jobs("jira:10012")) == 1)

        issue = bench.jira.issues["10012"]["fields"]
        issue["summary"] = "Change default page_size 100 -> 20"
        issue["description"] = "GET /orders: default page_size 100 -> 20"  # declared by Orders and Billing
        bench.deliver_jira("jira:issue_updated", "issue_generic")
        bench.drain()
        check("ambiguous_jira_abstains", "intent_unclear" in bench.jira_texts()[0])
        observe("ambiguous")
        events = bench.service.store.history()
        return {"level": "LOCAL", "result": "PASS" if all(c["result"] == "PASS" for c in checks) else "FAIL",
                "model": "OFF", "external_endpoints": "NOT_RUN", "checks": checks,
                "deliveries": deliveries, "observations": observations, "history": events,
                "base_head": {"base": bench.stand.head(), "breaking": bench.stand.head("orders", "pr-7"),
                              "fixed": bench.stand.head("orders", "readme-only")}}
    finally:
        bench.close()


class M2ScenarioTest(unittest.TestCase):
    def test_jira_linked_pr_fix_duplicates_api_failure_and_abstention(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = run_scenario(tmp)
        self.assertEqual([c["check"] for c in report["checks"] if c["result"] != "PASS"], [])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        report = run_scenario(tmp)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"level": report["level"], "result": report["result"], "checks": report["checks"]}))
    raise SystemExit(0 if report["result"] == "PASS" else 1)
