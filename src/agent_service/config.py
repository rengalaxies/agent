"""Installation configuration. Secrets are referenced by environment variable name, never stored here."""

from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .connectors.github import GitHubAppAuth, GitHubConnector, StaticToken
from .connectors.bitbucket_read import ApiTokenAuth, BitbucketReadClient
from .connectors.bitbucket import BitbucketQueueConnector
from .connectors.bitbucket_analysis import BitbucketLocalAnalysisConnector
from .connectors.bitbucket_jira import BitbucketJiraBackend
from .connectors.jira import DEFAULT_FIELDS, BasicAuth, BearerAuth, JiraConnector
from .http import HttpClient, validate_base_url
from .publisher import DirectorySink
from .queue import Limits, ServiceStore


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GitHubAuthConfig(Strict):
    kind: Literal["app", "token"]
    app_id: str | None = None
    installation_id: int | None = None
    private_key_path_env: str | None = None  # env var holding the path to the App private key PEM
    token_env: str | None = None


class GitHubConfig(Strict):
    api_base: str = "https://api.github.com"
    repositories: list[str] = Field(min_length=1)
    read_repositories: dict[str, str] = Field(default_factory=dict)  # every readable repo -> pinned branch
    repository_ids: dict[str, str] = Field(default_factory=dict)  # owner/repo -> repository name in the graph
    bot_login: str  # e.g. "my-app[bot]"; only its comments with our marker are ours
    webhook_secret_env: str
    auth: GitHubAuthConfig


BitbucketSlug = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,99}$")]
SecretEnv = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")]
RepositoryName = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_.-]{1,80}$")]


class BitbucketAuthConfig(Strict):
    email_env: SecretEnv
    token_env: SecretEnv


class BitbucketRepositoryConfig(Strict):
    uuid: UUID
    repository_id: RepositoryName


class BitbucketConfig(Strict):
    """Bitbucket probe, held queue intake, or isolated local analysis."""
    api_base: str = "https://api.bitbucket.org/2.0"
    mode: Literal['probe', 'queue_only', 'local_analysis', 'jira_delivery'] = 'probe'
    refresh_mirrors: bool = False
    workspace: BitbucketSlug
    workspace_uuid: UUID
    repositories: dict[BitbucketSlug, BitbucketRepositoryConfig] = Field(min_length=1, max_length=64)
    auth: BitbucketAuthConfig

    @model_validator(mode="after")
    def scope(self):
        url = validate_base_url(self.api_base, allow_loopback_http=True)
        parts = urlsplit(url)
        local = parts.scheme == 'http' and parts.hostname in {'127.0.0.1', 'localhost', '::1'} and parts.path == '/2.0'
        if url != 'https://api.bitbucket.org/2.0' and not local:
            raise ValueError('invalid_bitbucket_api_origin')
        if self.refresh_mirrors and (self.mode not in ("local_analysis", "jira_delivery") or local):
            raise ValueError("bitbucket_refresh_requires_cloud_local_analysis")
        self.api_base = url
        if (len({r.uuid for r in self.repositories.values()}) != len(self.repositories)
                or len({r.repository_id for r in self.repositories.values()}) != len(self.repositories)):
            raise ValueError('duplicate_bitbucket_repository_identity')
        return self


class JiraAuthConfig(Strict):
    kind: Literal["basic", "bearer"]
    email_env: str | None = None
    token_env: str


class JiraConfig(Strict):
    base_url: str  # https://<site>.atlassian.net or https://api.atlassian.com/ex/jira/<cloudId>
    project_keys: list[str] = Field(min_length=1)
    semantic_fields: list[str] = Field(default_factory=lambda: list(DEFAULT_FIELDS))
    bot_account_id: str
    webhook_secret_env: str
    auth: JiraAuthConfig


class QualificationRef(Strict):
    report_path: Path  # report.json of the batch 2B run (schema amvp-report-2)
    run_id: str = Field(min_length=1, max_length=200)
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CoreConfig(Strict):
    """The batch 2A core used as the analysis (``CoreAnalyzer``)."""

    policy_path: Path  # agent_graph Policy (JSON or YAML): repositories as local Git mirrors, snapshot: git
    state_dir: Path
    ownership_path: Path | None = None  # installation mapping {source, version, services}, re-read on reconcile
    runtime_sources: list[dict] = Field(default_factory=list)  # agent_graph AccessLogSource configurations
    runtime_window_seconds: int = Field(default=3600, ge=60, le=86400)
    constitution_path: Path | None = None
    # Batch 2B report that qualified the policy's model; checked against the loaded code on start.
    model_qualification: QualificationRef | None = None


class ServiceConfig(Strict):
    installation_id: str = Field(min_length=1, max_length=100)
    environment: str = Field(min_length=1, max_length=100)
    state_path: Path
    publication: Literal["dry_run", "live"] = "dry_run"
    dry_run_dir: Path | None = None
    github: GitHubConfig | None = None
    bitbucket: BitbucketConfig | None = None
    jira: JiraConfig | None = None
    analysis: dict = Field(default_factory=dict)  # graph/constitution/model ids, access scope, analysis_seconds
    core: CoreConfig | None = None
    limits: dict = Field(default_factory=dict)
    reconcile_seconds: float = Field(default=900, ge=60)
    allow_loopback_http: bool = False  # test stands only

    @model_validator(mode="after")
    def bitbucket_scope(self):
        if self.bitbucket:
            validate_base_url(self.bitbucket.api_base, allow_loopback_http=self.allow_loopback_http)
            if self.github:
                gh = self.github
                mapping = {k.lower(): v for k, v in gh.repository_ids.items()}
                readable = {r.lower() for r in gh.repositories} | {r.lower() for r in gh.read_repositories}
                github_ids = {mapping.get(r, r.replace('/', '.')) for r in readable}
                if github_ids & {r.repository_id for r in self.bitbucket.repositories.values()}:
                    raise ValueError('cross_provider_repository_id_collision')
        return self

    @classmethod
    def load(cls, path: Path) -> "ServiceConfig":
        text = Path(path).read_text(encoding="utf-8")
        if str(path).endswith((".yaml", ".yml")):
            import yaml

            try:
                document = yaml.safe_load(text)
            except yaml.YAMLError:
                raise ValueError('invalid_yaml_configuration') from None
            return cls.model_validate(document)
        return cls.model_validate(json.loads(text))


def _secret(name: str | None) -> str:
    value = os.environ.get(name or "", "")
    if not value:
        raise ValueError(f"missing_secret_env:{name}")
    return value


def build(config: ServiceConfig, *, clock=time.time, env_secret=_secret):
    """Return (store, connectors, backends) for the configuration."""
    _runtime_supported(config)
    store = ServiceStore(config.state_path, clock=clock, limits=Limits(**config.limits))
    return (store, *build_connectors(config, clock=clock, env_secret=env_secret))


def build_connectors(config: ServiceConfig, *, clock=time.time, env_secret=_secret):
    """Return (connectors, backends) without opening the state: source probes of a release not yet started."""
    _runtime_supported(config)
    connectors = {}
    if config.bitbucket:
        reader = build_bitbucket_reader(config, env_secret=env_secret)
        if config.bitbucket.mode in ('local_analysis', 'jira_delivery'):
            repositories = _document(config.core.policy_path)["repositories"]
            mirrors = {repo["id"]: Path(repo["root"]) for repo in repositories}
            connectors['bitbucket'] = BitbucketLocalAnalysisConnector(
                reader, config.bitbucket.repositories, mirrors=mirrors,
                refresh_mirrors=config.bitbucket.refresh_mirrors,
                jira_project_keys=config.jira.project_keys if config.jira else [])
        else:
            connectors['bitbucket'] = BitbucketQueueConnector(
                reader, config.bitbucket.repositories,
                jira_project_keys=config.jira.project_keys if config.jira else [])
    if config.github:
        gh = config.github
        client = HttpClient(gh.api_base, allow_loopback_http=config.allow_loopback_http, clock=clock)
        if gh.auth.kind == "app":
            key = Path(env_secret(gh.auth.private_key_path_env)).read_bytes()
            auth = GitHubAppAuth(client, gh.auth.app_id, gh.auth.installation_id, key, clock)
        else:
            auth = StaticToken(env_secret(gh.auth.token_env))
        connectors["github"] = GitHubConnector(
            client, auth, repositories=gh.repositories, read_repositories=gh.read_repositories,
            repository_ids=gh.repository_ids,
            jira_project_keys=config.jira.project_keys if config.jira else [], bot_login=gh.bot_login,
            webhook_secret=env_secret(gh.webhook_secret_env).encode(), clock=clock)
    if config.jira:
        jc = config.jira
        client = HttpClient(jc.base_url, allow_loopback_http=config.allow_loopback_http, clock=clock)
        auth = BasicAuth(env_secret(jc.auth.email_env), env_secret(jc.auth.token_env)) if jc.auth.kind == "basic" \
            else BearerAuth(env_secret(jc.auth.token_env))
        connectors["jira"] = JiraConnector(client, auth, project_keys=jc.project_keys,
                                           bot_account_id=jc.bot_account_id,
                                           webhook_secret=env_secret(jc.webhook_secret_env).encode(), clock=clock,
                                           fields=jc.semantic_fields)
    if config.publication == "live":
        backends = connectors
    else:
        root = config.dry_run_dir or config.state_path.parent / "dry-run-comments"
        backends = {name: DirectorySink(root / name) for name in connectors}
    if config.bitbucket and config.bitbucket.mode == 'jira_delivery':
        jira = connectors.pop("jira")
        if config.publication == "live":
            backends = {"bitbucket": BitbucketJiraBackend(connectors["bitbucket"], jira)}
            connectors["bitbucket"].publication_ready = True
        else:
            backends.pop("jira", None)
    return connectors, backends


def _runtime_supported(config):
    if config.bitbucket:
        if config.bitbucket.mode == 'probe':
            raise ValueError('bitbucket_runtime_not_available_use_probe')
        if config.bitbucket.mode == 'local_analysis':
            if config.publication != 'dry_run' or config.github or config.jira or not config.core:
                raise ValueError('bitbucket_local_analysis_requires_isolated_dry_run_core')
        elif config.bitbucket.mode == 'jira_delivery':
            if config.github or not config.jira or not config.core:
                raise ValueError('bitbucket_jira_delivery_requires_core_and_jira')
        elif config.publication != 'dry_run':
            raise ValueError('bitbucket_queue_only_requires_dry_run')


def build_bitbucket_reader(config: ServiceConfig, *, env_secret=_secret):
    """Build only the read probe; no other provider secrets, state or analyzer."""
    bb = config.bitbucket
    if bb is None:
        raise ValueError('bitbucket_not_configured')
    return BitbucketReadClient(
        HttpClient(bb.api_base, allow_loopback_http=config.allow_loopback_http),
        ApiTokenAuth(env_secret(bb.auth.email_env), env_secret(bb.auth.token_env)),
        workspace=bb.workspace, workspace_uuid=str(bb.workspace_uuid), repositories=bb.repositories)


def _document(path: Path):
    text = Path(path).read_text(encoding="utf-8")
    if str(path).endswith((".yaml", ".yml")):
        import yaml

        return yaml.safe_load(text)
    return json.loads(text)


def core_analyzer(core: CoreConfig, *, code_version: str):
    from .core_analyzer import CoreAnalyzer

    return CoreAnalyzer(_document(core.policy_path), core.state_dir,
                        ownership_path=str(core.ownership_path) if core.ownership_path else None,
                        runtime_sources=core.runtime_sources, runtime_window_seconds=core.runtime_window_seconds,
                        code_version=code_version,
                        constitution_path=str(core.constitution_path) if core.constitution_path else None,
                        model_qualification=core.model_qualification.model_dump()
                        if core.model_qualification else None)
