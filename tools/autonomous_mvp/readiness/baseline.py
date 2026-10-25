"""Baseline for 6-r1: an ordinary agent with search, same sources and rights as the service.

Same sources: the Jira text, the PR title, changed files and diff, the same
Git snapshots (every granted repository at its default branch, the provider at
the PR head on the PR stage), the same installation ownership mapping and the
same access-log windows. Same rights: revoked repositories are not readable.
No graph, no static extractor, no service.

Protocol ``baseline-search-1``: one JSON action per model reply (strict
``json_schema`` response format, as in 2B ``actions-v3``), the tool result goes
back as the next user message. Actions: ``list_repositories``, ``list_files``,
``read_file``, ``search``, ``read_ownership``, ``read_access_logs`` and
``finish`` with the answer. The transport interface is the 2B one:
``complete(payload, *, deadline) -> tools.autonomous_mvp.transport.TransportResult``,
so ``CloudRuTransport`` plugs in for a live run on the same endpoint as the
service's model. Live calls are out of scope of this batch; offline there are
two transports:

- ``ScriptedTransport`` (2B): replays prepared replies, for tests;
- ``NaiveSearchTransport``: a fixed, deterministic policy that greps the route
  named by the task or diff and names every other repository with a hit. It is
  a harness check and a floor, not "the baseline": no model takes part.

Usage: python -m tools.autonomous_mvp.readiness.baseline --split development --transport naive-search
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

from tools.autonomous_mvp.readiness import program as program_mod, world
from tools.autonomous_mvp.transport import TransportResult

PROTOCOL = "baseline-search-1"
LIMITS = dict(max_steps=12, max_invalid=2, max_result_bytes=16000, max_search_hits=60, deadline_seconds=120,
              max_completion_tokens=4096)
SYSTEM_PROMPT = """You assess the impact of a planned or proposed API change in a multi-service installation.
You can read the installation's Git repositories, its ownership mapping and its access logs through actions.
Reply with exactly one JSON object per turn: {"action": <name>, "arguments": {...}}.
Actions: list_repositories {}, list_files {"repository"}, read_file {"repository", "path"},
search {"pattern", "repository" optional} (literal text, case-sensitive), read_ownership {}, read_access_logs {},
finish {"outcome", "impacted"}.
finish.outcome: "answer" when you can name who is affected, "partial" when part of the impact cannot be
established from the sources, "abstain" when the task does not identify the changed operation or nothing
supports an answer. finish.impacted: one item per affected consumer service:
{"service", "severity": "breaking"|"recheck", "path": {"provider", "method", "route", "callsite": "repo:path" or null},
 "owner": {"status": "KNOWN"|"CONFLICT"|"UNKNOWN", "teams": [...]}, "freshness": "CURRENT"|"STALE"|"UNKNOWN"}.
"breaking": the consumer's behaviour changes for the worse; "recheck": it uses the changed operation but is
not known to break. Name only services you found in the sources; do not guess owners."""
ACTION_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["action", "arguments"],
    "properties": {"action": {"type": "string", "enum": ["list_repositories", "list_files", "read_file", "search",
                                                          "read_ownership", "read_access_logs", "finish"]},
                   "arguments": {"type": "object"}}}


def fingerprint():
    text = json.dumps(dict(protocol=PROTOCOL, limits=LIMITS, system=SYSTEM_PROMPT, schema=ACTION_SCHEMA),
                      sort_keys=True, ensure_ascii=False)
    return dict(protocol=PROTOCOL, sha256=hashlib.sha256(text.encode()).hexdigest())


# ---------------------------------------------------------------------------- sources


class Workspace:
    """Read-only view of one stage's sources at pinned commits."""

    def __init__(self, change, stand_root: Path, commits, stage, *, logs_dir: Path | None = None):
        revoked = set(change["grants"]["revoked"])
        self.repos = {n: Path(stand_root) / "repos" / n for n in change["repositories"] if n not in revoked}
        provider = change["pr"]["repository"]
        self.pins = {n: commits[n]["main"] for n in self.repos}
        if stage == "pr":
            self.pins[provider] = commits[provider][change["pr"]["head_branch"]]
        self.ownership = change["ownership"]
        self.logs_dir = logs_dir
        self.reads = 0

    def _git(self, repo, *args):
        out = subprocess.run(["git", "--git-dir", str(self.repos[repo] / ".git"), *args], capture_output=True)
        return out.returncode, out.stdout.decode("utf-8", "replace")

    def call(self, action, arguments):
        self.reads += 1
        repo = arguments.get("repository")
        if repo is not None and repo not in self.repos:
            return dict(error="repository_not_readable")
        if action == "list_repositories":
            return dict(repositories=sorted(self.repos))
        if action == "list_files":
            return dict(files=self._git(repo, "ls-tree", "-r", "--name-only", self.pins[repo])[1].split())
        if action == "read_file":
            code, text = self._git(repo, "show", f"{self.pins[repo]}:{arguments.get('path', '')}")
            return dict(text=text) if code == 0 else dict(error="not_found")
        if action == "search":
            pattern = arguments.get("pattern")
            if not isinstance(pattern, str) or not pattern:
                return dict(error="invalid_pattern")
            hits = []
            for name in sorted([repo] if repo else self.repos):
                code, text = self._git(name, "grep", "-n", "-F", "-e", pattern, self.pins[name])
                for line in text.splitlines():
                    _, path, number, content = line.split(":", 3)
                    hits.append(dict(repository=name, path=path, line=int(number), text=content.strip()[:200]))
            return dict(hits=hits[:LIMITS["max_search_hits"]], truncated=len(hits) > LIMITS["max_search_hits"])
        if action == "read_ownership":
            return dict(mapping=self.ownership)
        if action == "read_access_logs":
            if not self.logs_dir or not self.logs_dir.exists():
                return dict(windows=[])
            windows = []
            for coverage in sorted(self.logs_dir.glob("*.coverage.json")):
                meta = json.loads(coverage.read_text())
                lines = (self.logs_dir / meta["file"]).read_text().splitlines()
                windows.append(dict(start=meta["start"], end=meta["end"], records=[json.loads(x) for x in lines if x]))
            return dict(windows=windows)
        return dict(error="unknown_action")


def git_diff(stand_root, change, commits):
    repo = Path(stand_root) / "repos" / change["pr"]["repository"]
    base, head = (commits[change["pr"]["repository"]][change["pr"][b]] for b in ("base_branch", "head_branch"))
    run = lambda *a: subprocess.run(["git", "--git-dir", str(repo / ".git"), *a], capture_output=True,  # noqa: E731
                                    check=True).stdout.decode("utf-8")
    return run("diff", "--name-only", base, head).split(), run("diff", base, head)


def task_message(change, stage, *, changed_files=None, diff=None):
    jira = change["jira"]
    text = [f"Jira {jira['key']}: {jira['summary']}", jira["description"]]
    if stage == "jira":
        text.append("No code exists yet. Who may be affected by the planned change?")
    else:
        pr = change["pr"]
        text += [f"PR {pr['repository']}#{pr['number']}: {pr['title']}", "Changed files: " + ", ".join(changed_files),
                 "Diff:\n" + diff[:LIMITS["max_result_bytes"]], "Who is affected by this change?"]
    return "\n".join(text)


# ---------------------------------------------------------------------------- protocol loop


def validate_answer(arguments):
    if arguments.get("outcome") not in ("answer", "partial", "abstain"):
        return "invalid_outcome"
    if not isinstance(arguments.get("impacted"), list):
        return "invalid_impacted"
    for item in arguments["impacted"]:
        if not isinstance(item, dict) or not isinstance(item.get("service"), str):
            return "invalid_impacted_item"
    return None


def run_agent(transport, workspace, task, *, model="offline"):
    messages = [dict(role="system", content=SYSTEM_PROMPT), dict(role="user", content=task)]
    deadline = time.monotonic() + LIMITS["deadline_seconds"]
    steps, usage, invalid = [], [], 0
    for step in range(LIMITS["max_steps"]):
        payload = dict(model=model, messages=list(messages), temperature=0, stream=False,
                       max_completion_tokens=LIMITS["max_completion_tokens"],
                       response_format=dict(type="json_schema", json_schema=dict(
                           name="baseline_action", strict=True, schema=ACTION_SCHEMA)))
        result = transport.complete(payload, deadline=deadline)
        usage.append(result.usage)
        if not result.ok:
            steps.append(dict(step=step, valid=False, code=result.code))
            return dict(terminal="transport_error", answer=None, steps=steps, usage=usage)
        try:
            action = json.loads(result.content)
            name, arguments = action["action"], action["arguments"]
            if name not in ACTION_SCHEMA["properties"]["action"]["enum"] or not isinstance(arguments, dict):
                raise ValueError("invalid_action")
        except (ValueError, KeyError, TypeError):
            invalid += 1
            steps.append(dict(step=step, valid=False, code="invalid_action"))
            if invalid > LIMITS["max_invalid"]:
                return dict(terminal="invalid_actions", answer=None, steps=steps, usage=usage)
            messages += [dict(role="assistant", content=result.content or ""),
                         dict(role="user", content='{"error": "invalid_action"}')]
            continue
        if name == "finish":
            problem = validate_answer(arguments)
            steps.append(dict(step=step, valid=problem is None, action=name, code=problem or "ok"))
            if problem is None:
                return dict(terminal="finished", answer=arguments, steps=steps, usage=usage)
            invalid += 1
            if invalid > LIMITS["max_invalid"]:
                return dict(terminal="invalid_actions", answer=None, steps=steps, usage=usage)
            messages += [dict(role="assistant", content=result.content),
                         dict(role="user", content=json.dumps(dict(error=problem)))]
            continue
        observation = json.dumps(dict(action=name, result=workspace.call(name, arguments)), ensure_ascii=False)
        steps.append(dict(step=step, valid=True, action=name, code="ok", bytes=len(observation)))
        messages += [dict(role="assistant", content=result.content),
                     dict(role="user", content=observation[:LIMITS["max_result_bytes"]])]
    return dict(terminal="step_limit", answer=None, steps=steps, usage=usage)


# ---------------------------------------------------------------------------- offline transports


def _reply(action):
    return TransportResult(ok=True, code="ok", http_status=200, finish_reason="stop", usage=None,
                           content=json.dumps(action, ensure_ascii=False))


ROUTE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[A-Za-z0-9_\-./{}]*)")
DECLARED = re.compile(r'^[-+ ]@app\.(get|post|put|patch|delete)\("([^"]+)"\)', re.M)


class NaiveSearchTransport:
    """Deterministic grep policy: route from the task, one search, ownership, finish. Not a model."""

    kind = "scripted"

    def complete(self, payload, *, deadline):
        messages = payload["messages"]
        task = messages[1]["content"]
        observations = [json.loads(m["content"]) for m in messages[2:] if m["role"] == "user"]
        done = {o.get("action"): o.get("result") for o in observations}
        stage = "pr" if "\nDiff:\n" in task else "jira"
        routes = sorted({(m, r.rstrip(".:,")) for m, r in ROUTE.findall(task)})
        if not routes and stage == "pr":  # no route in the task text: take the first decorator the diff shows
            routes = sorted({(m.upper(), r) for m, r in DECLARED.findall(task)})
        if not routes:
            return _reply(dict(action="finish", arguments=dict(outcome="abstain", impacted=[])))
        method, route = routes[0]
        if "search" not in done:
            return _reply(dict(action="search", arguments=dict(pattern=route)))
        if "read_ownership" not in done:
            return _reply(dict(action="read_ownership", arguments={}))
        hits = done["search"]["hits"]
        declarers = sorted({h["repository"] for h in hits if "@app." in h["text"]})
        pr_repo = re.search(r"\nPR ([A-Za-z0-9_.-]+)#", task)
        provider = pr_repo.group(1) if pr_repo else (declarers[0] if declarers else None)
        mapping = done["read_ownership"]["mapping"]["services"]
        impacted = {}
        for h in hits:
            if h["repository"] in declarers or h["repository"] in impacted:
                continue
            teams = mapping.get(h["repository"])
            teams = [teams] if isinstance(teams, str) else list(teams or [])
            impacted[h["repository"]] = dict(
                service=h["repository"], severity="breaking",
                path=dict(provider=provider, method=method, route=route, callsite=f"{h['repository']}:{h['path']}"),
                owner=dict(status="UNKNOWN" if not teams else "KNOWN" if len(teams) == 1 else "CONFLICT", teams=teams),
                freshness="CURRENT")
        outcome = "answer" if impacted else "abstain"
        return _reply(dict(action="finish", arguments=dict(outcome=outcome, impacted=list(impacted.values()))))


TRANSPORTS = {"naive-search": NaiveSearchTransport}


# ---------------------------------------------------------------------------- runner


def run_change(change, work: Path, transport) -> dict:
    from tools.autonomous_mvp.readiness.bench import materialize, write_runtime_logs

    record = dict(change_id=change["change_id"], split=change["split"], family=change["family"])
    started = time.monotonic()
    try:
        commits = materialize(change, work / "stand")
        logs = work / "stand" / "logs"
        write_runtime_logs(change, logs, datetime.now(timezone.utc))
        changed, diff = git_diff(work / "stand", change, commits)
        usage = []
        for stage in ("jira", "pr"):
            workspace = Workspace(change, work / "stand", commits, stage, logs_dir=logs)
            task = task_message(change, stage, changed_files=changed, diff=diff)
            clock = time.monotonic()
            run = run_agent(transport, workspace, task)
            usage += run["usage"]
            record[stage] = dict(answer=run["answer"], terminal=run["terminal"], steps=run["steps"],
                                 latency_seconds=round(time.monotonic() - clock, 3), requests=len(run["usage"]),
                                 usage_known=all(u is not None for u in run["usage"]))
        live = getattr(transport, "kind", "live") == "live"
        known = all(u is not None for u in usage)
        # A scripted transport is not a model: no model calls and no money. Live usage stays unknown
        # (None) when the provider does not report it; the rouble price is applied by the reporting step.
        record["costs"] = dict(model_calls=len(usage) if live else 0, transport_requests=len(usage),
                               prompt_tokens=sum(u["prompt_tokens"] for u in usage) if known else None,
                               completion_tokens=sum(u["completion_tokens"] for u in usage) if known else None,
                               rub=None if live else 0.0)
        record["error"] = None
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["traceback"] = traceback.format_exc()[-4000:]
    record["wall_seconds"] = round(time.monotonic() - started, 3)
    record["human"] = dict(interventions=0, active_minutes=None, status="NOT_RECORDED")
    return record


def run_split(split, transport_name, *, out=None, base=None):
    from tools.autonomous_mvp.readiness import runner

    transport = TRANSPORTS[transport_name]()
    configuration = f"baseline-{transport_name}"
    current, digest = program_mod.status(base)
    path = Path(out) if out else runner.ledger_path(split, configuration, base=base)
    runner.guard(split, path, manifest_current=current)
    ledger = dict(schema="readiness-ledger-1", program=world.PROGRAM, split=split, configuration=configuration,
                  transport_kind=getattr(transport, "kind", "live"), protocol=fingerprint(),
                  manifest_digest=digest, manifest_current=current, source_sha=runner.source_sha(),
                  python=sys.version.split()[0], started_at=datetime.now(timezone.utc).isoformat(), records=[])
    root = Path(tempfile.mkdtemp(prefix="readiness-6-baseline-"))
    try:
        for change in runner.load_changes(split, base):
            ledger["records"].append(run_change(change, root / change["change_id"], transport))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    ledger["finished_at"] = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(ledger, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode())
    return ledger, path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--split", choices=world.SPLITS, required=True)
    parser.add_argument("--transport", choices=sorted(TRANSPORTS), required=True)
    parser.add_argument("--out")
    args = parser.parse_args()
    ledger, path = run_split(args.split, args.transport, out=args.out)
    print(f"LEDGER {path} records={len(ledger['records'])} errors="
          f"{sum(1 for r in ledger['records'] if r['error'])}")


if __name__ == "__main__":
    main()
