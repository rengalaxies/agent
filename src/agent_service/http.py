"""Pinned-host HTTP client with provider error classification.

Every request goes to the configured base URL; callers pass validated path
segments, never URLs taken from a payload. Redirects are refused so a
response cannot move a credentialed request to another host.
"""

from __future__ import annotations

from dataclasses import dataclass
from email.utils import parsedate_to_datetime
import http.client
import json
import socket
from urllib.parse import quote, urlencode, urlsplit
import urllib.error
import urllib.request

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_RETRY_AFTER = 3600.0


class ConnectorError(Exception):
    """Base class; ``code`` is a stable, secret-free reason code."""

    code = "connector_error"
    retryable = False

    def __init__(self, detail: str = "", *, status: int | None = None, retry_after: float | None = None):
        self.status, self.retry_after, self.detail = status, retry_after, detail
        super().__init__(f"{self.code}:{status}:{detail}")


class AuthError(ConnectorError):
    """401/403 that is not rate limiting: the connection needs attention."""

    code = "connection_unauthorized"


class RateLimited(ConnectorError):
    code = "rate_limited"
    retryable = True


class ServerError(ConnectorError):
    code = "provider_unavailable"
    retryable = True


class NotFound(ConnectorError):
    code = "not_found"


class ClientError(ConnectorError):
    code = "provider_rejected"


class TransportError(ConnectorError):
    """Request did not complete. For writes the outcome is unknown."""

    code = "outcome_unknown"
    retryable = True


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self):
        return json.loads(self.body.decode("utf-8"))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def validate_base_url(url: str, *, allow_loopback_http: bool = False) -> str:
    parts = urlsplit(url)
    loopback = parts.hostname in {"127.0.0.1", "localhost", "::1"}
    if (
        parts.scheme not in {"https", "http"}
        or (parts.scheme == "http" and not (allow_loopback_http and loopback))
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise ValueError("invalid_base_url")
    return url.rstrip("/")


def segment(value: str | int) -> str:
    """Quote one path segment; '/' and '..' cannot escape the API path."""
    text = str(value)
    if not text or text in {".", ".."} or len(text) > 300:
        raise ValueError("invalid_path_segment")
    return quote(text, safe="")


def retry_after_seconds(headers: dict[str, str], now: float) -> float | None:
    value = headers.get("retry-after")
    if value:
        try:
            seconds = float(value)
        except ValueError:
            try:
                seconds = parsedate_to_datetime(value).timestamp() - now
            except (TypeError, ValueError):
                seconds = None
        if seconds is not None:
            return min(max(seconds, 0.0), MAX_RETRY_AFTER)
    # GitHub primary rate limit: remaining=0 with an epoch reset.
    if headers.get("x-ratelimit-remaining") == "0" and headers.get("x-ratelimit-reset", "").isdigit():
        return min(max(float(headers["x-ratelimit-reset"]) - now, 0.0), MAX_RETRY_AFTER)
    return None


def classify(status: int, headers: dict[str, str], now: float, body: bytes = b"") -> ConnectorError:
    wait = retry_after_seconds(headers, now)
    if status == 429 or (status == 403 and wait is not None):
        return RateLimited(status=status, retry_after=wait)
    if status in (401, 403):
        return AuthError(status=status)
    if status in (404, 410):
        return NotFound(status=status)
    if status >= 500:
        return ServerError(status=status, retry_after=wait)
    return ClientError(status=status)


class HttpClient:
    def __init__(self, base_url: str, *, timeout: float = 15.0, allow_loopback_http: bool = False, clock=None):
        import time

        self.base_url = validate_base_url(base_url, allow_loopback_http=allow_loopback_http)
        self.host = urlsplit(self.base_url).netloc
        self.timeout = timeout
        self.clock = clock or time.time
        self._opener = urllib.request.build_opener(_NoRedirect)

    def request(self, method: str, path: str, *, query: dict | None = None, headers: dict | None = None,
                json_body=None, accept: str = "application/json") -> Response:
        if not path.startswith("/") or "//" in path or "\\" in path:
            raise ValueError("invalid_path")
        url = self.base_url + path + (("?" + urlencode(query)) if query else "")
        if urlsplit(url).netloc != self.host:
            raise ValueError("host_mismatch")
        data = None
        all_headers = {"Accept": accept, "User-Agent": "agent-service/1"}
        all_headers.update(headers or {})
        if json_body is not None:
            data = json.dumps(json_body, ensure_ascii=False).encode()
            all_headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=all_headers)
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                body = resp.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ClientError("response_too_large", status=resp.status)
                return Response(resp.status, {k.lower(): v for k, v in resp.headers.items()}, body)
        except urllib.error.HTTPError as exc:
            headers_lower = {k.lower(): v for k, v in (exc.headers or {}).items()}
            exc.close()
            raise classify(exc.code, headers_lower, self.clock()) from None
        except (urllib.error.URLError, http.client.HTTPException, socket.timeout, TimeoutError, ConnectionError) as exc:
            raise TransportError(type(exc).__name__) from None
