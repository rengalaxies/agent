"""Harness: real service code against the local GitHub/Jira stands over HTTP.

Only the true boundaries are replaced: the clock (lease/backoff time travel)
and the analysis, which belongs to batch 2A and is out of scope here.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid

from agent_service.analysis import AnalysisUnavailable
from agent_service.connectors.github import GitHubConnector, StaticToken
from agent_service.connectors.jira import BasicAuth, JiraConnector
from agent_service.http import HttpClient
from agent_service.queue import Limits, ServiceStore
from agent_service.service import Service

from tests.service.clock import Clock
from agent_service.stands import GitHubStand, JiraStand, sign

GH_SECRET = b"github-webhook-secret"
JIRA_SECRET = b"jira-webhook-secret"
REPO = "acme/orders"
CONSUMER = "acme/reporting"
BASE = "b" * 40
HEAD1 = "1" * 40
HEAD2 = "2" * 40
CONSUMER_SHA = "c" * 40


class Crash(BaseException):
    """Simulated process death: not an Exception, so service code cannot swallow it."""


NOW = "2026-10-24T12:00:00Z"


def _service(request, name):
    return {"kind": "service", "installation_id": request["installation_id"],
            "environment": request["environment"], "service": name}


def _fresh(status="CURRENT", reasons=()):
    return {"status": status, "checked_at": NOW, "reasons": list(reasons)}


def orders_result(request: dict, *, schema_version="2.0", status=None) -> dict:
    """agent-graph-output 2.0 AnalysisResult for the Orders/Reporting example (spec section 5)."""
    pr, revisions = request.get("pr"), request["repository_revisions"]
    operation = {"kind": "operation", "installation_id": request["installation_id"],
                 "environment": request["environment"], "service": "orders", "method": "GET", "route": "/orders"}
    call = {"id": "ev-call", "origin": "code", "provenance": "AUTHENTIC", "sufficiency": "SUPPORTED_WITHIN_PROFILE",
            "freshness": _fresh(), "visibility": ["reporting"], "snapshot": "GIT_COMMIT", "repository": "reporting",
            "commit": revisions["reporting"], "blob": "4" * 40, "content_sha256": "5" * 64,
            "path": "reporting/export.py", "start_line": 12, "end_line": 14}
    runtime = {"id": "ev-runtime", "origin": "runtime", "provenance": "AUTHENTIC",
               "sufficiency": "OBSERVED_WITHIN_WINDOW", "freshness": _fresh("STALE", ["sampled_source"]),
               "visibility": ["access-log"], "source": "access-log", "consumer": _service(request, "reporting"),
               "provider": _service(request, "orders"), "window_start": "2026-10-23T00:00:00Z",
               "window_end": "2026-10-24T00:00:00Z"}
    calls = {"id": "rel-calls", "kind": "calls", "source": _service(request, "reporting"), "target": operation,
             "status": "ACTIVE", "origins": ["code", "runtime"], "evidence_refs": ["ev-call", "ev-runtime"],
             "freshness": _fresh(), "change_origin": "code_scan", "visibility": ["reporting", "orders"]}
    snapshots = [{"repository": "reporting", "mode": "GIT_COMMIT", "commit": revisions["reporting"],
                  "tree": "9" * 40, "role": "consumer"}]
    if pr:
        snapshots += [{"repository": "orders", "mode": "GIT_COMMIT", "commit": pr["base_sha"], "tree": "7" * 40,
                       "role": "base"},
                      {"repository": "orders", "mode": "GIT_COMMIT", "commit": pr["head_sha"], "tree": "8" * 40,
                       "role": "head"}]
    status = status or ("USEFUL" if pr else "PARTIAL")
    return {
        "schema": "agent-graph-output", "schema_version": schema_version, "kind": "analysis_result",
        "profile": "http-requests-4", "code_version": "test", "constitution_version": "agent-service-v1",
        "installation_id": request["installation_id"], "environment": request["environment"],
        "request_id": request["request_id"], "event_id": request["source_event"]["event_id"],
        "resource_version": request["source_event"]["resource_version"], "correlation_id": request["request_id"],
        "trigger_kind": request["trigger_kind"], "snapshots": snapshots, "graph_version": "graph-7",
        "status": status, "reason_code": "impact_found_within_profile" if pr else "owner_unknown",
        "summary": ("PR меняет размер страницы GET /orders со 100 на 20; Reporting вызывает без page_size."
                    if pr else "Задача касается GET /orders; вероятный потребитель Reporting."),
        "affected": [{"service": _service(request, "reporting"), "relationship_refs": ["rel-calls"],
                      "owner": {"status": "KNOWN", "source": "codeowners", "source_version": revisions["reporting"][:12],
                                "teams": [{"kind": "team", "installation_id": request["installation_id"],
                                           "team": "team-reporting"}]}}],
        "impact_paths": [{"relationship_refs": ["rel-calls"], "summary": "reporting.export -> orders GET /orders"}],
        "checks": [{"consumer": _service(request, "reporting"), "claim_refs": ["claim-1"],
                    "text": "Проверить, что выгрузка Reporting получает все страницы"}],
        "claims": [{"id": "claim-1", "kind": "fact", "statement": "Reporting вызывает GET /orders без page_size.",
                    "evidence_refs": ["ev-call"], "applicability": "закреплённые коммиты", "uncertainty": "LOW",
                    "unknowns": ["requirement_unknown"]}],
        "deltas": ([{"operation": operation, "code": "PAGE_DEFAULT_CHANGED", "before": 100, "after": 20,
                     "evidence_refs": ["ev-call"]}] if pr else []),
        "unknowns": [{"code": "requirement_unknown", "subject": "reporting"}]
        + ([] if pr else [{"code": "jira_without_diff"}]),
        "source_freshness": [{"source_kind": "runtime", "source_id": "access-log",
                              "freshness": _fresh("STALE", ["sampled_source"])}],
        "evidence": [call, runtime], "relationships": [calls], "model": None,
        "costs": {"model_calls": 0, "prompt_tokens": None, "completion_tokens": None, "reserved_micro": None,
                  "currency": None},
        "timings": {"started_at": NOW, "finished_at": NOW, "seconds": {"analysis": 0.1}},
    }


class ScriptedAnalyzer:
    def __init__(self):
        self.requests = []
        self.during = None  # callable(request) run inside analyze
        self.unavailable = 0  # raise AnalysisUnavailable this many times
        self.result = orders_result

    def analyze(self, request, *, attachments, cancelled):
        self.requests.append((request, attachments))
        if self.unavailable:
            self.unavailable -= 1
            raise AnalysisUnavailable("analysis_unavailable")
        if self.during:
            self.during(request)
        return self.result(request)


class Receiver:
    """FastAPI webhook receiver on a real local port (uvicorn)."""

    def __init__(self, service):
        import uvicorn

        from agent_service.api import create_app

        self.server = uvicorn.Server(uvicorn.Config(create_app(service, status_token="status-token"),
                                                    host="127.0.0.1", port=0, log_level="error", lifespan="off"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError("receiver did not start")
            time.sleep(0.01)
        self.url = f"http://127.0.0.1:{self.server.servers[0].sockets[0].getsockname()[1]}"

    def close(self):
        self.server.should_exit = True
        self.thread.join(timeout=10)


def post(url, body: bytes, headers: dict) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json",
                                                                          **headers})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, json.loads(exc.read() or b"{}")


class ServiceCase(unittest.TestCase):
    """Fresh stands, store and receiver per test."""

    limits = dict(lease_seconds=60, max_analysis_attempts=3, max_publish_attempts=4, backoff_base=5,
                  backoff_cap=60, create_settle_seconds=0)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = Clock()
        self.github = GitHubStand()
        self.jira = JiraStand()
        self.addCleanup(self.github.close)
        self.addCleanup(self.jira.close)
        self.github.add_pr(REPO, 7, head=HEAD1, base=BASE, title="ORD-1 Reduce default page size")
        self.github.branches[(CONSUMER, "main")] = CONSUMER_SHA
        self.github.branches[(REPO, "main")] = BASE
        self.jira.add_issue(10001, "ORD-1", "ORD", "Уменьшить стандартный размер страницы Orders со 100 до 20",
                            "GET /orders должен отдавать 20 записей по умолчанию")
        self.analyzer = ScriptedAnalyzer()
        self.db = Path(self.tmp.name) / "state" / "service.sqlite"
        self.hook = None
        self.service = self.make_service()
        self.receiver = Receiver(self.service)
        self.addCleanup(self.receiver.close)

    def make_service(self, hook=None) -> Service:
        store = ServiceStore(self.db, clock=self.clock, limits=Limits(**self.limits))
        gh_client = HttpClient(self.github.url, allow_loopback_http=True, clock=self.clock, timeout=5)
        jira_client = HttpClient(self.jira.url, allow_loopback_http=True, clock=self.clock, timeout=5)
        connectors = {
            "github": GitHubConnector(gh_client, StaticToken(self.github.token), repositories=[REPO],
                                      read_repositories={REPO: "main", CONSUMER: "main"},
                                      repository_ids={REPO: "orders", CONSUMER: "reporting"}, jira_project_keys=["ORD"],
                                      bot_login=self.github.bot_login, webhook_secret=GH_SECRET, clock=self.clock),
            "jira": JiraConnector(jira_client, BasicAuth("bot@example.invalid", "jira-test-token"),
                                  project_keys=["ORD"], bot_account_id=self.jira.bot_account_id,
                                  webhook_secret=JIRA_SECRET, clock=self.clock),
        }
        return Service(store=store, connectors=connectors, analyzer=self.analyzer, installation_id="inst-1",
                       environment="test", analysis_settings={"graph_version": "graph-7"},
                       hook=hook, worker_id=uuid.uuid4().hex)

    def restart(self, hook=None) -> Service:
        """New process on the same database after the old lease expired."""
        self.clock.advance(self.limits["lease_seconds"] + 1)
        self.service = self.make_service(hook)
        self.service.recover()
        return self.service

    # -- deliveries -------------------------------------------------------

    def pr_payload(self, head, action="synchronize", number=7, extra=None):
        pr = self.github.prs[(REPO, number)]
        payload = {"action": action, "number": number, "repository": {"full_name": REPO},
                   "pull_request": {"number": number, "title": pr["title"],
                                    "head": {"sha": head, "ref": pr["head"]["ref"]},
                                    "base": {"sha": BASE, "ref": "main"}}}
        payload.update(extra or {})
        return payload

    def deliver_github(self, payload, *, event="pull_request", delivery=None, secret=GH_SECRET):
        body = json.dumps(payload).encode()
        return post(self.receiver.url + "/webhooks/github", body, {
            "X-GitHub-Event": event, "X-GitHub-Delivery": delivery or uuid.uuid4().hex,
            "X-Hub-Signature-256": sign(secret, body)})

    def deliver_jira(self, payload, *, delivery=None, secret=JIRA_SECRET):
        body = json.dumps(payload).encode()
        return post(self.receiver.url + "/webhooks/jira", body, {
            "X-Atlassian-Webhook-Identifier": delivery or uuid.uuid4().hex, "X-Hub-Signature": sign(secret, body)})

    def jira_payload(self, event="jira:issue_updated", type_name="issue_generic", changelog=None):
        payload = {"webhookEvent": event, "issue_event_type_name": type_name, "timestamp": 1,
                   "issue": {"id": "10001", "key": "ORD-1", "fields": {"project": {"key": "ORD"}}},
                   "user": {"accountId": "human"}}
        if changelog is not None:
            payload["changelog"] = {"items": changelog}
        return payload

    def drain(self, max_steps=200):
        """Run the worker; advance the fake clock over backoff waits until idle."""
        outcomes = []
        for _ in range(20):
            outcomes += self.service.run_until_idle(max_steps)
            if not self._waiting():
                return outcomes
            self.clock.advance(self.limits["backoff_cap"] + 1)
        return outcomes

    def _waiting(self) -> bool:
        status = self.service.store.status()
        return bool(status["events"].get("RECEIVED") or status["jobs"].get("QUEUED")
                    or status["intents"].get("PENDING") or status["intents"].get("UNKNOWN")
                    or status["intents"].get("BLOCKED"))

    def pr_requests(self) -> int:
        return sum(1 for request, _ in self.analyzer.requests if request["trigger_kind"] == "pr")

    def pr_comments(self):
        return self.github.service_comments(REPO, 7)

    def jira_comments(self):
        return self.jira.comments["10001"]
