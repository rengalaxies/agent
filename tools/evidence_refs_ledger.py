"""Durable experiment accounting; Git ref compare-and-swap, no force/reset path."""
from __future__ import annotations

import base64
import copy
import json
import os
import re
import time
import urllib.error
import urllib.request

from agent_graph.contracts import GraphError, canonical

LEDGER_REF = "heads/experiment-state/evidence-refs-v2"
LEDGER_FILE = "ledger.json"


class GitHubLedgerBackend:
    """Single JSON file, immutable commits. Divergent updates fail non-fast-forward.

    Only initialize creates the ref. A missing ref during execute fails closed.
    An ambiguous write NEVER permits a model call or a new ledger fallback.
    """
    def __init__(self, repository, token):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not token:
            raise GraphError("invalid_ledger_configuration")
        self.repository, self._token = repository, token

    def _api(self, method, path, body=None, *, missing=False):
        data = canonical(body).encode() if body is not None else None
        request = urllib.request.Request(
            "https://api.github.com/repos/" + self.repository + path, data=data, method=method,
            headers={"Authorization": "Bearer " + self._token, "Accept": "application/vnd.github+json",
                     "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28"})
        try:
            # Use the configured proxy/CA. Do not follow credential-bearing redirects.
            opener = urllib.request.build_opener(_NoRedirect)
            with opener.open(request, timeout=15) as response:
                raw = response.read(4_000_001)
                if len(raw) > 4_000_000:
                    raise GraphError("ledger_response_limit")
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and missing:
                return None
            raise GraphError("ledger_write_conflict" if exc.code in (409, 422) else "ledger_http_error") from None
        except (OSError, ValueError, KeyError, urllib.error.URLError):
            raise GraphError("ledger_unavailable") from None

    def read(self, *, missing=False):
        ref = self._api("GET", "/git/ref/" + LEDGER_REF, missing=missing)
        if ref is None:
            return None, None
        head = ref["object"]["sha"]
        blob = self._api("GET", "/contents/" + LEDGER_FILE + "?ref=" + head)
        try:
            return head, json.loads(base64.b64decode(blob["content"], validate=False))
        except (ValueError, KeyError, TypeError):
            raise GraphError("invalid_ledger") from None

    def write(self, expected_head, state):
        blob = self._api("POST", "/git/blobs", {"content": canonical(state), "encoding": "utf-8"})
        tree = self._api("POST", "/git/trees", {"tree": [
            {"path": LEDGER_FILE, "mode": "100644", "type": "blob", "sha": blob["sha"]}]})
        commit = self._api("POST", "/git/commits", dict(
            message="Record evidence-refs-v2 accounting", tree=tree["sha"],
            parents=[expected_head] if expected_head else []))
        if expected_head is None:
            self._api("POST", "/git/refs", {"ref": "refs/" + LEDGER_REF, "sha": commit["sha"]})
        else:
            # A concurrent commit has the same old parent, so GitHub rejects it.
            self._api("PATCH", "/git/refs/" + LEDGER_REF, {"sha": commit["sha"], "force": False})
        return commit["sha"]

    def run_created_epoch(self, run_id):
        if not str(run_id).isdigit():
            raise GraphError("invalid_run_identity")
        from datetime import datetime
        run = self._api("GET", "/actions/runs/" + str(run_id))
        return datetime.fromisoformat(run["created_at"].replace("Z", "+00:00")).timestamp()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class RunLedger:
    def __init__(self, backend, packet, source_sha, *, clock=time.time):
        self.backend, self.packet, self.source_sha, self.clock = backend, packet, source_sha, clock
        self.head, self.state = backend.read(missing=True)
        if self.state is not None:
            if (self.state.get("manifest_digest") != packet["manifest_digest"]
                    or self.state.get("source_sha") != source_sha
                    or self.state.get("experiment_id") != packet["plan"]["experiment_id"]
                    or self.state.get("historical_requests") != packet["historical_requests"]):
                raise GraphError("ledger_identity_mismatch")

    def _save(self):
        # Work on a copy. Once a write is uncertain, caller must stop, not reuse it.
        data = canonical(self.state)
        for name in ("CLOUDRU_FOUNDATION_API_KEY", "GH_TOKEN", "GITHUB_TOKEN"):
            secret = os.environ.get(name)
            if secret and secret in data:
                raise GraphError("ledger_secret_detected")
        self.head = self.backend.write(self.head, copy.deepcopy(self.state))

    def initialize(self, request_cap, money_cap_micro):
        if self.state is not None:
            raise GraphError("ledger_already_initialized")
        maximum = len(self.packet["plan"]["models"]) * len(self.packet["plan"]["case_order"]) * self.packet["plan"]["parameters"]["max_model_steps"]
        if type(request_cap) is not int or not 1 <= request_cap <= maximum or type(money_cap_micro) is not int or money_cap_micro < 1:
            raise GraphError("explicit_new_budget_required")
        self.state = dict(schema="evidence-refs-ledger-1", experiment_id=self.packet["plan"]["experiment_id"],
                          manifest_digest=self.packet["manifest_digest"], source_sha=self.source_sha,
                          historical_requests=self.packet["historical_requests"], status="INITIALIZED",
                          request_cap=request_cap, money_cap_micro=money_cap_micro, currency="RUB",
                          attempts=[], cases=[], last_seen=self.clock(), run_id=None, deadline=None)
        self._save()

    def claim(self, run_id, *, started_epoch):
        if self.state is None:
            raise GraphError("ledger_missing_initialize_explicitly")
        if self.state["status"] != "INITIALIZED":
            raise GraphError("series_already_started_no_rerun")
        now = self.clock()
        if started_epoch > now + 1 or now < self.state["last_seen"]:
            raise GraphError("invalid_series_clock")
        self.state.update(status="RUNNING", run_id=run_id, started=started_epoch,
                          deadline=started_epoch + self.packet["plan"]["deadlines"]["series_seconds"])
        self._save()
        self.check()

    def check(self, case_key=None):
        now = self.clock()
        if self.state is None or self.state["status"] != "RUNNING":
            raise GraphError("series_not_running")
        if now < self.state["last_seen"]:
            self.state["status"] = "STOPPED_CLOCK"
            self._save()
            raise GraphError("clock_moved_backwards")
        self.state["last_seen"] = now
        deadline = self.state["deadline"]
        if case_key is not None:
            row = next((c for c in self.state["cases"] if c["key"] == case_key), None)
            if row is None:
                raise GraphError("unregistered_case")
            deadline = min(deadline, row["deadline"])
        if now >= deadline:
            # Fuse expiration durably: a later clock rollback cannot reopen it.
            self.state["status"] = "STOPPED_DEADLINE"
            self._save()
            raise GraphError("series_or_case_deadline")
        return deadline

    def start_case(self, case, model):
        plan = self.packet["plan"]
        self.check()
        if case not in plan["case_order"] or model not in plan["models"]:
            raise GraphError("unregistered_case")
        key = case + ":" + model
        if any(c["key"] == key for c in self.state["cases"]):
            raise GraphError("case_already_started")
        row = dict(key=key, case=case, model=model, status="RUNNING", started=self.clock(),
                   deadline=min(self.state["deadline"], self.clock() + plan["deadlines"]["case_seconds"]))
        self.state["cases"].append(row)
        self._save()
        return key, row["deadline"]

    def reserve(self, case_key, prompt_digest, token_upper_bound=None):
        deadline = self.check(case_key)
        p = self.packet["plan"]["parameters"]
        ceiling = p["max_prompt_bytes"] + p["max_output_tokens"] + 4096
        tokens = ceiling if token_upper_bound is None else token_upper_bound
        if type(tokens) is not int or not 1 <= tokens <= ceiling:
            raise GraphError("invalid_reservation_bound")
        micro = (tokens * self.packet["plan"]["budget"]["worst_micro_per_million_tokens"] + 999999) // 1000000
        rows = self.state["attempts"]
        if (len(rows) >= self.state["request_cap"] or sum(r["reserved_micro"] for r in rows) + micro > self.state["money_cap_micro"]):
            raise GraphError("new_budget_exhausted")
        if sum(r["case_key"] == case_key for r in rows) >= p["max_model_steps"]:
            raise GraphError("case_request_limit")
        row = dict(id=22 + len(rows), case_key=case_key, reserved_at=self.clock(), deadline=deadline,
                   reserved_tokens=tokens, reserved_micro=micro, status="RESERVED_USAGE_UNKNOWN",
                   http_status=None, usage=None, finish_reason=None, error=None, prompt_digest=prompt_digest)
        rows.append(row)
        self._save()  # Must succeed before ANY model transport begins.
        self.check(case_key)  # Ledger latency is part of the same deadline.
        return row["id"]

    def record(self, attempt_id, metadata, error=None):
        row = next(r for r in self.state["attempts"] if r["id"] == attempt_id)
        row["observation_epoch"] = self.clock()
        row.update(status="RESPONSE_OBSERVED" if metadata.get("http_status") is not None else "FINISHED_USAGE_UNKNOWN",
                   http_status=metadata.get("http_status"), usage=metadata.get("usage"),
                   finish_reason=metadata.get("finish_reason"), error=error)
        # No refund, including invalid output, HTTP errors, unknown usage/timeout.
        self._save()

    def finish_case(self, key, result):
        row = next(c for c in self.state["cases"] if c["key"] == key)
        row["status"] = result["status"]
        row["result"] = result
        self._save()

    def finish(self, status):
        self.state["status"] = status
        self.state["finished_epoch"] = self.clock()
        self._save()

    @staticmethod
    def _usage(rows):
        known = [r["usage"] for r in rows if r["usage"] is not None]
        unknown = len(rows) - len(known)
        prompt = sum(u["prompt_tokens"] for u in known)
        completion = sum(u["completion_tokens"] for u in known)
        return dict(observed_prompt_tokens=prompt, observed_completion_tokens=completion,
                    unknown_attempts=unknown, total_prompt_tokens=None if unknown else prompt,
                    total_completion_tokens=None if unknown else completion)

    def report(self):
        history = self.state["historical_requests"]
        new = self.state["attempts"]
        results = [c["result"] for c in self.state["cases"] if "result" in c]
        expected = len(self.packet["plan"]["models"]) * len(self.packet["plan"]["case_order"])
        all_passed = self.state["status"] == "COMPLETED_NEW_SERIES" and len(results) == expected and all(r["evaluation"]["all_passed"] for r in results)
        return dict(schema="evidence-refs-series-report-1", new_case_results=len(results),
                    expected_new_case_results=expected, all_new_cases_passed=all_passed,
                    series_started_epoch=self.state.get("started"), series_deadline_epoch=self.state["deadline"],
                    finished_epoch=self.state.get("finished_epoch"), owner_run_id=self.state["run_id"],
                    new_request_cap=self.state["request_cap"], new_money_cap_micro=self.state["money_cap_micro"], source_sha=self.source_sha,
                    manifest_digest=self.packet["manifest_digest"], status=self.state["status"],
                    historical_request_count=len(history), new_request_count=len(new),
                    lifetime_request_count=len(history) + len(new), historical_requests=history,
                    new_attempts=new, cases=self.state["cases"],
                    reserved_new_micro=sum(r["reserved_micro"] for r in new), currency="RUB",
                    historical_usage=self._usage(history), new_usage=self._usage(new), lifetime_usage=self._usage(history + new),
                    historical_unknown_usage_ids=[r["id"] for r in history if r["usage"] is None],
                    new_unknown_usage_ids=[r["id"] for r in new if r["usage"] is None],
                    actual_billed_cost="NOT_MEASURED", historical_results_in_new_score=False)
