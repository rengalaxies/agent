"""GitHub pull requests through a GitHub App (REST API version 2022-11-28).

Webhooks: ``X-Hub-Signature-256`` HMAC-SHA256 over the raw body,
``X-GitHub-Delivery`` is the delivery id. Only ``pull_request`` deliveries
can start work; ``issue_comment`` (including our own comment) never does.
Reads use the app installation token; the only write is the issue comment.
"""

from __future__ import annotations

import base64
import json
import re
import threading
from typing import Callable

from ..envelope import EventEnvelope, digest
from ..http import ClientError, HttpClient, NotFound, segment
from .base import (MAX_WEBHOOK_BYTES, Comment, Prepared, ResourceNotAllowed, Snapshot, WebhookRejected,
                   parse_marker, verify_hmac_sha256)

API_VERSION = "2022-11-28"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
REPO_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,80}$")  # contract Name of a repository
SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
RESOURCE_RE = re.compile(r"^github:([A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100})#([1-9][0-9]{0,9})$")
PR_ACTIONS = {"opened", "reopened", "synchronize", "edited", "ready_for_review", "closed"}
MAX_DIFF_BYTES = 2 * 1024 * 1024
MAX_COMMENT_PAGES = 10


def resource_id(repository: str, number: int) -> str:
    return f"github:{repository.lower()}#{int(number)}"


def jira_keys(texts: list[str], project_keys: list[str]) -> list[str]:
    """Explicit Jira keys only (``ORD-12`` in the title or branch), restricted to configured projects."""
    allowed = {p.upper() for p in project_keys}
    found = set()
    for text in texts:
        for project, number in re.findall(r"(?<![A-Za-z0-9_])([A-Z][A-Z0-9_]{1,9})-([1-9][0-9]{0,8})(?![A-Za-z0-9_])",
                                          text or ""):
            if project in allowed:
                found.add(f"{project}-{number}")
    return sorted(found)


def pr_version(head_sha: str, base_ref: str, keys: list[str], base_sha: str) -> str:
    # Both commits are analysis inputs; moving either invalidates the result.
    return "pr:" + digest({"head": head_sha, "base": base_sha, "base_ref": base_ref,
                           "jira": sorted(keys)})[:32]


class StaticToken:
    """Fine-grained token for development stands. Production uses ``GitHubAppAuth``."""

    def __init__(self, token: str):
        self.token = token

    def __call__(self) -> str:
        return f"Bearer {self.token}"


class GitHubAppAuth:
    """Installation access token from an App JWT (RS256), cached until shortly before expiry."""

    def __init__(self, client: HttpClient, app_id: str, installation_id: int, private_key_pem: bytes, clock):
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        self._key = serialization.load_pem_private_key(private_key_pem, password=None)
        self._sign = lambda data: self._key.sign(data, padding.PKCS1v15(), hashes.SHA256())
        self.client, self.app_id, self.installation_id, self.clock = client, str(app_id), int(installation_id), clock
        self._token, self._expires, self._lock = None, 0.0, threading.Lock()

    def _jwt(self) -> str:
        def b64(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

        now = int(self.clock())
        header = b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        claims = b64(json.dumps({"iat": now - 60, "exp": now + 540, "iss": self.app_id}).encode())
        signing_input = f"{header}.{claims}".encode()
        return f"{header}.{claims}.{b64(self._sign(signing_input))}"

    def __call__(self) -> str:
        from datetime import datetime

        with self._lock:
            if self._token is None or self.clock() >= self._expires - 120:
                resp = self.client.request(
                    "POST", f"/app/installations/{segment(self.installation_id)}/access_tokens",
                    headers={"Authorization": f"Bearer {self._jwt()}", "X-GitHub-Api-Version": API_VERSION},
                    json_body={}, accept="application/vnd.github+json").json()
                self._token = resp["token"]
                self._expires = datetime.fromisoformat(resp["expires_at"].replace("Z", "+00:00")).timestamp()
            return f"Bearer {self._token}"


class GitHubConnector:
    provider = "github"

    def __init__(self, client: HttpClient, auth: Callable[[], str], *, repositories: list[str],
                 read_repositories: dict[str, str] | None = None, repository_ids: dict[str, str] | None = None,
                 jira_project_keys: list[str] | None = None, bot_login: str, webhook_secret: bytes, clock,
                 installation_id: int | None = None):
        for repo in list(repositories) + list((read_repositories or {}).keys()):
            if not REPO_RE.match(repo):
                raise ValueError("invalid_repository")
        self.client, self.auth, self.clock = client, auth, clock
        self.repositories = {r.lower() for r in repositories}
        # Every readable repository and the branch pinned for analyses (consumers included).
        self.read_repositories = {k.lower(): v for k, v in (read_repositories or {}).items()}
        self.repository_ids = {k.lower(): v for k, v in (repository_ids or {}).items()}
        for repo in self.repositories | set(self.read_repositories):
            if not REPO_ID_RE.match(self.repository_id(repo)):
                raise ValueError("invalid_repository_id")
        self.jira_project_keys = list(jira_project_keys or [])
        self.bot_login = bot_login
        self.webhook_secret = webhook_secret
        self.installation_id = installation_id if installation_id is not None else getattr(auth, "installation_id", None)

    # -- transport --------------------------------------------------------

    def _call(self, method, path, *, accept="application/vnd.github+json", **kwargs):
        headers = {"Authorization": self.auth(), "X-GitHub-Api-Version": API_VERSION}
        return self.client.request(method, path, headers=headers, accept=accept, **kwargs)

    def repository_id(self, repository: str) -> str:
        """Name used by the analysis contracts: configured, or ``owner.repo``."""
        return self.repository_ids.get(repository.lower(), repository.lower().replace("/", "."))

    def readable_repository_ids(self) -> list[str]:
        return sorted({self.repository_id(r) for r in self.repositories | set(self.read_repositories)})

    def _repo(self, repository: str) -> str:
        owner, repo = repository.split("/")
        return f"/repos/{segment(owner)}/{segment(repo)}"

    def _parse_resource(self, rid: str) -> tuple[str, int]:
        match = RESOURCE_RE.match(rid)
        if not match:
            raise ResourceNotAllowed("invalid_resource_id")
        repository, number = match.group(1).lower(), int(match.group(2))
        if repository not in self.repositories:
            raise ResourceNotAllowed("repository_not_configured")
        return repository, number

    # -- webhooks ---------------------------------------------------------

    def parse_webhook(self, headers: dict[str, str], body: bytes) -> EventEnvelope:
        if len(body) > MAX_WEBHOOK_BYTES:
            raise WebhookRejected(413, "payload_too_large")
        verify_hmac_sha256(self.webhook_secret, body, headers.get("x-hub-signature-256"))
        delivery = headers.get("x-github-delivery", "")
        event = headers.get("x-github-event", "")
        if not delivery or len(delivery) > 200 or not event or len(event) > 100:
            raise WebhookRejected(400, "delivery_headers_missing")
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            raise WebhookRejected(400, "payload_not_json") from None
        if not isinstance(payload, dict):
            raise WebhookRejected(400, "payload_invalid_shape")
        for name in ("repository", "installation", "pull_request", "issue"):
            if name in payload and not isinstance(payload[name], dict):
                raise WebhookRejected(400, "payload_invalid_shape")
        pr_shape = payload.get("pull_request", {})
        if any(name in pr_shape and not isinstance(pr_shape[name], dict) for name in ("head", "base")):
            raise WebhookRejected(400, "payload_invalid_shape")
        if event != "ping" and self.installation_id is not None \
                and payload.get("installation", {}).get("id") != self.installation_id:
            raise WebhookRejected(403, "installation_not_configured")
        common = dict(provider="github", event_id=delivery, event_kind=event, payload_digest=digest(body),
                      received_at=self.clock())
        repository = str(((payload.get("repository") or {}).get("full_name")) or "").lower()
        if event != "pull_request":
            number = (payload.get("issue") or {}).get("number")
            rid = resource_id(repository, number) if REPO_RE.match(repository) and isinstance(number, int) \
                else f"github:{event}"
            return EventEnvelope(source=repository or "-", resource_id=rid, ignored_reason="event_not_relevant",
                                 **common)
        number, action = payload.get("number"), payload.get("action")
        if not REPO_RE.match(repository) or not isinstance(number, int):
            raise WebhookRejected(400, "payload_missing_resource")
        rid = resource_id(repository, number)
        common["event_kind"] = f"pull_request.{action}"[:100]
        if repository not in self.repositories:
            return EventEnvelope(source=repository, resource_id=rid, ignored_reason="repository_not_configured",
                                 **common)
        pr = payload.get("pull_request") or {}
        head, base = pr.get("head") or {}, pr.get("base") or {}
        hint = None
        if isinstance(head.get("sha"), str) and SHA_RE.match(head["sha"]) and isinstance(base.get("ref"), str) \
                and isinstance(base.get("sha"), str) and SHA_RE.match(base["sha"]):
            hint = pr_version(head["sha"], base["ref"],
                              jira_keys([str(pr.get("title") or ""), str(head.get("ref") or "")],
                                        self.jira_project_keys), base["sha"])
        return EventEnvelope(source=repository, resource_id=rid, resource_version_hint=hint,
                             ignored_reason=None if action in PR_ACTIONS else "action_not_relevant", **common)

    # -- reads ------------------------------------------------------------

    def _snapshot(self, repository: str, pr: dict) -> Snapshot:
        head, base = pr["head"]["sha"], pr["base"]["sha"]
        if not (SHA_RE.match(head) and SHA_RE.match(base)):
            raise ClientError("invalid_sha_in_response")
        keys = jira_keys([str(pr.get("title") or ""), str(pr["head"].get("ref") or "")], self.jira_project_keys)
        data = {"provider": "github", "repository": repository, "repository_id": self.repository_id(repository),
                "pr_id": int(pr["number"]), "base_sha": base,
                "head_sha": head, "base_ref": str(pr["base"]["ref"])[:255], "linked_jira_keys": keys,
                "updated_at": str(pr.get("updated_at") or "")[:40]}
        closed = pr.get("state") != "open"
        return Snapshot(resource_id(repository, pr["number"]), "pr", pr_version(head, data["base_ref"], keys, base),
                        data, closed)

    def fetch(self, rid: str) -> Snapshot:
        repository, number = self._parse_resource(rid)
        try:
            pr = self._call("GET", f"{self._repo(repository)}/pulls/{segment(number)}").json()
        except NotFound:
            return Snapshot(rid, "pr", "missing", {}, closed=True)
        return self._snapshot(repository, pr)

    def resolve_branch(self, repository: str, branch: str) -> str:
        sha = self._call("GET", f"{self._repo(repository)}/commits/{segment(branch)}",
                         accept="application/vnd.github.sha").body.decode().strip()
        if not SHA_RE.match(sha):
            raise ClientError("invalid_sha_in_response")
        return sha

    def prepare(self, snapshot: Snapshot) -> Prepared:
        data = snapshot.data
        repo_path = self._repo(data["repository"])
        basehead = segment(f"{data['base_sha']}...{data['head_sha']}")
        gaps, attachments = [], {}
        compare = self._call("GET", f"{repo_path}/compare/{basehead}", query={"per_page": 100}).json()
        changed = sorted({str(f.get("filename"))[:500] for f in compare.get("files", []) if f.get("filename")})
        if len(compare.get("files", [])) >= 300:
            gaps.append("changed_files_truncated_by_provider")
        try:
            diff = self._call("GET", f"{repo_path}/compare/{basehead}", accept="application/vnd.github.diff").body
            if len(diff) > MAX_DIFF_BYTES:
                gaps.append("diff_too_large")
            else:
                attachments["diff"] = diff
        except ClientError:
            gaps.append("diff_unavailable")
        # The 2.0 PullRequestTrigger has no fields for these, so they travel beside the request.
        attachments.update(changed_paths=changed[:1000], linked_jira_keys=data["linked_jira_keys"])
        return Prepared(dict(data), self.pin_revisions(data), attachments, gaps)

    def pin_revisions(self, pr: dict | None) -> dict[str, str]:
        """Commit per readable repository: the PR head for its own repository, the pinned branch tip elsewhere."""
        revisions = {}
        for repository, branch in sorted(self.read_repositories.items()):
            if pr is None or repository != pr["repository"]:
                revisions[self.repository_id(repository)] = self.resolve_branch(repository, branch)
        if pr is not None:
            revisions[pr["repository_id"]] = pr["head_sha"]
        return revisions

    def reconcile_candidates(self, since: float | None) -> list[tuple[str, str]]:
        """All open PRs of configured repositories with their current version."""
        out = []
        for repository in sorted(self.repositories):
            for page in range(1, 5):
                prs = self._call("GET", f"{self._repo(repository)}/pulls",
                                 query={"state": "open", "sort": "updated", "direction": "desc",
                                        "per_page": 50, "page": page}).json()
                for pr in prs:
                    snap = self._snapshot(repository, pr)
                    out.append((snap.resource_id, snap.version))
                if len(prs) < 50:
                    break
            else:
                raise ClientError("reconcile_listing_incomplete")
        return out

    def complete_listing(self) -> bool:
        return True  # reconcile_candidates lists every open PR, so absence means closed

    # -- comments ---------------------------------------------------------

    def _comment(self, item: dict) -> Comment:
        marker, body_digest, generation = parse_marker(item.get("body") or "")
        return Comment(str(item["id"]), str((item.get("user") or {}).get("login") or ""), marker, body_digest,
                       generation)

    def list_comments(self, rid: str) -> list[Comment]:
        repository, number = self._parse_resource(rid)
        out = []
        for page in range(1, MAX_COMMENT_PAGES + 1):
            items = self._call("GET", f"{self._repo(repository)}/issues/{segment(number)}/comments",
                               query={"per_page": 100, "page": page}).json()
            out.extend(self._comment(i) for i in items)
            if len(items) < 100:
                break
        else:
            raise ClientError("comment_listing_incomplete")
        return out

    def get_comment(self, rid: str, comment_id: str) -> Comment | None:
        repository, _ = self._parse_resource(rid)
        try:
            return self._comment(self._call("GET", f"{self._repo(repository)}/issues/comments/"
                                                   f"{segment(comment_id)}").json())
        except NotFound:
            return None

    def create_comment(self, rid: str, doc: dict, marker: str) -> str:
        repository, number = self._parse_resource(rid)
        resp = self._call("POST", f"{self._repo(repository)}/issues/{segment(number)}/comments",
                          json_body={"body": to_markdown(doc, marker)})
        return str(resp.json()["id"])

    def update_comment(self, rid: str, comment_id: str, doc: dict, marker: str) -> None:
        repository, _ = self._parse_resource(rid)
        self._call("PATCH", f"{self._repo(repository)}/issues/comments/{segment(comment_id)}",
                   json_body={"body": to_markdown(doc, marker)})

    @property
    def bot_identity(self) -> str:
        return self.bot_login


_MD_ESCAPE = str.maketrans({"<": "&lt;", "[": "\\[", "]": "\\]", "!": "\\!",
                            "*": "\\*", "|": "\\|", "~": "\\~"})
_URL_RE = re.compile(r"(?:[A-Za-z][A-Za-z0-9+.-]*://|www\.)[^\s`]+")
_MENTION_RE = re.compile(r"(?<![A-Za-z0-9])@")  # "@team" notifies; "repo@sha" does not


def _plain(text: str) -> str:
    return _MENTION_RE.sub("&#64;", text.translate(_MD_ESCAPE))


def _md(text: str) -> str:
    """Analysis text is untrusted: no mentions, links, images or HTML in the comment.

    GitHub autolinks bare URLs, so URL-like tokens are shown as code spans.
    """
    text = " ".join(str(text).replace("`", "'").split())
    parts, last = [], 0
    for match in _URL_RE.finditer(text):
        parts.append(_plain(text[last:match.start()]))
        parts.append(f"`{match.group(0)}`")
        last = match.end()
    parts.append(_plain(text[last:]))
    return "".join(parts)


def to_markdown(doc: dict, marker: str) -> str:
    lines = [f"### {_md(doc['title'])}", "", _md(doc["status_line"]), ""]
    for section in doc["sections"]:
        lines.append(f"**{_md(section['title'])}**")
        lines.extend(f"- {_md(item)}" for item in section["items"] or ["нет данных"])
        lines.append("")
    lines.append(f"<!-- {marker} -->")
    return "\n".join(lines)
