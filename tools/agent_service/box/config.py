"""The one file the owner fills in (``/etc/agent-service/box.yaml``) and what the box derives from it.

Secret values never appear here: the file names environment variables that
``/etc/agent-service/secrets.env`` defines. The box generates the service's
internal configuration (``service.json``, ``policy.json``) from this file;
nobody edits those by hand.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

ENV_NAME = r"^[A-Z][A-Z0-9_]{0,80}$"
NAME = r"^[a-zA-Z0-9_.-]{1,64}$"
STATUS_TOKEN_ENV = "AGENT_SERVICE_STATUS_TOKEN"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Listen(Strict):
    host: str = "127.0.0.1"
    port: int = Field(default=8090, ge=1024, le=65535)


class Repository(Strict):
    name: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")  # owner/repo on the Git host
    service: str = Field(pattern=NAME)  # service id in the graph
    id: str | None = Field(default=None, pattern=NAME)  # repository id in the graph; default: repo part of name
    branch: str = Field(default="main", pattern=r"^[A-Za-z0-9_./-]{1,200}$")
    watch_prs: bool = False  # analyze this repository's pull requests
    clone_url: str | None = None  # default https://github.com/<name>.git; local paths only for test stands
    include: list[str] | None = None

    @property
    def graph_id(self) -> str:
        return self.id or self.name.split("/", 1)[1]


class GitHubAuth(Strict):
    kind: Literal["app", "token"]
    app_id: str | None = None
    installation_id: int | None = None
    private_key_path_env: str = Field(default="GITHUB_APP_PRIVATE_KEY_PATH", pattern=ENV_NAME)
    token_env: str = Field(default="GITHUB_TOKEN", pattern=ENV_NAME)

    @model_validator(mode="after")
    def complete(self):
        if self.kind == "app" and (not self.app_id or not self.installation_id):
            raise ValueError("github app auth needs app_id and installation_id")
        return self


class GitHub(Strict):
    api_base: str = "https://api.github.com"
    web_base: str = "https://github.com"
    repositories: list[Repository] = Field(min_length=1, max_length=32)
    bot_login: str = Field(min_length=1, max_length=100)
    webhook_secret_env: str = Field(default="GITHUB_WEBHOOK_SECRET", pattern=ENV_NAME)
    auth: GitHubAuth

    @model_validator(mode="after")
    def unique(self):
        ids = [r.graph_id for r in self.repositories]
        if len(set(ids)) != len(ids) or len({r.name for r in self.repositories}) != len(ids):
            raise ValueError("duplicate repository")
        if not any(r.watch_prs for r in self.repositories):
            raise ValueError("set watch_prs: true on at least one repository")
        return self


class JiraAuth(Strict):
    kind: Literal["basic", "bearer"] = "basic"
    email_env: str = Field(default="JIRA_EMAIL", pattern=ENV_NAME)
    token_env: str = Field(default="JIRA_API_TOKEN", pattern=ENV_NAME)


class Jira(Strict):
    base_url: str
    project_keys: list[str] = Field(min_length=1)
    bot_account_id: str = Field(min_length=1)
    webhook_secret_env: str = Field(default="JIRA_WEBHOOK_SECRET", pattern=ENV_NAME)
    auth: JiraAuth = Field(default_factory=JiraAuth)


class Qualification(Strict):
    report_path: Path
    run_id: str = Field(min_length=1, max_length=200)
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Model(Strict):
    """The open model endpoint; off when the section is absent."""

    endpoint: str
    model: str = Field(min_length=1, max_length=200)
    configuration_id: str = Field(min_length=1, max_length=200)
    api_key_env: str = Field(default="MODEL_API_KEY", pattern=ENV_NAME)
    route: Literal["loopback", "corporate"] = "corporate"
    allow_source_transfer: bool = False
    qualification: Qualification | None = None
    settings: dict = Field(default_factory=dict)  # other agent_graph ModelConfig fields (limits, prices)


class Freshness(Strict):
    reconcile_seconds: int = Field(default=900, ge=60, le=86400)  # events missed by webhooks, graph upkeep
    mirror_sync_seconds: int = Field(default=120, ge=30, le=86400)  # git fetch of every repository
    code_max_age_seconds: int = Field(default=3600, ge=60, le=86400)
    runtime_window_seconds: int = Field(default=3600, ge=60, le=86400)


class Storage(Strict):
    keep_backups: int = Field(default=7, ge=2, le=100)
    daily_backup: bool = True


class Testing(Strict):
    """Only for the local HTTP stands of CI: plain-HTTP loopback APIs and local clone paths."""

    allow_loopback_http: bool = False
    allow_local_sources: bool = False
    fault_hooks: bool = False  # AGENT_SERVICE_BOX_KILL_AT=<phase> kills the installer at that phase


class BoxConfig(Strict):
    installation_id: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,80}$")
    environment: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,80}$")
    listen: Listen = Field(default_factory=Listen)
    github: GitHub
    jira: Jira | None = None
    service_addresses: dict[str, str] = Field(default_factory=dict)  # service -> base URL its clients call
    ownership_file: Path | None = None  # installation mapping {source, version, services}
    requirements: list[dict] = Field(default_factory=list)  # agent_graph ApprovedRequirement entries
    runtime_sources: list[dict] = Field(default_factory=list)  # agent_graph AccessLogSource entries
    model: Model | None = None
    publication: Literal["dry_run", "live"] = "dry_run"
    constitution_file: Path | None = None  # default: the constitution shipped in the release
    freshness: Freshness = Field(default_factory=Freshness)
    limits: dict = Field(default_factory=dict)  # agent_service queue Limits
    storage: Storage = Field(default_factory=Storage)
    testing: Testing = Field(default_factory=Testing)

    @model_validator(mode="after")
    def consistent(self):
        services = {r.service for r in self.github.repositories}
        unknown = sorted(set(self.service_addresses) - services)
        if unknown:
            raise ValueError(f"service_addresses names services without a repository: {', '.join(unknown)}")
        for r in self.github.repositories:
            if r.clone_url and not r.clone_url.startswith("https://") and not self.testing.allow_local_sources:
                raise ValueError(f"{r.name}: clone_url must be https:// (local paths are for test stands only)")
        for url in [self.github.api_base] + ([self.jira.base_url] if self.jira else []):
            u = urlsplit(url)
            if u.scheme != "https" and not (self.testing.allow_loopback_http and u.hostname in ("127.0.0.1",
                                                                                                "localhost")):
                raise ValueError(f"{url}: only https is allowed")
        return self

    # -- secrets ------------------------------------------------------------

    def secret_names(self) -> dict[str, str]:
        """{env name: why it is needed}. Values come from secrets.env, never from this file."""
        names = {STATUS_TOKEN_ENV: "status/graph access token (the box generates it)",
                 self.github.webhook_secret_env: "GitHub webhook secret"}
        if self.github.auth.kind == "app":
            names[self.github.auth.private_key_path_env] = "path to the GitHub App private key (.pem)"
        else:
            names[self.github.auth.token_env] = "GitHub token with read access to the repositories"
        if self.jira:
            names[self.jira.webhook_secret_env] = "Jira webhook secret"
            names[self.jira.auth.token_env] = "Jira API token"
            if self.jira.auth.kind == "basic":
                names[self.jira.auth.email_env] = "Jira account e-mail of the API token"
        if self.model:
            names[self.model.api_key_env] = "model endpoint API key"
        return names

    # -- generated service configuration -----------------------------------

    def clone_url(self, repo: Repository) -> str:
        return repo.clone_url or f"{self.github.web_base.rstrip('/')}/{repo.name}.git"

    def policy(self, *, mirrors: Path, tips: dict[str, str], constitution: Path) -> dict:
        """agent_graph Policy: every repository read from its local mirror at pinned commits."""
        repositories = []
        for r in self.github.repositories:
            entry = dict(id=r.graph_id, service=r.service, root=str(mirrors / f"{r.graph_id}.git"), snapshot="git",
                         revision=tips[r.graph_id])
            if r.include:
                entry["include"] = r.include
            repositories.append(entry)
        policy = dict(installation_id=self.installation_id, environment=self.environment, subject="agent-service",
                      capabilities=["read_context", "maintain", "propose", "report_check"],
                      repositories=repositories,
                      addresses=[dict(service=s, base_url=u) for s, u in sorted(self.service_addresses.items())],
                      requirements=self.requirements, constitution=str(constitution),
                      limits=dict(freshness_seconds=self.freshness.code_max_age_seconds))
        if self.model:
            m = self.model
            policy["model"] = dict(protocol="actions-v3", endpoint=m.endpoint, allowed_endpoints=[m.endpoint],
                                   model=m.model, configuration_id=m.configuration_id, api_key_env=m.api_key_env,
                                   route=m.route, allow_source_transfer=m.allow_source_transfer, **m.settings)
        return policy

    def service(self, *, state: Path, policy_path: Path, constitution: Path, release_id: str) -> dict:
        """agent_service ServiceConfig."""
        gh = self.github
        auth = dict(kind=gh.auth.kind)
        if gh.auth.kind == "app":
            auth.update(app_id=gh.auth.app_id, installation_id=gh.auth.installation_id,
                        private_key_path_env=gh.auth.private_key_path_env)
        else:
            auth["token_env"] = gh.auth.token_env
        config = dict(
            installation_id=self.installation_id, environment=self.environment,
            state_path=str(state / "service" / "service.sqlite"), publication=self.publication,
            dry_run_dir=str(state / "dry-run"),
            github=dict(api_base=gh.api_base, repositories=[r.name for r in gh.repositories if r.watch_prs],
                        read_repositories={r.name: r.branch for r in gh.repositories},
                        repository_ids={r.name: r.graph_id for r in gh.repositories}, bot_login=gh.bot_login,
                        webhook_secret_env=gh.webhook_secret_env, auth=auth),
            analysis=dict(code_version=release_id),
            core=dict(policy_path=str(policy_path), state_dir=str(state / "core"),
                      ownership_path=str(self.ownership_file) if self.ownership_file else None,
                      runtime_sources=self.runtime_sources,
                      runtime_window_seconds=self.freshness.runtime_window_seconds,
                      constitution_path=str(constitution),
                      model_qualification=self.model.qualification.model_dump(mode="json")
                      if self.model and self.model.qualification else None),
            limits=self.limits, reconcile_seconds=self.freshness.reconcile_seconds,
            allow_loopback_http=self.testing.allow_loopback_http)
        if self.jira:
            j = self.jira
            jauth = dict(kind=j.auth.kind, token_env=j.auth.token_env)
            if j.auth.kind == "basic":
                jauth["email_env"] = j.auth.email_env
            config["jira"] = dict(base_url=j.base_url, project_keys=j.project_keys, bot_account_id=j.bot_account_id,
                                  webhook_secret_env=j.webhook_secret_env, auth=jauth)
        return config


class ConfigProblem(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def load(path: Path) -> BoxConfig:
    """Parse and validate; problems name the field, never echo its value."""
    import yaml

    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigProblem([f"config file not found: {path}"]) from None
    except (yaml.YAMLError, UnicodeError):
        raise ConfigProblem([f"config file is not valid YAML: {path}"]) from None
    try:
        return BoxConfig.model_validate(data)
    except ValidationError as exc:
        problems = []
        for e in exc.errors(include_input=False, include_url=False):
            where = ".".join(str(p) for p in e["loc"]) or "(file)"
            problems.append(f"{where}: {e['msg']}")
        raise ConfigProblem(problems) from None


def read_secrets(path: Path) -> dict[str, str]:
    """KEY=VALUE lines (systemd EnvironmentFile subset). Values stay in memory only."""
    values = {}
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not re.fullmatch(ENV_NAME, key):
            raise ConfigProblem([f"{path}: line {number} is not NAME=value"])
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def write_json(path: Path, value) -> bool:
    """Write only when the content differs; returns whether it changed."""
    data = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    return write_bytes(path, data)


def write_bytes(path: Path, data: bytes, mode: int = 0o644) -> bool:
    path = Path(path)
    if path.is_file() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
        os.chmod(tmp, mode)
    tmp.replace(path)
    return True
