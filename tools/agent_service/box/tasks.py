"""Work on service data, run by the box as the service user inside the release venv.

    <release>/venv/bin/python -I -B <release>/app/tools/agent_service/box/tasks.py <task> --config service.json

Each task prints one ASCII JSON document. Secret values come from the
environment the box passes (read from secrets.env) and never appear in the
output: errors are reason codes and the names of the variables involved.

Tasks: mirrors (clone/fetch Git mirrors), graph (initial or refreshed graph at
the default branches), probes (read access to GitHub and Jira), readiness
(graph, queue and model state without writing), smoke (the offline
end-to-end smoke of the installed release).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

RELEASE = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(RELEASE / "app" / "src"), str(RELEASE / "app")]


def _service(service_config: Path):
    from agent_service.__main__ import _analyzer
    from agent_service.config import ServiceConfig, build
    from agent_service.service import Service

    config = ServiceConfig.load(service_config)
    store, connectors, backends = build(config)
    service = Service(store=store, connectors=connectors, backends=backends, analyzer=_analyzer(None, config),
                      installation_id=config.installation_id, environment=config.environment,
                      analysis_settings=config.analysis)
    return service, config


def _safe(exc: Exception) -> dict:
    code = getattr(exc, "code", None)
    if code:
        return {"code": code, "http_status": getattr(exc, "status", None)}
    text = str(exc)
    if text.startswith("missing_secret_env:"):
        return {"code": "secret_missing", "secret": text.split(":", 1)[1]}
    return {"code": type(exc).__name__}


def task_mirrors(args) -> dict:
    from tools.agent_service.box import config as box_config
    from tools.agent_service.box.mirrors import sync

    config = box_config.load(args.box_config)
    results = sync(config, Path(args.mirrors), dict(os.environ))
    return {"ok": all(r["status"] == "OK" for r in results), "repositories": results}


def _graph_view(service) -> dict:
    query = service.analyzer.query()
    summary = query.summary()
    freshness = query.source_freshness()
    model = service.analyzer.model_status()
    return {"summary": summary, "sources": freshness,
            "model": {"ok": model.ok, "reason_code": model.reason_code}}


def task_graph(args) -> dict:
    service, _ = _service(args.config)
    started = time.monotonic()
    try:
        results = service.reconcile_graph()
    except Exception as exc:
        return {"ok": False, "error": _safe(exc)}
    view = _graph_view(service)
    failed = [r for r in results or [] if r.get("error") or r.get("status") == "UNAVAILABLE"]
    code = [s for s in view["sources"] if s["source_kind"] == "git"]
    ok = results is not None and not failed and bool(code) and view["summary"]["relationships"] > 0
    return {"ok": ok, "seconds": round(time.monotonic() - started, 2), "sources_reconciled": results,
            "failed_sources": [r["source"] for r in failed], **view}


def task_probes(args) -> dict:
    """Read-only calls with the configured credentials; publication rights are checked on first publish.

    Runs before the pre-update backup, so it must not open (and possibly migrate) the service state.
    """
    from agent_service.config import ServiceConfig, build_connectors

    config = ServiceConfig.load(args.config)
    try:
        connectors, _ = build_connectors(config)
    except Exception as exc:
        return {"ok": False, "checks": [{"source": "configuration", "ok": False, **_safe(exc)}]}
    checks = []
    if "github" in connectors:
        gh = connectors["github"]
        for repo, branch in sorted(config.github.read_repositories.items()):
            try:
                gh.resolve_branch(repo, branch)
                checks.append({"source": f"github:{repo}", "check": "read_branch", "ok": True})
            except Exception as exc:
                checks.append({"source": f"github:{repo}", "check": "read_branch", "ok": False, **_safe(exc)})
        try:
            gh.reconcile_candidates(None)
            checks.append({"source": "github", "check": "list_pull_requests", "ok": True})
        except Exception as exc:
            checks.append({"source": "github", "check": "list_pull_requests", "ok": False, **_safe(exc)})
    if "jira" in connectors:
        try:
            connectors["jira"].reconcile_candidates(time.time() - 3600)
            checks.append({"source": "jira", "check": "search_issues", "ok": True})
        except Exception as exc:
            checks.append({"source": "jira", "check": "search_issues", "ok": False, **_safe(exc)})
    return {"ok": all(c["ok"] for c in checks), "checks": checks,
            "not_checked": ["publication rights (a write; checked on the first comment, see notices)"]}


def task_readiness(args) -> dict:
    from agent_service.config import ServiceConfig
    from agent_service.queue import ServiceStore

    config = ServiceConfig.load(args.config)
    out = {}
    if not Path(config.state_path).is_file():  # never create an empty queue just to report on it
        return {"queue_error": {"code": "state_missing"}, "graph_error": {"code": "state_missing"}}
    try:
        out["queue"] = ServiceStore(config.state_path).status()
    except Exception as exc:
        out["queue_error"] = _safe(exc)
    try:
        from agent_service.config import core_analyzer

        analyzer = core_analyzer(config.core, code_version=config.analysis.get("code_version", "agent-service"))
        query = analyzer.query()
        model = analyzer.model_status()
        out.update(graph=query.summary(), sources=query.source_freshness(),
                   model={"ok": model.ok, "reason_code": model.reason_code})
        analyzer.close()
    except Exception as exc:
        out["graph_error"] = _safe(exc)
    return out


def task_smoke(args) -> dict:
    from agent_service.smoke import run_smoke

    root = Path(tempfile.mkdtemp(prefix="smoke-", dir=args.tmp))
    try:
        report = run_smoke(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", choices=["mirrors", "graph", "probes", "readiness", "smoke"])
    parser.add_argument("--config", type=Path, help="generated service.json")
    parser.add_argument("--box-config", type=Path, help="box.yaml (mirrors)")
    parser.add_argument("--mirrors", help="mirror directory (mirrors)")
    parser.add_argument("--tmp", help="scratch directory (smoke)")
    args = parser.parse_args(argv)
    result = globals()[f"task_{args.task}"](args)
    sys.stdout.write(json.dumps(result, ensure_ascii=True, sort_keys=True, default=str) + "\n")
    return 0 if result.get("ok", True) else 3


if __name__ == "__main__":
    raise SystemExit(main())
