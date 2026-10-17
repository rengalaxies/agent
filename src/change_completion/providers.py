"""Patch proposal sources. Providers receive source and intent, never test answers."""
from dataclasses import dataclass, field
import json
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .adapters import prepare_window_patch
from .verification import digest_bytes, load_json


class PatchProvider(Protocol):
    @property
    def identity(self) -> str: ...
    def propose(self, source: str, *, old_window: int, new_window: int) -> dict: ...


class WindowPatchProvider:
    identity = "deterministic-window-rewrite/1"

    def propose(self, source, *, old_window, new_window):
        return prepare_window_patch(source, old_window=old_window, new_window=new_window)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class ClientPatchProvider:
    """Explicit client HTTP gateway contract, not a vendor-specific API.

    POST {model,source,intent}; response exactly {candidate}. Deployment must
    approve source transfer and endpoint. No implicit external route or retries.
    """
    endpoint: str
    model: str
    allowed_endpoints: frozenset[str]
    allow_source_transfer: bool = False
    allow_loopback_http: bool = False
    api_key: str | None = field(default=None, repr=False)
    timeout_seconds: float = 10

    def __post_init__(self):
        url = urlsplit(self.endpoint)
        loopback_http = (self.allow_loopback_http and url.scheme == "http"
                         and url.hostname in {"127.0.0.1", "::1", "localhost"})
        if (self.endpoint not in self.allowed_endpoints or not self.allow_source_transfer
                or not self.model or not (url.scheme == "https" or loopback_http)
                or not url.hostname or url.username or url.password or url.fragment
                or type(self.timeout_seconds) not in (int, float)
                or not 0 < self.timeout_seconds <= 30):
            raise ValueError("unapproved_model_route")

    @property
    def identity(self):
        return "client-http/1:" + digest_bytes(json.dumps({"endpoint": self.endpoint, "model": self.model}, sort_keys=True).encode())

    def propose(self, source, *, old_window, new_window):
        if len(source.encode()) > 65_536:
            return {"status": "unsupported", "reason_codes": ["source_limit"]}
        payload = json.dumps({"model": self.model, "source": source,
                              "intent": {"old_window": old_window, "new_window": new_window}}, allow_nan=False).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        try:
            opener = build_opener(ProxyHandler({}), _NoRedirect())
            with opener.open(Request(self.endpoint, payload, headers), timeout=self.timeout_seconds) as response:
                data = load_json(response.read(65_537))
            if (set(data) != {"candidate"} or type(data["candidate"]) is not str
                    or not data["candidate"].strip() or len(data["candidate"].encode()) > 65_536):
                raise ValueError("invalid_model_response")
            return {"status": "prepared", "candidate": data["candidate"], "reason_codes": []}
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, RecursionError):
            return {"status": "unsupported", "reason_codes": ["model_unavailable_or_invalid"]}
