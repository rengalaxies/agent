"""The web boundary accepts scenario IDs, never paths, policies or executables."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

VERSIONS = ("A", "B", "D", "E")
CORE_SHA = "18e8b71b39eb6d2368d40ffb3892b9a5cdf2cd70"
PROFILE = "http-requests-4"


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical(v):
    return json.dumps(
        v, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(v):
    return hashlib.sha256(canonical(v).encode()).hexdigest()


class DemoError(Exception):
    def __init__(self, code, status=409):
        self.code, self.status = code, status
        super().__init__(code)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Payload(Strict):
    target_version: Literal["B", "D", "E"] | None = None
    base_context_id: str | None = None
    context_id: str | None = None
    task: str = Field(default="", max_length=4000)


class JobRequest(Strict):
    action: Literal["prepare_context", "analyze_change", "investigate"]
    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=100)
    payload: Payload = Field(default_factory=Payload)

    @model_validator(mode="after")
    def combinations(self):
        p = self.payload
        fields = p.model_fields_set
        valid = {
            "prepare_context": {"task"},
            "analyze_change": {"target_version", "base_context_id", "task"},
            "investigate": {"context_id"},
        }[self.action]
        if fields - valid:
            raise ValueError("invalid_payload_fields")
        if self.action == "analyze_change" and not (
            p.target_version and p.base_context_id
        ):
            raise ValueError("selection_requires_base")
        if self.action == "investigate" and not p.context_id:
            raise ValueError("investigation_requires_context")
        return self


class ResetRequest(Strict):
    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=100)


class CorrectionRequest(ResetRequest):
    context_id: str
    evidence_id: str
    key: str = Field(min_length=1, max_length=160)
    statement: str = Field(min_length=1, max_length=4000)
    supersedes: str | None = None


class DemoSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state_root: Path
    core_root: Path
    auth_config_path: Path
    runtime_registry_path: Path
    allowed_origins: list[str] = ["http://127.0.0.1:18081"]
    public_mode: bool = False
    start_worker: bool = True
    job_seconds: float = Field(default=180, gt=0, le=180)
    product_sha: str = "WORKTREE"

    @model_validator(mode="after")
    def origins(self):
        if not self.allowed_origins:
            raise ValueError("origin_required")
        for origin in self.allowed_origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
                or self.public_mode
                and parsed.scheme != "https"
            ):
                raise ValueError("invalid_origin_configuration")
        return self
