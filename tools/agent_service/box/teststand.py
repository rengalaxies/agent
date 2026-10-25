"""Long-running Orders/Reporting stand for acceptance of an INSTALLED box (CI, development).

    python teststand.py serve --dir DIR [--service-port 8090]

Builds the Git stand (examples/orders_reporting), starts the GitHub and Jira
HTTP stands of agent_service.stands on 127.0.0.1 and writes:

    DIR/box.yaml      configuration for ``box install`` pointing at the stands
    DIR/secrets.env   stand credentials and webhook secrets (test values)
    DIR/stand.json    URLs, including the control API below

Control API (127.0.0.1 only), used by the acceptance driver:

    POST /deliver/pr {"action": "opened"}           signed pull_request webhook to the service
    POST /push {"branch": "pr-7", "deliver": true}  move PR #7 head to a stand branch
    POST /deliver/jira {"event": "created"}         signed Jira webhook
    POST /jira/summary {"summary": "..."}           change ORD-12 (no webhook)
    GET  /comments                                  service comments and write counts
    POST /shutdown

These stands are local emulations of the documented endpoints, not the live
GitHub or Jira.
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sys
import threading
import uuid

APP = Path(__file__).resolve().parents[3]  # app/ of a release, or a source checkout
sys.path[:0] = [str(APP / "src"), str(APP)]


def main(argv=None) -> int:
    from agent_service.connectors.jira import adf_text
    from agent_service.smoke import ORG, load_stand_module, post
    from agent_service.stands import GitHubStand, JiraStand, sign

    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["serve"])
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--service-port", type=int, default=8090)
    args = parser.parse_args(argv)
    root = args.dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    module = load_stand_module()
    stand = module.build_stand(root / "stand")
    issue = module.JIRA_ISSUE
    github, jira = GitHubStand(), JiraStand()
    repos = {name: f"{ORG}/{name}" for name in stand.commits}
    for name, full in repos.items():
        github.branches[(full, "main")] = stand.head(name)
    github.add_pr(repos["orders"], 7, head=stand.head("orders", "readme-only"), base=stand.head(),
                  title="ORD-12 Reduce the default page size", head_ref="pr-7")
    fields = issue["text_fields"]
    jira.add_issue(10012, issue["key"], issue["project"], fields["summary"], fields["description"])
    gh_secret, jira_secret = secrets.token_hex(16), secrets.token_hex(16)
    service_url = f"http://127.0.0.1:{args.service_port}"
    policy = stand.policy()
    config = {
        "installation_id": module.INSTALLATION, "environment": module.ENVIRONMENT,
        "listen": {"host": "127.0.0.1", "port": args.service_port},
        "github": {"api_base": github.url, "bot_login": github.bot_login, "auth": {"kind": "token"},
                   "repositories": [{"name": full, "service": module.SERVICES[name], "id": name,
                                     "watch_prs": name == "orders", "clone_url": str(stand.repo(name))}
                                    for name, full in sorted(repos.items())]},
        "jira": {"base_url": jira.url, "project_keys": [issue["project"]], "bot_account_id": jira.bot_account_id},
        "service_addresses": {a["service"]: a["base_url"] for a in policy["addresses"]},
        "ownership_file": str(stand.root / "ownership.json"),
        "requirements": policy["requirements"],
        "publication": "live",
        "freshness": {"reconcile_seconds": 60, "mirror_sync_seconds": 30},
        "limits": {"create_settle_seconds": 0},
        "testing": {"allow_loopback_http": True, "allow_local_sources": True, "fault_hooks": True},
    }
    (root / "box.yaml").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")  # JSON is valid YAML
    (root / "secrets.env").write_text(
        f"GITHUB_TOKEN={github.token}\nGITHUB_WEBHOOK_SECRET={gh_secret}\nJIRA_EMAIL=bot@example.invalid\n"
        f"JIRA_API_TOKEN=jira-test-token\nJIRA_WEBHOOK_SECRET={jira_secret}\n", encoding="utf-8")

    def deliver_pr(action):
        pr = github.prs[(repos["orders"], 7)]
        body = json.dumps({"action": action, "number": 7, "repository": {"full_name": repos["orders"]},
                           "pull_request": {"number": 7, "title": pr["title"], "head": dict(pr["head"]),
                                            "base": dict(pr["base"])}}).encode()
        return post(service_url + "/webhooks/github", body, {
            "X-GitHub-Event": "pull_request", "X-GitHub-Delivery": uuid.uuid4().hex,
            "X-Hub-Signature-256": sign(gh_secret.encode(), body)})

    def deliver_jira(event):
        name = {"created": ("jira:issue_created", "issue_created"),
                "updated": ("jira:issue_updated", "issue_generic")}[event]
        body = json.dumps({"webhookEvent": name[0], "issue_event_type_name": name[1], "timestamp": 1,
                           "issue": {"id": "10012", "key": issue["key"],
                                     "fields": {"project": {"key": issue["project"]}}}}).encode()
        return post(service_url + "/webhooks/jira", body, {
            "X-Atlassian-Webhook-Identifier": uuid.uuid4().hex, "X-Hub-Signature": sign(jira_secret.encode(), body)})

    def comments():
        pr = github.service_comments(repos["orders"], 7)
        return {"pr": [{"id": c["id"], "first_line": c["body"].splitlines()[0], "body": c["body"]} for c in pr],
                "jira": [{"id": c["id"], "text": adf_text(c["body"])} for c in jira.comments["10012"]],
                "creates": {"github": github.count("POST", r"/repos/acme/orders/issues/7/comments"),
                            "jira": jira.count("POST", r"/rest/api/3/issue/10012/comment")},
                "updates": {"github": github.count("PATCH", r"/repos/acme/orders/issues/comments/\d+"),
                            "jira": jira.count("PUT", r"/rest/api/3/issue/10012/comment/\d+")},
                "heads": {b: stand.head("orders", b) for b in ("readme-only", "unclassified", "pr-7")}}

    stop = threading.Event()

    class Control(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _reply(self, status, payload):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/comments":
                return self._reply(200, comments())
            self._reply(404, {})

        def do_POST(self):
            length = int(self.headers.get("content-length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/deliver/pr":
                status, payload = deliver_pr(body.get("action", "opened"))
                return self._reply(200, {"status": status, "response": payload})
            if self.path == "/push":
                github.set_head(repos["orders"], 7, stand.head("orders", body["branch"]))
                result = deliver_pr("synchronize") if body.get("deliver", True) else (None, None)
                return self._reply(200, {"status": result[0], "response": result[1]})
            if self.path == "/deliver/jira":
                status, payload = deliver_jira(body.get("event", "created"))
                return self._reply(200, {"status": status, "response": payload})
            if self.path == "/jira/summary":
                jira.set_summary(10012, body["summary"])
                return self._reply(200, {"ok": True})
            if self.path == "/shutdown":
                stop.set()
                return self._reply(200, {"ok": True})
            self._reply(404, {})

    control = ThreadingHTTPServer(("127.0.0.1", 0), Control)
    threading.Thread(target=control.serve_forever, daemon=True).start()
    info = {"control": f"http://127.0.0.1:{control.server_address[1]}", "github": github.url, "jira": jira.url,
            "service": service_url, "box_config": str(root / "box.yaml"), "secrets": str(root / "secrets.env")}
    (root / "stand.json").write_text(json.dumps(info, indent=2) + "\n")
    print(json.dumps(info), flush=True)
    stop.wait()
    control.shutdown()
    github.close()
    jira.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
