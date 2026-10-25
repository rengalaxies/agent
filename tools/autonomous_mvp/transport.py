"""OpenAI-compatible Chat Completions transport for Cloud.ru Foundation Models.

Transport success is decided here and only here: HTTP 200, a JSON body within
limits and exactly one choice with string content. What the content means is the
action protocol's job, so a malformed action is never booked as a network fault.

No SDK, proxy environment, redirects or retries. The credential is read from one
environment variable at send time and never stored, logged or echoed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import http.client
import json
import os
import socket
import ssl
import time
from urllib.parse import urlsplit

ENDPOINT = "https://foundation-models.api.cloud.ru/v1/chat/completions"
MODELS_ENDPOINT = "https://foundation-models.api.cloud.ru/v1/models"
KEY_ENV = "CLOUDRU_FOUNDATION_API_KEY"
MAX_BODY = 1_048_576


@dataclass
class TransportResult:
    ok: bool
    code: str  # "ok" or a stable transport error code
    http_status: int | None = None
    finish_reason: str | None = None
    usage: dict | None = None
    content: str | None = field(default=None, repr=False)  # handed to the protocol, never persisted
    has_tool_calls: bool = False
    has_reasoning: bool = False
    returned_model: str | None = None
    latency_seconds: float = 0.0
    request_bytes: int = 0
    response_bytes: int = 0

    def safe(self):
        """Fields allowed into the ledger and reports."""
        return dict(ok=self.ok, code=self.code, http_status=self.http_status, finish_reason=self.finish_reason,
                    usage=self.usage, has_tool_calls=self.has_tool_calls, has_reasoning=self.has_reasoning,
                    returned_model=self.returned_model, latency_seconds=round(self.latency_seconds, 3),
                    request_bytes=self.request_bytes, response_bytes=self.response_bytes)


def _usage(data):
    usage = data.get("usage") if isinstance(data, dict) else None
    if (isinstance(usage, dict) and type(usage.get("prompt_tokens")) is int and usage["prompt_tokens"] >= 0
            and type(usage.get("completion_tokens")) is int and usage["completion_tokens"] >= 0):
        return dict(prompt_tokens=usage["prompt_tokens"], completion_tokens=usage["completion_tokens"])
    return None


def interpret(status, raw):
    """Classify one HTTP exchange. Pure function so the rules are testable offline."""
    result = TransportResult(ok=False, code="http_error", http_status=status, response_bytes=len(raw))
    if status == 429:
        result.code = "http_rate_limited"
    elif status in (401, 403):
        result.code = "http_unauthorized"
    elif status is not None and 500 <= status:
        result.code = "http_server_error"
    if status != 200:
        return result
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        result.code = "body_not_json"
        return result
    result.usage = _usage(data)
    choices = data.get("choices") if isinstance(data, dict) else None
    if isinstance(data, dict) and isinstance(data.get("model"), str):
        result.returned_model = data["model"][:200]
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        result.code = "no_single_choice"
        return result
    choice = choices[0]
    if isinstance(choice.get("finish_reason"), str):
        result.finish_reason = choice["finish_reason"][:40]
    message = choice.get("message")
    if not isinstance(message, dict):
        result.code = "no_message"
        return result
    result.has_tool_calls = bool(message.get("tool_calls"))
    result.has_reasoning = bool(message.get("reasoning_content") or message.get("reasoning"))
    if not isinstance(message.get("content"), str):
        result.code = "no_string_content"
        return result
    result.ok, result.code, result.content = True, "ok", message["content"]
    return result


class CloudRuTransport:
    """One request at a time; every stage checks the absolute deadline."""

    def __init__(self, *, endpoint=ENDPOINT, key_env=KEY_ENV, allowed_hosts=("foundation-models.api.cloud.ru",)):
        u = urlsplit(endpoint)
        if u.scheme != "https" or u.hostname not in allowed_hosts or u.username or u.query or u.fragment:
            raise ValueError("unapproved_endpoint")
        self.endpoint, self.key_env = endpoint, key_env

    def _secret(self):
        secret = os.environ.get(self.key_env, "")
        if not secret or any(c in secret for c in "\r\n"):
            return None
        return secret

    def _exchange(self, method, url, body, deadline):
        u = urlsplit(url)
        secret = self._secret()
        if secret is None:
            return None, b"", "missing_secret"
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None, b"", "deadline_before_send"
        headers = {"Authorization": "Bearer " + secret, "Accept": "application/json",
                   "Accept-Encoding": "identity"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        conn = http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=remaining,
                                           context=ssl.create_default_context())
        try:
            conn.request(method, u.path, body=body, headers=headers)
            conn.sock.settimeout(max(0.001, deadline - time.monotonic()))
            response = conn.getresponse()
            if response.getheader("Content-Encoding", "identity") != "identity":
                return response.status, b"", "unsupported_content_encoding"
            chunks, size = [], 0
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    return response.status, b"", "deadline_during_body"
                conn.sock.settimeout(min(5.0, left))
                chunk = response.read1(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BODY:
                    return response.status, b"", "body_limit"
                chunks.append(chunk)
            return response.status, b"".join(chunks), None
        except (socket.timeout, TimeoutError):
            return None, b"", "timeout"
        except ssl.SSLError:
            return None, b"", "tls_error"
        except (OSError, http.client.HTTPException):
            return None, b"", "connection_error"
        finally:
            conn.close()

    def complete(self, payload, *, deadline):
        """POST one chat completion. `deadline` is a time.monotonic() value."""
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        started = time.monotonic()
        status, raw, error = self._exchange("POST", self.endpoint, body, deadline)
        if error:
            result = TransportResult(ok=False, code=error, http_status=status)
        else:
            result = interpret(status, raw)
        result.latency_seconds = time.monotonic() - started
        result.request_bytes = len(body)
        return result

    def list_models(self, *, deadline):
        """GET /v1/models: availability check that spends no tokens."""
        status, raw, error = self._exchange("GET", MODELS_ENDPOINT, None, deadline)
        if error or status != 200:
            return dict(ok=False, code=error or ("http_unauthorized" if status in (401, 403) else "http_error"),
                        http_status=status, models=[])
        try:
            data = json.loads(raw)
            models = sorted({m["id"] for m in data["data"] if isinstance(m.get("id"), str)})
        except (ValueError, KeyError, TypeError):
            return dict(ok=False, code="body_not_json", http_status=status, models=[])
        return dict(ok=True, code="ok", http_status=status, models=models)


class ScriptedTransport:
    """Offline transport for tests and dry runs: replays prepared exchanges, sends nothing.

    Each script item is a TransportResult, a callable(payload) -> TransportResult,
    or ("sleep", seconds) to emulate a slow provider against the deadline.
    """

    def __init__(self, script, *, models=()):
        self.script, self.models, self.sent = list(script), list(models), []

    def complete(self, payload, *, deadline):
        self.sent.append(payload)
        if not self.script:
            return TransportResult(ok=False, code="script_exhausted")
        item = self.script.pop(0)
        started = time.monotonic()
        if isinstance(item, tuple) and item[0] == "sleep":
            if time.monotonic() + item[1] >= deadline:
                time.sleep(max(0.0, deadline - time.monotonic()))
                return TransportResult(ok=False, code="timeout", latency_seconds=time.monotonic() - started)
            time.sleep(item[1])
            item = self.script.pop(0)
        result = item(payload) if callable(item) else item
        result.latency_seconds = result.latency_seconds or (time.monotonic() - started)
        return result

    def list_models(self, *, deadline):
        return dict(ok=True, code="ok", http_status=200, models=sorted(self.models))


def reply(content, *, prompt_tokens=100, completion_tokens=20, finish_reason="stop"):
    """Build the TransportResult of a successful exchange (test helper)."""
    return interpret(200, json.dumps(dict(model="scripted", choices=[dict(
        index=0, finish_reason=finish_reason, message=dict(role="assistant", content=content))],
        usage=dict(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens))).encode())
