"""Fixed-contour Jira read probe. Never prints credentials, task text or exceptions."""
import json
import os
from pathlib import Path
import re
import sys

from agent_service.connectors.jira import BasicAuth
from agent_service.http import HttpClient

BASE = "https://api.atlassian.com/ex/jira/d0b47b8d-4655-4cb1-9f81-30573fd372c3"
PROJECT = "KAN"
PERMISSIONS = ("BROWSE_PROJECTS", "ADD_COMMENTS", "EDIT_OWN_COMMENTS")


def probe(request):
    checks = []

    def read(name, path, verify, metadata, query=None):
        entry = dict(check=name, status="FAIL")
        try:
            response = request("GET", path, query=query)
            entry["http_status"] = response.status
            if response.status != 200:
                raise ValueError("unexpected_status")
            data = response.json()
            if verify(data):
                entry.update(metadata(data), status="PASS")
        except Exception as exc:
            # Provider exception details, URLs and response bodies are never artifacts.
            status = getattr(exc, "status", None)
            if isinstance(status, int) and 100 <= status <= 599:
                entry["http_status"] = status
        checks.append(entry)
        return entry["status"] == "PASS"

    def finish():
        return dict(status="PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL",
                    level="REAL_API_READ_ONLY", api_base=BASE, project=PROJECT, model="OFF", checks=checks,
                    not_proven=["comment write", "webhooks", "complete task enumeration", "intent quality", "VM service"])

    if not read("identity", "/rest/api/3/myself",
                lambda d: d.get("active") is True and bool(re.fullmatch(r"[\w:-]{1,128}", d.get("accountId", ""))),
                lambda d: dict(account_id=d["accountId"], active=True)):
        return finish()
    if not read("project", "/rest/api/3/project/" + PROJECT,
                lambda d: d.get("key") == PROJECT and str(d.get("id", "")).isdigit(),
                lambda d: dict(project_key=PROJECT, project_id=str(d["id"]))):
        return finish()
    if not read("permissions", "/rest/api/3/mypermissions",
                lambda d: all(d.get("permissions", {}).get(p, {}).get("havePermission") is True for p in PERMISSIONS),
                lambda d: dict(permissions={p: True for p in PERMISSIONS}),
                dict(projectKey=PROJECT, permissions=",".join(PERMISSIONS))):
        return finish()
    read("task_sample", "/rest/api/3/search/jql",
         lambda d: isinstance(d.get("issues"), list) and len(d["issues"]) <= 5
         and all(re.fullmatch(r"KAN-[1-9][0-9]*", i.get("key", ""))
                 and str(i.get("id", "")).isdigit() for i in d["issues"]),
         lambda d: dict(tasks=[dict(id=str(i["id"]), key=i["key"]) for i in d["issues"]],
                        sample_page_is_last=d.get("isLast") is True and not d.get("nextPageToken"),
                        complete_listing=False),
         dict(jql="project = KAN ORDER BY key ASC", maxResults=5, fields="key"))
    return finish()


def main():
    output = Path(sys.argv[1])
    email, token = os.environ.get("JIRA_EMAIL"), os.environ.get("JIRA_API_TOKEN")
    if not email or not token:
        report = dict(status="BLOCKED", reason="jira_secrets_missing", model="OFF")
    else:
        client, auth = HttpClient(BASE, timeout=15), BasicAuth(email, token)

        def request(method, path, **kwargs):
            return client.request(method, path, headers={"Authorization": auth()}, **kwargs)

        report = probe(request)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(report["status"])
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
