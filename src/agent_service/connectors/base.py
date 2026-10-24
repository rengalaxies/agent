"""Shared connector types and webhook signature verification."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac
import re

MAX_WEBHOOK_BYTES = 5 * 1024 * 1024
MARKER_RE = re.compile(r"agent-service marker=([0-9a-f]{16}) digest=([0-9a-f]{64}) generation=(\d+)")


class WebhookRejected(Exception):
    def __init__(self, status: int, code: str):
        self.status, self.code = status, code
        super().__init__(code)


class ResourceNotAllowed(Exception):
    """The resource is outside the configured repositories/projects."""

    def __init__(self, code: str = "resource_not_configured"):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Snapshot:
    resource_id: str
    kind: str  # "pr" | "jira"
    version: str
    data: dict
    closed: bool = False


@dataclass(frozen=True)
class Comment:
    comment_id: str
    author: str
    marker: str | None
    digest: str | None
    generation: int | None


@dataclass
class Prepared:
    subject: dict
    repository_revisions: dict
    attachments: dict = field(default_factory=dict)
    gaps: list[str] = field(default_factory=list)


def verify_hmac_sha256(secret: bytes, body: bytes, header_value: str | None) -> None:
    """``sha256=<hex>`` over the raw body, as GitHub and Jira Cloud admin webhooks send it."""
    if not secret:
        raise WebhookRejected(500, "webhook_secret_not_configured")
    if not header_value or "=" not in header_value:
        raise WebhookRejected(401, "signature_missing")
    method, _, signature = header_value.partition("=")
    if method.strip().lower() != "sha256":
        raise WebhookRejected(401, "signature_method_unsupported")
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature.strip().lower()):
        raise WebhookRejected(401, "signature_invalid")


def parse_marker(text: str) -> tuple[str | None, str | None, int | None]:
    match = MARKER_RE.search(text or "")
    if not match:
        return None, None, None
    return match.group(1), match.group(2), int(match.group(3))


def marker_line(marker: str, body_digest: str, generation: int) -> str:
    return f"agent-service marker={marker} digest={body_digest} generation={generation}"
