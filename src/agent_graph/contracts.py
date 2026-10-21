"""Operator configuration and untrusted agent messages have different contracts."""
from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def load_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite_json")))


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class GraphError(Exception):
    """Only this stable code is safe to return; never echo input/HTTP errors."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class Repository(Strict):
    id: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,64}$")
    service: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,64}$")
    root: str
    revision: str = Field(min_length=1, max_length=160)
    # Relative allowlist; no roots or dependencies are accepted from model output.
    include: list[str] = Field(default_factory=lambda: ["*.py", "*.json", "*.md"])

    @model_validator(mode="after")
    def patterns(self):
        if not self.include or any(p.startswith("/") or ".." in PurePosixPath(p).parts for p in self.include):
            raise ValueError("invalid_include")
        return self


class ServiceAddress(Strict):
    service: str
    base_url: str

    @model_validator(mode="after")
    def address(self):
        u = urlsplit(self.base_url)
        if (u.scheme not in ("http", "https") or not u.hostname or u.username or u.password
                or u.query or u.fragment or u.path.endswith("/") and u.path != ""):
            raise ValueError("invalid_service_address")
        return self


class ApprovedRequirement(Strict):
    id: str
    repository: str
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    issuer: str
    service: str
    method: str = "GET"
    path_template: str
    consumer: str
    predicate: Literal["complete_collection", "first_page_only"]
    # Approval is from this operator-owned configuration, never an extracted bool.


class Limits(Strict):
    max_files: int = Field(default=256, ge=1, le=10000)
    max_file_bytes: int = Field(default=65536, ge=1, le=262144)
    max_corpus_bytes: int = Field(default=2_000_000, ge=1, le=20_000_000)
    scan_seconds: float = Field(default=15.0, gt=0, le=120)
    freshness_seconds: int = Field(default=3600, ge=1, le=86400)
    max_model_steps: int = Field(default=4, ge=1, le=12)
    max_tool_lines: int = Field(default=60, ge=1, le=200)
    max_proposals: int = Field(default=24, ge=1, le=100,
                              description="Active non-superseded proposals at the current basis; immutable history is excluded.")


class ModelConfig(Strict):
    protocol: Literal["quotes-v1", "evidence-refs-v2"] = "quotes-v1"
    endpoint: str
    allowed_endpoints: list[str]
    model: str = Field(min_length=1, max_length=200)
    configuration_id: str = Field(min_length=1, max_length=200)
    api_key_env: str = Field(default="GRAPH_LLM_API_KEY", pattern=r"^[A-Z][A-Z0-9_]{0,80}$")
    allow_source_transfer: bool = False
    route: Literal["loopback", "corporate"] = "loopback"
    context_tokens: int = Field(default=16384, ge=4096, le=131072)
    max_output_tokens: int = Field(default=1024, ge=64, le=4096)
    max_prompt_bytes: int = Field(default=10000, ge=512, le=100000)
    timeout_seconds: float = Field(default=20.0, ge=0.1, le=60)
    installation_token_cap: int = Field(default=1_000_000, ge=1)
    run_token_cap: int = Field(default=100_000, ge=1)
    # Micro currency units. One worst-case rate covers input AND output.
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    micro_per_million_tokens: int = Field(default=0, ge=0)
    installation_micro_cap: int = Field(default=0, ge=0)
    run_micro_cap: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def route_valid(self):
        u = urlsplit(self.endpoint)
        local = (u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost", "::1"))
        if (not self.allow_source_transfer or self.endpoint not in self.allowed_endpoints
                or not u.hostname or u.username or u.password or u.query or u.fragment
                or not u.path.endswith("/chat/completions")
                or (self.route == "loopback" and not local)
                or (self.route == "corporate" and u.scheme != "https")
                or self.max_prompt_bytes + self.max_output_tokens + 4096 > self.context_tokens):
            raise ValueError("unapproved_model_configuration")
        if self.micro_per_million_tokens and not (self.installation_micro_cap and self.run_micro_cap):
            raise ValueError("missing_monetary_cap")
        if self.route == "corporate" and not self.micro_per_million_tokens:
            raise ValueError("corporate_cost_bound_required")
        return self


Capability = Literal["read_context", "maintain", "propose", "report_check", "correct"]


class Policy(Strict):
    installation_id: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,80}$")
    environment: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,80}$")
    subject: str = Field(min_length=1, max_length=100)
    capabilities: list[Capability]
    repositories: list[Repository] = Field(min_length=1, max_length=32)
    addresses: list[ServiceAddress]
    requirements: list[ApprovedRequirement] = Field(default_factory=list)
    limits: Limits = Field(default_factory=Limits)
    model: ModelConfig | None = None

    @model_validator(mode="after")
    def unique(self):
        if len({r.id for r in self.repositories}) != len(self.repositories):
            raise ValueError("duplicate_repository")
        if len({r.id for r in self.requirements}) != len(self.requirements):
            raise ValueError("duplicate_requirement")
        return self

    def require(self, capability):
        if capability not in self.capabilities:
            raise GraphError("forbidden")

    def view_id(self):
        # Same read grants may share a context. Different grants cannot retrieve
        # even a cached summary or count. Not an OS-level multi-tenant boundary.
        repos = [r.model_dump(exclude={"revision"}) for r in self.repositories]
        return digest([self.installation_id, self.environment, repos, self.addresses_dump(),
                       [r.model_dump() for r in self.requirements]])

    def addresses_dump(self):
        return [a.model_dump() for a in self.addresses]


class Citation(Strict):
    source_id: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=6000)


class Proposal(Strict):
    key: str = Field(min_length=1, max_length=160)
    kind: Literal["hypothesis", "requirement_candidate", "human_correction"]
    statement: str = Field(min_length=1, max_length=4000)
    citations: list[Citation] = Field(min_length=1, max_length=8)
    supersedes: str | None = None


class ExternalCheck(Strict):
    context_id: str
    candidate_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    artifact_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    command: str = Field(min_length=1, max_length=500)
    exit_code: int
    citations: list[Citation] = Field(min_length=1, max_length=8)


class ModelReply(Strict):
    action: Literal["read_source", "propose", "finish"]
    source_id: str | None
    start_line: int | None
    end_line: int | None
    proposals: list[Proposal] = Field(max_length=8)


def model_action_schema(reply_type=ModelReply):
    """Strict structured-output APIs require every property, nullable if optional."""
    schema = reply_type.model_json_schema()
    def visit(value):
        if isinstance(value, dict):
            value.pop("default", None)
            if value.get("type") == "object":
                value["required"] = list(value.get("properties", {}))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(schema)
    return schema
