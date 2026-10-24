"""Check the oracle against the fixtures by executing them, independent of any model.

For each case the trusted fixture code (written by the corpus author, never by a
model) runs in an isolated interpreter with recording `requests`/`httpx` fakes.
The fake Orders provider pages 50 orders with the default page size before (100)
and after (20) the change. Observed calls give the true directed edges; the
fixture's own requirement tests give the impact. The static extractor is not
consulted here, so beyond-AST cases are grounded too.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

from tools.autonomous_mvp import fixtures

ROOT = Path(__file__).resolve().parents[2]
TOTAL = 50

HARNESS = r'''
import importlib, json, sys, types, unittest, runpy
from urllib.parse import urlsplit

spec = json.loads(sys.argv[1])
TOTAL, PAGE = spec["total"], spec["default_page_size"]
calls = []


class Response:
    def __init__(self, data):
        self._data = data
        self.status_code = 200

    def json(self):
        return self._data

    def raise_for_status(self):
        return None


def serve(method, url, params=None):
    params = dict(params or {})
    u = urlsplit(url)
    calls.append(dict(method=method.upper(), scheme=u.scheme, host=u.hostname, port=u.port, path=u.path,
                      param_keys=sorted(k for k, v in params.items() if v is not None)))
    if method.upper() == "GET" and u.path.endswith("/orders"):
        size = int(params.get("page_size") or PAGE)
        start = int(params.get("cursor") or 0)
        items = [dict(id=i) for i in range(start, min(TOTAL, start + size))]
        nxt = start + size if start + size < TOTAL else None
        return Response(dict(items=items, next_cursor=None if nxt is None else str(nxt)))
    return Response(dict(ok=True))


requests = types.ModuleType("requests")
requests.get = lambda url, params=None, **kw: serve("GET", url, params)
requests.post = lambda url, json=None, **kw: serve("POST", url)


class Session:
    def get(self, url, params=None, **kw):
        return serve("GET", url, params)

    def post(self, url, json=None, **kw):
        return serve("POST", url)


requests.Session = Session
httpx = types.ModuleType("httpx")


class Client:
    def __init__(self, base_url="", **kw):
        self.base_url = base_url

    def get(self, path, params=None, **kw):
        return serve("GET", self.base_url + path, params)


httpx.Client = Client
fastapi = types.ModuleType("fastapi")
sys.modules.update(requests=requests, httpx=httpx, fastapi=fastapi)
sys.path.insert(0, spec["root"])
out = {}
if spec["kind"] == "entrypoint":
    fn = getattr(importlib.import_module(spec["module"]), spec["function"])
    result = fn(*spec["args"])
    out = dict(calls=calls, items=len(result) if isinstance(result, list) else None)
else:
    module = runpy.run_path(spec["path"])
    suite = unittest.TestSuite()
    for value in module.values():
        if isinstance(value, type) and issubclass(value, unittest.TestCase):
            suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(value))
    result = unittest.TextTestRunner(stream=open(__import__("os").devnull, "w"), verbosity=0).run(suite)
    out = dict(tests=result.testsRun, status="PASS" if result.wasSuccessful() and result.testsRun else "FAIL")
print(json.dumps(out))
'''


def _run(harness, spec):
    result = subprocess.run([sys.executable, "-I", str(harness), json.dumps(spec)], capture_output=True,
                            text=True, timeout=60, cwd=str(harness.parent))
    if result.returncode != 0:
        raise fixtures.FixtureError("fixture_execution_failed")
    return json.loads(result.stdout.strip().splitlines()[-1])


def _service(addresses, call):
    for a in addresses:
        base = urlsplit(a["base_url"])
        if (call["scheme"], call["host"], call["port"]) == (base.scheme, base.hostname, base.port) and (
                not base.path or call["path"].startswith(base.path + "/")):
            return a["service"], call["path"][len(base.path):] or "/"
    return None, call["path"]


def _key(c):
    return (c["consumer_repository"], c["consumer_service"], c["provider_service"], c["method"], c["path_template"])


def check_case(case, oracle, work):
    """Return a list of mismatch codes; empty means the oracle matches the fixture."""
    work = Path(work)
    everything = dict(case, repositories=[dict(r, availability="available") for r in case["repositories"]])
    repos = fixtures.materialize(everything, work / "repos")
    harness = work / "harness" / "run.py"
    harness.parent.mkdir()
    harness.write_text(HARNESS, encoding="utf-8")
    problems, observed, counts = [], set(), {}
    for e in oracle["grounding"]["entrypoints"]:
        for page in (100, 20):
            out = _run(harness, dict(kind="entrypoint", root=repos[e["repository"]]["root"], module=e["module"],
                                     function=e["function"], args=e["args"], total=TOTAL, default_page_size=page))
            counts[(e["repository"], page)] = out["items"]
            for call in out["calls"]:
                service, path = _service(case["addresses"], call)
                if service is not None:
                    observed.add((e["repository"], e["repository"], service, call["method"], path))
    # Unverifiable claims are true in the fixture but unreadable during the run.
    for c in oracle["required_claims"] + oracle["allowed_claims"] + oracle["unverifiable_claims"]:
        if _key(c) not in observed:
            problems.append("claim_not_observed:" + ":".join(_key(c)))
    for c in oracle["forbidden_claims"]:
        if _key(c) in observed:
            problems.append("forbidden_claim_observed:" + ":".join(_key(c)))
    tests = {}
    for t in oracle["grounding"]["requirement_tests"]:
        path = Path(repos[t["repository"]]["root"]) / t["path"]
        statuses = {}
        for label, page in (("before", 100), ("after", 20)):
            statuses[label] = _run(harness, dict(kind="test", root=repos[t["repository"]]["root"], path=str(path),
                                                 total=TOTAL, default_page_size=page))["status"]
        tests[t["repository"]] = statuses
        if (statuses["before"], statuses["after"]) != (t["before"], t["after"]):
            problems.append("requirement_test_mismatch:" + t["repository"])
    # Owners follow the operator mapping: one team KNOWN, several CONFLICT, none UNKNOWN.
    mapping = (case.get("ownership") or {}).get("services", {})
    for service, status in oracle["owners"].items():
        teams = mapping.get(service)
        expected = "UNKNOWN" if not teams else "KNOWN" if isinstance(teams, str) or len(teams) == 1 else "CONFLICT"
        if status != expected:
            problems.append("owner_not_grounded:" + service)
    revoked = {r["id"] for r in case["repositories"] if r.get("scope") == "revoked"}
    if set(oracle["revoked_services"]) != revoked:
        problems.append("revoked_scope_mismatch")
    consequence = oracle["grounding"].get("known_consequence")
    for service, verdict in oracle["impact"].items():
        after = counts.get((service, 20))
        evidence = tests.get(service)
        if verdict == "AT_RISK":
            ok = after is not None and after < TOTAL and (
                (evidence and evidence["after"] == "FAIL") or (consequence and consequence["service"] == service))
        elif verdict == "NOT_AT_RISK":
            ok = after == TOTAL and evidence is not None and evidence == dict(before="PASS", after="PASS")
        else:
            # No requirement and no known consequence: whatever the counts, breakage is not established.
            ok = verdict == "UNKNOWN" and evidence is None and not (consequence and consequence["service"] == service)
        if not ok:
            problems.append("impact_not_grounded:" + service)
    return problems


def load_program(program):
    cases = {}
    for path in sorted((program / "cases").glob("*/*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        cases[case["case_id"]] = case
    oracle = {}
    for split in ("transport", "development", "evaluation"):
        oracle.update(json.loads((program / "oracle" / f"{split}.json").read_text(encoding="utf-8"))["cases"])
    return cases, oracle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, default=ROOT / "experiments/autonomous_mvp/programs/2b-r1")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    cases, oracle = load_program(args.program)
    if set(cases) != set(oracle):
        raise SystemExit("ORACLE_CASE_SET_MISMATCH")
    report = {}
    for case_id in sorted(cases):
        with tempfile.TemporaryDirectory(prefix="amvp-oracle-") as work:
            report[case_id] = check_case(cases[case_id], oracle[case_id], work)
    failed = {k: v for k, v in report.items() if v}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(dict(cases=len(report), failed=failed), indent=2) + "\n")
    print(f"ORACLE_CHECK cases={len(report)} failed={len(failed)}")
    for k, v in failed.items():
        print(k, " ".join(v))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
