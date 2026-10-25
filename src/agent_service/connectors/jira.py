"""Jira Cloud issues (REST API v3) with an admin-registered webhook.

Webhooks: the admin webhook secret gives ``X-Hub-Signature: sha256=<hex>``
over the raw body; ``X-Atlassian-Webhook-Identifier`` is stable across
retries and is the delivery id. Comment events never start work, and the
resource version is a digest of the configured semantic fields only, so the
``updated`` timestamp that our own comment bumps cannot open a generation.

The base URL is either ``https://<site>.atlassian.net`` (basic auth with an
API token of a dedicated account) or ``https://api.atlassian.com/ex/jira/<cloudId>``
(OAuth/scoped token); paths are identical.
"""

from __future__ import annotations

import base64
import json
import re

from ..envelope import EventEnvelope, digest
from ..http import HttpClient, NotFound, segment
from .base import (MAX_WEBHOOK_BYTES, Comment, Prepared, ResourceNotAllowed, Snapshot, WebhookRejected,
                   parse_marker, verify_hmac_sha256)

PROJECT_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,9}$")
RESOURCE_RE = re.compile(r"^jira:([1-9][0-9]{0,15})$")
ISSUE_EVENTS = {"jira:issue_created", "jira:issue_updated", "jira:issue_deleted"}
DEFAULT_FIELDS = ("summary", "description", "issuetype", "labels", "components")
MAX_TEXT = 20000


def resource_id(issue_id) -> str:
    return f"jira:{int(issue_id)}"


class BasicAuth:
    def __init__(self, email: str, api_token: str):
        self.value = "Basic " + base64.b64encode(f"{email}:{api_token}".encode()).decode()

    def __call__(self) -> str:
        return self.value


class BearerAuth:
    def __init__(self, token: str):
        self.token = token

    def __call__(self) -> str:
        return f"Bearer {self.token}"


def adf_text(node) -> str:
    """Plain text of an Atlassian Document Format tree (or a legacy string)."""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_text(n) for n in node)
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return str(node.get("text") or "")
    inner = adf_text(node.get("content") or [])
    return inner + ("\n" if node.get("type") in {"paragraph", "heading", "listItem", "codeBlock"} else "")


def semantic_fields(fields: dict, names) -> dict:
    out = {}
    for name in names:
        value = fields.get(name)
        if name == "description":
            out[name] = adf_text(value).strip()[:MAX_TEXT]
        elif name == "issuetype":
            out[name] = str((value or {}).get("name") or "")
        elif name == "components":
            out[name] = sorted(str(c.get("name") or "") for c in value or [] if isinstance(c, dict))
        elif name == "labels":
            out[name] = sorted(str(v) for v in value or [])
        else:
            out[name] = adf_text(value).strip()[:MAX_TEXT] if value is not None else ""
    return out


def issue_version(fields: dict, names) -> str:
    return "jira:" + digest(semantic_fields(fields, names))[:32]


class JiraConnector:
    provider = "jira"

    def __init__(self, client: HttpClient, auth, *, project_keys: list[str], bot_account_id: str,
                 webhook_secret: bytes, clock, fields=DEFAULT_FIELDS):
        for key in project_keys:
            if not PROJECT_RE.match(key):
                raise ValueError("invalid_project_key")
        self.client, self.auth, self.clock = client, auth, clock
        self.project_keys = sorted(set(project_keys))
        self.bot_account_id = bot_account_id
        self.webhook_secret = webhook_secret
        self.fields = tuple(fields)

    def _call(self, method, path, **kwargs):
        return self.client.request(method, path, headers={"Authorization": self.auth()}, **kwargs)

    def _issue_id(self, rid: str) -> str:
        match = RESOURCE_RE.match(rid)
        if not match:
            raise ResourceNotAllowed("invalid_resource_id")
        return match.group(1)

    # -- webhooks ---------------------------------------------------------

    def parse_webhook(self, headers: dict[str, str], body: bytes) -> EventEnvelope:
        if len(body) > MAX_WEBHOOK_BYTES:
            raise WebhookRejected(413, "payload_too_large")
        verify_hmac_sha256(self.webhook_secret, body, headers.get("x-hub-signature"))
        delivery = headers.get("x-atlassian-webhook-identifier", "")
        if not delivery or len(delivery) > 200:
            raise WebhookRejected(400, "delivery_headers_missing")
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            raise WebhookRejected(400, "payload_not_json") from None
        event = str(payload.get("webhookEvent") or "")[:100] or "unknown"
        issue = payload.get("issue") or {}
        issue_id = str(issue.get("id") or "")
        project = str(((issue.get("fields") or {}).get("project") or {}).get("key") or "")
        common = dict(provider="jira", event_id=delivery, event_kind=event, payload_digest=digest(body),
                      received_at=self.clock(), source=project or "-")
        if not issue_id.isdigit():
            return EventEnvelope(resource_id=f"jira:{event}", ignored_reason="event_not_relevant", **common)
        rid = resource_id(issue_id)
        if event not in ISSUE_EVENTS:
            # comment_created/updated (ours or anyone's) never trigger analysis.
            return EventEnvelope(resource_id=rid, ignored_reason="event_not_relevant", **common)
        if project and project not in self.project_keys:
            return EventEnvelope(resource_id=rid, ignored_reason="project_not_configured", **common)
        if event == "jira:issue_updated":
            items = (payload.get("changelog") or {}).get("items") or []
            changed = {str(i.get("fieldId") or i.get("field") or "").lower() for i in items if isinstance(i, dict)}
            if not changed & {f.lower() for f in self.fields} and payload.get("issue_event_type_name") in {
                    "issue_commented", "issue_comment_edited", "issue_comment_deleted", "issue_worklogged"}:
                return EventEnvelope(resource_id=rid, ignored_reason="non_semantic_change", **common)
        # Webhook descriptions are not in the REST v3 format, so no version hint.
        return EventEnvelope(resource_id=rid, **common)

    # -- reads ------------------------------------------------------------

    def _snapshot(self, issue: dict) -> Snapshot:
        fields = issue.get("fields") or {}
        project = str((fields.get("project") or {}).get("key") or "")
        if project not in self.project_keys:
            raise ResourceNotAllowed("project_not_configured")
        version = issue_version(fields, self.fields)
        data = {"project": project, "key": str(issue["key"])[:40], "issue_id": str(issue["id"]),
                "revision": version, "updated_at": str(fields.get("updated") or "")[:40],
                "fields": semantic_fields(fields, self.fields)}
        return Snapshot(resource_id(issue["id"]), "jira", version, data)

    def fetch(self, rid: str) -> Snapshot:
        issue_id = self._issue_id(rid)
        try:
            issue = self._call("GET", f"/rest/api/3/issue/{segment(issue_id)}",
                               query={"fields": ",".join(self.fields + ("project", "updated"))}).json()
        except NotFound:
            # Deleted, moved out of reach or permission removed: stop working on it.
            return Snapshot(rid, "jira", "missing", {}, closed=True)
        return self._snapshot(issue)

    def prepare(self, snapshot: Snapshot) -> Prepared:
        return Prepared(dict(snapshot.data), {}, {}, [])

    def reconcile_candidates(self, since: float | None) -> list[tuple[str, str]]:
        """Issues updated since the checkpoint, with the same semantic version as ``fetch``."""
        minutes = 7 * 24 * 60 if since is None else max(int((self.clock() - since) / 60) + 10, 10)
        minutes = min(minutes, 7 * 24 * 60)
        # Relative JQL avoids the account time zone of absolute dates.
        jql = f"project in ({','.join(self.project_keys)}) AND updated >= -{minutes}m ORDER BY updated ASC"
        out, token = [], None
        for _ in range(20):
            query = {"jql": jql, "maxResults": 100, "fields": ",".join(self.fields + ("project", "updated"))}
            if token:
                query["nextPageToken"] = token
            page = self._call("GET", "/rest/api/3/search/jql", query=query).json()
            for issue in page.get("issues", []):
                try:
                    snap = self._snapshot(issue)
                except ResourceNotAllowed:
                    continue
                out.append((snap.resource_id, snap.version))
            token = page.get("nextPageToken")
            if not token or page.get("isLast", True):
                break
        return out

    def complete_listing(self) -> bool:
        return False  # time-windowed search: absence does not mean deleted

    # -- comments ---------------------------------------------------------

    def _comment(self, item: dict) -> Comment:
        marker, body_digest, generation = parse_marker(adf_text(item.get("body")))
        return Comment(str(item["id"]), str((item.get("author") or {}).get("accountId") or ""), marker,
                       body_digest, generation)

    def list_comments(self, rid: str) -> list[Comment]:
        issue_id = self._issue_id(rid)
        out, start = [], 0
        for _ in range(10):
            page = self._call("GET", f"/rest/api/3/issue/{segment(issue_id)}/comment",
                              query={"startAt": start, "maxResults": 100, "orderBy": "created"}).json()
            items = page.get("comments", [])
            out.extend(self._comment(i) for i in items)
            start += len(items)
            if not items or start >= int(page.get("total", 0)):
                break
        return out

    def get_comment(self, rid: str, comment_id: str) -> Comment | None:
        issue_id = self._issue_id(rid)
        try:
            return self._comment(self._call("GET", f"/rest/api/3/issue/{segment(issue_id)}/comment/"
                                                   f"{segment(comment_id)}").json())
        except NotFound:
            return None

    def create_comment(self, rid: str, doc: dict, marker: str) -> str:
        issue_id = self._issue_id(rid)
        resp = self._call("POST", f"/rest/api/3/issue/{segment(issue_id)}/comment",
                          json_body={"body": to_adf(doc, marker)})
        return str(resp.json()["id"])

    def update_comment(self, rid: str, comment_id: str, doc: dict, marker: str) -> None:
        issue_id = self._issue_id(rid)
        # Edits of the service comment are not news for watchers.
        self._call("PUT", f"/rest/api/3/issue/{segment(issue_id)}/comment/{segment(comment_id)}",
                   query={"notifyUsers": "false"}, json_body={"body": to_adf(doc, marker)})

    @property
    def bot_identity(self) -> str:
        return self.bot_account_id


def _text(value: str) -> dict:
    return {"type": "text", "text": " ".join(str(value).split()) or " "}


def to_adf(doc: dict, marker: str) -> dict:
    """ADF text nodes are plain text: analysis output cannot add mentions or links."""
    content = [{"type": "heading", "attrs": {"level": 3}, "content": [_text(doc["title"])]},
               {"type": "paragraph", "content": [_text(doc["status_line"])]}]
    for section in doc["sections"]:
        content.append({"type": "paragraph", "content": [{**_text(section["title"]),
                                                          "marks": [{"type": "strong"}]}]})
        content.append({"type": "bulletList", "content": [
            {"type": "listItem", "content": [{"type": "paragraph", "content": [_text(item)]}]}
            for item in section["items"] or ["нет данных"]]})
    content.append({"type": "paragraph", "content": [{**_text(marker), "marks": [{"type": "code"}]}]})
    return {"type": "doc", "version": 1, "content": content}

