"""Durable accounting for one (program revision, phase, model). No reset, no rerun.

The ledger is one JSON document. Every write is a compare-and-swap on the previous
version: a lost or concurrent write stops the runner instead of forking history.

Money is reserved per case before its first request, at the worst case of every
allowed request. When the case ends, attempts with known usage settle at the
published rates; unknown usage stays at the worst case. A crash therefore never
under-counts. Attempt details are written with the case result, so a process
killed mid-case keeps its reservation but loses that case's attempt rows.
"""
from __future__ import annotations

import base64
import copy
from decimal import ROUND_CEILING, Decimal
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

SECRET_ENVS = ("CLOUDRU_FOUNDATION_API_KEY", "GH_TOKEN", "GITHUB_TOKEN")


class LedgerError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def micro_cost(prompt_tokens, completion_tokens, price):
    """Ceil of RUB cost in micro-RUB. A price per million tokens equals micro-RUB per token."""
    total = Decimal(prompt_tokens) * Decimal(price["input_per_million"]) + \
        Decimal(completion_tokens) * Decimal(price["output_per_million"])
    return int(total.to_integral_value(rounding=ROUND_CEILING))


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class FileBackend:
    """Local CAS backend for offline tests and dry runs."""

    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        if not self.path.exists():
            return None, None
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return data["version"], data["state"]

    def write(self, expected_version, state):
        current, _ = self.read()
        if current != expected_version:
            raise LedgerError("ledger_write_conflict")
        version = (current or 0) + 1
        tmp = self.path.with_suffix(".tmp")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(canonical(dict(version=version, state=state)), encoding="utf-8")
        os.replace(tmp, self.path)
        return version


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHubContentsBackend:
    """One file on a dedicated accounting branch; the blob SHA is the CAS version.

    Two API calls per case keep a full evaluation well inside the GITHUB_TOKEN
    rate limit. Only the first write creates the branch (orphan commit).
    """

    def __init__(self, repository, token, branch, path):
        if (not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not token
                or not re.fullmatch(r"experiment-state/autonomous-mvp/[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*", branch)
                or not re.fullmatch(r"[A-Za-z0-9_.-]+\.json", path)):
            raise LedgerError("invalid_ledger_configuration")
        self.repository, self._token, self.branch, self.path = repository, token, branch, path

    def _api(self, method, path, body=None, *, missing=False):
        request = urllib.request.Request(
            "https://api.github.com/repos/" + self.repository + path, method=method,
            data=None if body is None else canonical(body).encode(),
            headers={"Authorization": "Bearer " + self._token, "Accept": "application/vnd.github+json",
                     "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28"})
        try:
            with urllib.request.build_opener(_NoRedirect).open(request, timeout=20) as response:
                raw = response.read(8_000_001)
                if len(raw) > 8_000_000:
                    raise LedgerError("ledger_response_limit")
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and missing:
                return None
            raise LedgerError("ledger_write_conflict" if exc.code in (409, 422) else "ledger_http_error") from None
        except (OSError, ValueError, urllib.error.URLError):
            raise LedgerError("ledger_unavailable") from None

    def read(self):
        data = self._api("GET", f"/contents/{self.path}?ref={self.branch}", missing=True)
        if data is None:
            return None, None
        try:
            return data["sha"], json.loads(base64.b64decode(data["content"]))
        except (KeyError, ValueError, TypeError):
            raise LedgerError("invalid_ledger") from None

    def write(self, expected_version, state):
        content = canonical(state)
        if expected_version is None:
            if self._api("GET", "/git/ref/heads/" + self.branch, missing=True) is not None:
                raise LedgerError("ledger_write_conflict")
            blob = self._api("POST", "/git/blobs", dict(content=content, encoding="utf-8"))
            tree = self._api("POST", "/git/trees", dict(tree=[dict(path=self.path, mode="100644", type="blob",
                                                                  sha=blob["sha"])]))
            commit = self._api("POST", "/git/commits", dict(message="Open autonomous MVP ledger",
                                                             tree=tree["sha"], parents=[]))
            self._api("POST", "/git/refs", dict(ref="refs/heads/" + self.branch, sha=commit["sha"]))
            return blob["sha"]
        result = self._api("PUT", "/contents/" + self.path, dict(
            message="Record autonomous MVP accounting", branch=self.branch, sha=expected_version,
            content=base64.b64encode(content.encode()).decode()))
        return result["content"]["sha"]


class Ledger:
    def __init__(self, backend, identity, *, clock=time.time):
        """identity: run_id, phase, model, manifest_digest, source_sha, caps and prices."""
        self.backend, self.identity, self.clock = backend, identity, clock
        self.version, self.state = backend.read()
        if self.state is not None and any(self.state.get(k) != identity[k] for k in (
                "run_id", "phase", "model", "manifest_digest", "source_sha")):
            raise LedgerError("ledger_identity_mismatch")

    def _save(self):
        data = canonical(self.state)
        for name in SECRET_ENVS:
            secret = os.environ.get(name)
            if secret and len(secret) >= 8 and secret in data:
                raise LedgerError("ledger_secret_detected")
        self.version = self.backend.write(self.version, copy.deepcopy(self.state))

    def claim(self, actions_run, *, started_epoch):
        """Open the phase exactly once. A second process or an Actions rerun is refused."""
        if self.state is not None:
            raise LedgerError("phase_already_started_no_rerun")
        now = self.clock()
        if started_epoch > now + 1:
            raise LedgerError("invalid_phase_clock")
        i = self.identity
        self.state = dict(schema="amvp-ledger-1", **{k: i[k] for k in (
            "run_id", "phase", "model", "manifest_digest", "source_sha", "request_cap", "money_cap_micro",
            "worst_micro_per_request", "price")}, status="RUNNING", actions_run=actions_run,
            started_epoch=started_epoch, deadline_epoch=started_epoch + i["phase_seconds"],
            last_seen=now, case_runs=[])
        self._save()

    def check(self):
        now = self.clock()
        if self.state is None or self.state["status"] != "RUNNING":
            raise LedgerError("phase_not_running")
        if now < self.state["last_seen"]:
            self.finish("STOPPED_CLOCK")
            raise LedgerError("clock_moved_backwards")
        self.state["last_seen"] = now
        if now >= self.state["deadline_epoch"]:
            self.finish("STOPPED_PHASE_DEADLINE")
            raise LedgerError("phase_deadline")
        return self.state["deadline_epoch"]

    def committed(self):
        rows = self.state["case_runs"]
        money = sum(r["settled_micro"] if r["status"] != "RESERVED" else r["reserved_micro"] for r in rows)
        requests = sum(len(r["attempts"]) if r["status"] != "RESERVED" else r["max_requests"] for r in rows)
        return requests, money

    def start_case(self, case_id, repeat, max_requests):
        self.check()
        key = f"{case_id}#{repeat}"
        if any(r["key"] == key for r in self.state["case_runs"]):
            raise LedgerError("case_already_started")
        reserve = max_requests * self.state["worst_micro_per_request"]
        requests, money = self.committed()
        if requests + max_requests > self.state["request_cap"]:
            raise LedgerError("request_cap_reached")
        if money + reserve > self.state["money_cap_micro"]:
            raise LedgerError("money_cap_reached")
        self.state["case_runs"].append(dict(key=key, case_id=case_id, repeat=repeat, status="RESERVED",
                                            max_requests=max_requests, reserved_micro=reserve, settled_micro=None,
                                            started_epoch=self.clock(), attempts=[], result=None))
        self._save()
        return key

    def settle(self, attempts):
        worst = self.state["worst_micro_per_request"]
        total = 0
        for a in attempts:
            u = a.get("usage")
            a["cost_micro"] = micro_cost(u["prompt_tokens"], u["completion_tokens"], self.state["price"]) if u else None
            total += a["cost_micro"] if a["cost_micro"] is not None else worst
        return total

    def finish_case(self, key, attempts, result):
        row = next(r for r in self.state["case_runs"] if r["key"] == key)
        if row["status"] != "RESERVED":
            raise LedgerError("case_already_finished")
        if len(attempts) > row["max_requests"]:
            raise LedgerError("case_request_overrun")
        row.update(status="FINISHED", attempts=attempts, settled_micro=self.settle(attempts),
                   finished_epoch=self.clock(), result=result)
        self._save()

    def finish(self, status):
        if self.state["status"] == "RUNNING":
            self.state["status"] = status
            self.state["finished_epoch"] = self.clock()
            self._save()
