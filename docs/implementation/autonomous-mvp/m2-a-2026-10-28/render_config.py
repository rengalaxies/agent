"""Materialize known non-secret IDs; refuse missing values. No network or installation.

python <this-file> --inputs inputs.json --output work/box.yaml
Input/output contain identifiers only. Do not put secrets in either file.
"""
import argparse
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[3]))
from tools.agent_service.box.config import BoxConfig  # noqa: E402


def render(inputs):
    required = ("github_app_id", "github_installation_id", "github_bot_login", "jira_api_base_url",
                "jira_project_key", "jira_bot_account_id")
    missing = [name for name in required if not inputs.get(name)]
    if missing:
        raise ValueError("missing_non_secret_identifiers:" + ",".join(missing))
    if not str(inputs["github_app_id"]).isdigit() or type(inputs["github_installation_id"]) is not int \
            or inputs["github_installation_id"] <= 0:
        raise ValueError("invalid_github_identifiers")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,9}", inputs["jira_project_key"]):
        raise ValueError("invalid_jira_project_key")
    if not re.fullmatch(r"[a-z0-9-]+\[bot\]", inputs["github_bot_login"]):
        raise ValueError("invalid_github_bot_login")
    jira = urlsplit(inputs["jira_api_base_url"])
    site = re.fullmatch(r"[a-z0-9-]+\.atlassian\.net", jira.hostname or "")
    gateway = jira.hostname == "api.atlassian.com" and re.fullmatch(r"/ex/jira/[a-zA-Z0-9-]+", jira.path)
    if jira.scheme != "https" or jira.username or jira.password or jira.query or jira.fragment \
            or jira.port not in (None, 443) or not (site and jira.path in ("", "/") or gateway):
        raise ValueError("invalid_jira_cloud_api_base")
    config = yaml.safe_load((ROOT / "box.partial.yaml").read_text())
    config["github"]["bot_login"] = inputs["github_bot_login"]
    config["github"]["auth"].update(app_id=str(inputs["github_app_id"]),
                                    installation_id=inputs["github_installation_id"])
    config["jira"].update(base_url=inputs["jira_api_base_url"].rstrip("/"),
                          project_keys=[inputs["jira_project_key"]], bot_account_id=inputs["jira_bot_account_id"])
    # The real production schema is exercised; this does not prove API access.
    BoxConfig.model_validate(config)
    return config


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = render(json.loads(args.inputs.read_text()))
    except ValueError as exc:
        sys.exit(str(exc))
    with args.output.open("x") as out:
        yaml.safe_dump(result, out, sort_keys=False)
    print("SCHEMA_VALIDATED; APIs, credentials, endpoint and installation NOT_VERIFIED")
