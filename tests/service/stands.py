"""Local HTTP stands emulating the GitHub REST and Jira Cloud REST v3 endpoints the service uses.

They answer real HTTP requests on 127.0.0.1 with the documented paths,
headers and status codes. Faults are injected per request: a status with
headers (429 + Retry-After, 5xx, 403) or a dropped connection before or
after the write was applied. They are stands, not proof of the live APIs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit


def sign(secret: bytes, body: bytes) -> str:
    return "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()


@dataclass
class Fault:
    method: str
    path: str  # regex matched against the path
    status: int | None = None
    headers: dict = field(default_factory=dict)
    drop: str | None = None  # "before" (not applied) or "after" (applied, response lost)
    times: int = 1


class Stand:
    """Threaded HTTP server with a request log and one-shot fault rules."""

    def __init__(self):
        self.lock = threading.RLock()
        self.log: list[tuple[str, str]] = []
        self.faults: list[Fault] = []
        self.on_request = None  # callable(method, path) run before handling
        stand = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _handle(self):
                parts = urlsplit(self.path)
                length = int(self.headers.get("content-length") or 0)
                body = self.rfile.read(length) if length else b""
                with stand.lock:
                    stand.log.append((self.command, parts.path))
                    fault = stand._take_fault(self.command, parts.path)
                if stand.on_request:
                    stand.on_request(self.command, parts.path)
                if fault and fault.drop == "before":
                    self.close_connection = True
                    return
                if fault and fault.status:
                    self._send(fault.status, {"message": "injected"}, fault.headers)
                    return
                with stand.lock:
                    status, payload, headers = stand.route(self.command, parts.path, parse_qs(parts.query),
                                                           {k.lower(): v for k, v in self.headers.items()}, body)
                if fault and fault.drop == "after":
                    self.close_connection = True
                    return
                self._send(status, payload, headers)

            def _send(self, status, payload, headers=None):
                headers = dict(headers or {})
                if isinstance(payload, (bytes, str)):
                    data = payload.encode() if isinstance(payload, str) else payload
                    ctype = headers.pop("content-type", "text/plain")
                else:
                    data = json.dumps(payload).encode()
                    ctype = "application/json"
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                for k, v in headers.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = _handle

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def _take_fault(self, method, path):
        for fault in self.faults:
            if fault.method == method and re.fullmatch(fault.path, path) and fault.times > 0:
                fault.times -= 1
                return fault
        return None

    def count(self, method, pattern) -> int:
        with self.lock:
            return sum(1 for m, p in self.log if m == method and re.fullmatch(pattern, p))

    def route(self, method, path, query, headers, body):
        raise NotImplementedError


class GitHubStand(Stand):
    def __init__(self, token="test-installation-token", bot_login="agent-service[bot]"):
        super().__init__()
        self.token, self.bot_login = token, bot_login
        self.prs: dict[tuple[str, int], dict] = {}
        self.branches: dict[tuple[str, str], str] = {}
        self.comments: dict[int, dict] = {}
        self.next_comment = 1000
        self.revoked = False
        self.written: list[str] = []  # every comment body accepted, in order
        self.app_id, self.app_public_key, self.token_exchanges = None, None, 0

    def add_pr(self, repo, number, *, head, base, title="", head_ref="feature", base_ref="main", state="open"):
        self.prs[(repo, number)] = {"number": number, "state": state, "title": title,
                                    "head": {"sha": head, "ref": head_ref}, "base": {"sha": base, "ref": base_ref},
                                    "updated_at": "2026-10-24T10:00:00Z"}

    def set_head(self, repo, number, head):
        with self.lock:
            self.prs[(repo, number)]["head"]["sha"] = head

    def add_comment(self, repo, number, body, login):
        with self.lock:
            self.next_comment += 1
            self.comments[self.next_comment] = {"id": self.next_comment, "repo": repo, "number": number,
                                                "body": body, "user": {"login": login}}
            return self.next_comment

    def service_comments(self, repo, number):
        return [c for c in self.comments.values() if (c["repo"], c["number"]) == (repo, number)
                and c["user"]["login"] == self.bot_login]

    def _app_token(self, headers):
        """POST /app/installations/{id}/access_tokens with an RS256 App JWT."""
        import base64

        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        def unb64(text):
            return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))

        try:
            header, claims, signature = headers.get("authorization", "").removeprefix("Bearer ").split(".")
            self.app_public_key.verify(unb64(signature), f"{header}.{claims}".encode(), padding.PKCS1v15(),
                                       hashes.SHA256())
            payload = json.loads(unb64(claims))
        except Exception:
            return 401, {"message": "A JSON web token could not be decoded"}, {}
        if payload["iss"] != self.app_id or payload["exp"] - payload["iat"] > 600:
            return 401, {"message": "invalid claims"}, {}
        self.token_exchanges += 1
        return 201, {"token": self.token, "expires_at": "2099-01-01T00:00:00Z"}, {}

    def route(self, method, path, query, headers, body):
        if method == "POST" and re.fullmatch(r"/app/installations/\d+/access_tokens", path):
            return self._app_token(headers)
        if self.revoked or headers.get("authorization") != f"Bearer {self.token}":
            return 401, {"message": "Bad credentials"}, {}
        if headers.get("x-github-api-version") != "2022-11-28":
            return 400, {"message": "unsupported api version"}, {}
        m = re.fullmatch(r"/repos/([^/]+)/([^/]+)(/.*)", path)
        if not m:
            return 404, {"message": "Not Found"}, {}
        repo, rest = f"{unquote(m.group(1))}/{unquote(m.group(2))}", m.group(3)
        if method == "GET" and (pm := re.fullmatch(r"/pulls/(\d+)", rest)):
            pr = self.prs.get((repo, int(pm.group(1))))
            return (200, pr, {}) if pr else (404, {"message": "Not Found"}, {})
        if method == "GET" and rest == "/pulls":
            page, per = int(query.get("page", ["1"])[0]), int(query.get("per_page", ["30"])[0])
            items = [pr for (r, _), pr in sorted(self.prs.items()) if r == repo and pr["state"] == "open"]
            return 200, items[(page - 1) * per: page * per], {}
        if method == "GET" and (cm := re.fullmatch(r"/compare/([0-9a-f]+)\.\.\.([0-9a-f]+)", unquote(rest))):
            base, head = cm.group(1), cm.group(2)
            if headers.get("accept") == "application/vnd.github.diff":
                return 200, f"diff --git a/orders/api.py b/orders/api.py\n-PAGE_SIZE = 100\n+PAGE_SIZE = 20\n# {base}..{head}\n", \
                    {"content-type": "text/x-diff"}
            return 200, {"files": [{"filename": "orders/api.py"}], "merge_base_commit": {"sha": base}}, {}
        if method == "GET" and (bm := re.fullmatch(r"/commits/([^/]+)", rest)):
            sha = self.branches.get((repo, unquote(bm.group(1))))
            if not sha:
                return 404, {"message": "Not Found"}, {}
            return 200, sha, {"content-type": "application/vnd.github.sha"}
        if (im := re.fullmatch(r"/issues/(\d+)/comments", rest)):
            number = int(im.group(1))
            if method == "GET":
                page, per = int(query.get("page", ["1"])[0]), int(query.get("per_page", ["30"])[0])
                items = [c for c in sorted(self.comments.values(), key=lambda c: c["id"])
                         if (c["repo"], c["number"]) == (repo, number)]
                return 200, [{k: c[k] for k in ("id", "body", "user")} for c in items[(page - 1) * per: page * per]], {}
            if method == "POST":
                cid = self.add_comment(repo, number, json.loads(body)["body"], self.bot_login)
                self.written.append(self.comments[cid]["body"])
                return 201, {"id": cid, "body": self.comments[cid]["body"], "user": {"login": self.bot_login}}, {}
        if (km := re.fullmatch(r"/issues/comments/(\d+)", rest)):
            comment = self.comments.get(int(km.group(1)))
            if comment is None or comment["repo"] != repo:
                return 404, {"message": "Not Found"}, {}
            if method == "GET":
                return 200, {k: comment[k] for k in ("id", "body", "user")}, {}
            if method == "PATCH":
                if comment["user"]["login"] != self.bot_login:
                    return 403, {"message": "Resource not accessible by integration"}, {}
                comment["body"] = json.loads(body)["body"]
                self.written.append(comment["body"])
                return 200, {k: comment[k] for k in ("id", "body", "user")}, {}
        return 404, {"message": "Not Found"}, {}


class JiraStand(Stand):
    def __init__(self, email="bot@example.invalid", api_token="jira-test-token", bot_account_id="bot-account"):
        super().__init__()
        import base64

        self.auth = "Basic " + base64.b64encode(f"{email}:{api_token}".encode()).decode()
        self.bot_account_id = bot_account_id
        self.issues: dict[str, dict] = {}
        self.comments: dict[str, list[dict]] = {}
        self.next_comment = 5000
        self.on_comment = None  # callable(issue_id, comment) after create/update, e.g. to send webhooks

    def add_issue(self, issue_id, key, project, summary, description):
        self.issues[str(issue_id)] = {"id": str(issue_id), "key": key, "fields": {
            "summary": summary, "project": {"key": project}, "issuetype": {"name": "Task"}, "labels": [],
            "components": [], "updated": "2026-10-24T10:00:00.000+0000", "_epoch": time.time(),
            "description": {"type": "doc", "version": 1, "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": description}]}]}}}
        self.comments.setdefault(str(issue_id), [])

    def touch(self, issue_id):
        fields = self.issues[str(issue_id)]["fields"]
        fields["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S.000+0000", time.gmtime())
        fields["_epoch"] = time.time()

    def set_summary(self, issue_id, summary):
        with self.lock:
            self.issues[str(issue_id)]["fields"]["summary"] = summary
            self.touch(issue_id)

    def _public(self, issue):
        return {"id": issue["id"], "key": issue["key"],
                "fields": {k: v for k, v in issue["fields"].items() if not k.startswith("_")}}

    def route(self, method, path, query, headers, body):
        if headers.get("authorization") != self.auth:
            return 401, {"errorMessages": ["unauthorized"]}, {}
        if method == "GET" and (m := re.fullmatch(r"/rest/api/3/issue/(\d+)", path)):
            issue = self.issues.get(m.group(1))
            return (200, self._public(issue), {}) if issue else (404, {"errorMessages": ["not found"]}, {})
        if method == "GET" and path == "/rest/api/3/search/jql":
            jql = query["jql"][0]
            minutes = int(re.search(r"updated >= -(\d+)m", jql).group(1))
            projects = re.search(r"project in \(([^)]*)\)", jql).group(1).split(",")
            items = [self._public(i) for i in self.issues.values()
                     if i["fields"]["project"]["key"] in projects and i["fields"]["_epoch"] >= time.time() - minutes * 60]
            return 200, {"issues": items, "isLast": True}, {}
        if (m := re.fullmatch(r"/rest/api/3/issue/(\d+)/comment", path)):
            issue_id = m.group(1)
            if issue_id not in self.issues:
                return 404, {"errorMessages": ["not found"]}, {}
            items = self.comments[issue_id]
            if method == "GET":
                start, size = int(query.get("startAt", ["0"])[0]), int(query.get("maxResults", ["50"])[0])
                return 200, {"comments": items[start:start + size], "startAt": start, "maxResults": size,
                             "total": len(items)}, {}
            if method == "POST":
                self.next_comment += 1
                comment = {"id": str(self.next_comment), "author": {"accountId": self.bot_account_id},
                           "body": json.loads(body)["body"]}
                items.append(comment)
                self.touch(issue_id)  # Jira bumps "updated" when a comment is added
                self._comment_event(issue_id, comment)
                return 201, comment, {}
        if (m := re.fullmatch(r"/rest/api/3/issue/(\d+)/comment/(\d+)", path)):
            issue_id, cid = m.group(1), m.group(2)
            comment = next((c for c in self.comments.get(issue_id, []) if c["id"] == cid), None)
            if comment is None:
                return 404, {"errorMessages": ["not found"]}, {}
            if method == "GET":
                return 200, comment, {}
            if method == "PUT":
                if query.get("notifyUsers") != ["false"]:
                    return 400, {"errorMessages": ["expected notifyUsers=false"]}, {}
                comment["body"] = json.loads(body)["body"]
                self.touch(issue_id)
                self._comment_event(issue_id, comment)
                return 200, comment, {}
        return 404, {"errorMessages": ["not found"]}, {}

    def _comment_event(self, issue_id, comment):
        if self.on_comment:
            threading.Thread(target=self.on_comment, args=(issue_id, comment), daemon=True).start()
