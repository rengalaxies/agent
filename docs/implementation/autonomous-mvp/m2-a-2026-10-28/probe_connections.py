"""Read-only App/Jira identity probes, with credentials already delivered outside Git.

Needs rendered box.yaml and the normal secret environment/PEM. Writes selected
metadata only; no secret values, raw response bodies or exception details.
No service DB is opened. No comments, webhook registration or model calls.
POST installation-token exchange is authentication, not a test publication.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from agent_service.config import ServiceConfig, build_connectors  # noqa: E402
from agent_service.http import segment  # noqa: E402
from tools.agent_service.box.config import load  # noqa: E402


def probe(path):
    config = load(path)
    if config.github.auth.kind != "app":
        raise ValueError("app_required")
    service = ServiceConfig.model_validate(config.service(state=Path("/unused"), policy_path=Path("/unused"),
        constitution=Path("/unused"), release_id="identity-probe"))
    connectors, _ = build_connectors(service)
    gh, jira = connectors["github"], connectors.get("jira")
    records = []

    def finish():
        if gh.auth._token:
            get("revoke_installation_token", lambda: gh._call("DELETE", "/installation/token"),
                lambda d: {}, lambda d: True)
        return {"level": "REAL_API_READ_ONLY", "auth": "dedicated GitHub App installation"
                    + (" + Jira Basic API token" if jira else " (Jira NOT_RUN)"),
                "scope": "github_and_jira" if jira else "github_only",
                "at": datetime.now(timezone.utc).isoformat(), "checks": records,
                "status": "PASS" if all(r["status"] == "PASS" for r in records) else "FAIL",
                "not_proven": ["webhook signature/delivery", "publication rights by actual write", "installed M3", "LIVE M2"]}


    def get(name, call, summarize, verify):
        try:
            response = call()
            data = response.json() if response.body else {}
            record = {"check": name, "status": "PASS" if verify(data) else "FAIL",
                      "http_status": response.status, "metadata": summarize(data),
                      "request_id": next((response.headers[k] for k in
                          ("x-github-request-id", "x-arequestid", "atl-traceid") if k in response.headers), None)}
        except Exception as exc:
            record = {"check": name, "status": "FAIL", "error_type": type(exc).__name__,
                      "http_status": getattr(exc, "status", None), "code": getattr(exc, "code", None)}
        records.append(record)
        return record["status"] == "PASS"

    def app_get(path):
        return gh.client.request("GET", path, headers={"Authorization": "Bearer " + gh.auth._jwt(),
            "X-GitHub-Api-Version": "2022-11-28"}, accept="application/vnd.github+json")

    expected = {"metadata": "read", "contents": "read", "pull_requests": "read", "issues": "write"}
    app_ok = get("app_identity", lambda: app_get("/app"),
        lambda d: {k: d.get(k) for k in ("id", "slug", "permissions", "events")},
        lambda d: str(d.get("id")) == config.github.auth.app_id
            and d.get("slug", "") + "[bot]" == config.github.bot_login and d.get("permissions") == expected)
    if not app_ok:
        return finish()
    installation_ok = get("installation_identity", lambda: app_get(f"/app/installations/{config.github.auth.installation_id}"),
        lambda d: {"id": d.get("id"), "app_id": d.get("app_id"), "account": d.get("account", {}).get("login"),
                   "permissions": d.get("permissions"), "repository_selection": d.get("repository_selection")},
        lambda d: str(d.get("id")) == str(config.github.auth.installation_id)
            and str(d.get("app_id")) == config.github.auth.app_id
            and d.get("account", {}).get("login") == "rengalaxies" and d.get("permissions") == expected
            and d.get("repository_selection") == "selected" and not d.get("suspended_at"))
    if not installation_ok:
        return finish()
    names = {r.name for r in config.github.repositories}
    repositories_ok = get("installation_repositories", lambda: gh._call("GET", "/installation/repositories", query={"per_page": 100}),
        lambda d: {"total_count": d.get("total_count"), "repositories": [
            {k: r.get(k) for k in ("id", "full_name", "private")} for r in d.get("repositories", [])]},
        lambda d: d.get("total_count") == 2 and {r["full_name"] for r in d.get("repositories", [])} == names
            and all(r.get("private") for r in d.get("repositories", [])))
    if not repositories_ok:
        return finish()
    get("bot_identity", lambda: gh._call("GET", "/users/" + segment(config.github.bot_login)),
        lambda d: {k: d.get(k) for k in ("id", "login", "type")},
        lambda d: d.get("login") == config.github.bot_login and d.get("type") == "Bot")
    for repo in config.github.repositories:
        get("read_branch:" + repo.name,
            lambda r=repo: gh._call("GET", gh._repo(r.name) + "/branches/" + segment(r.branch)),
            lambda d: {"branch": d.get("name"), "sha": d.get("commit", {}).get("sha")},
            lambda d: bool(d.get("commit", {}).get("sha")))
        get("read_pull_requests:" + repo.name,
            lambda r=repo: gh._call("GET", gh._repo(r.name) + "/pulls", query={"state": "all", "per_page": 100}),
            lambda d: {"count": len(d), "pull_requests": [
                {"number": p.get("number"), "state": p.get("state"),
                 "base": p.get("base", {}).get("sha"), "head": p.get("head", {}).get("sha")} for p in d]},
            lambda d: isinstance(d, list))
    if jira:
        get("jira_identity", lambda: jira._call("GET", "/rest/api/3/myself"),
            lambda d: {k: d.get(k) for k in ("accountId", "active")},
            lambda d: d.get("accountId") == config.jira.bot_account_id and d.get("active") is True)
    for project in config.jira.project_keys if config.jira else []:
        get("jira_project:" + project, lambda p=project: jira._call("GET", "/rest/api/3/project/" + segment(p)),
            lambda d: {k: d.get(k) for k in ("id", "key")}, lambda d, p=project: d.get("key") == p)
        permissions = ["BROWSE_PROJECTS", "ADD_COMMENTS", "EDIT_OWN_COMMENTS"]
        get("jira_permissions:" + project, lambda p=project: jira._call("GET", "/rest/api/3/mypermissions",
            query={"projectKey": p, "permissions": ",".join(permissions)}),
            lambda d: {k: d.get("permissions", {}).get(k, {}).get("havePermission") for k in permissions},
            lambda d: all(d.get("permissions", {}).get(k, {}).get("havePermission") is True for k in permissions))
    return finish()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--box-config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = probe(args.box_config)
    except Exception as exc:
        report = {"status": "BLOCKED", "error_type": type(exc).__name__, "code": getattr(exc, "code", None)}
    with args.output.open("x") as output:
        json.dump(report, output, indent=2)
        output.write("\n")
    print(report["status"])
    sys.exit(0 if report["status"] == "PASS" else 1)
