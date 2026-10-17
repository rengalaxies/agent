"""Opt-in delivery to a client-owned gateway, not a vendor API adapter.

Unknown outcomes require reconciliation with the gateway using the same key.
This module deliberately performs no retries and never follows redirects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import http.client
import ipaddress
import json
import re
import ssl
import time
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True)
class DeliveryConfig:
    endpoint: str | None = None
    allowed_endpoints: frozenset[str] = frozenset()
    allow_send: bool = False
    allow_loopback_http: bool = False
    api_key: str | None = field(default=None, repr=False)
    timeout: float = 5.0


def _safe_url(value: Any, loopback: bool) -> bool:
    if not isinstance(value, str) or not value or any(ord(c) <= 32 for c in value):
        return False
    try:
        u = urlsplit(value)
        if not u.hostname or u.username is not None or u.password is not None or u.fragment:
            return False
        _ = u.port
        if u.scheme == "https":
            return True
        return bool(loopback and u.scheme == "http" and ipaddress.ip_address(u.hostname).is_loopback)
    except ValueError:
        return False


class GatewayDelivery:
    """Caller must separately authorize the payload's source/diff disclosure scope."""

    def __init__(self, config: DeliveryConfig):
        self.config = config

    def send(self, kind: str, payload: dict, idempotency_key: str) -> dict:
        def result(status: str, code: str, receipt: dict | None = None) -> dict:
            return {"status": status, "receipt": receipt, "reason_codes": [code]}

        if kind not in {"pull_request", "notification"}:
            return result("blocked", "unsupported_delivery_kind")
        if not isinstance(idempotency_key, str) or not re.fullmatch(r"[0-9a-f]{64}", idempotency_key):
            return result("blocked", "invalid_idempotency_key")
        cfg = self.config
        if not cfg.allow_send or cfg.endpoint is None:
            return result("draft", "delivery_not_enabled")
        if (cfg.endpoint not in cfg.allowed_endpoints
                or not _safe_url(cfg.endpoint, cfg.allow_loopback_http)):
            return result("blocked", "endpoint_not_allowed")
        if (isinstance(cfg.timeout, bool) or not isinstance(cfg.timeout, (int, float))
                or not 0 < cfg.timeout <= 10):
            return result("blocked", "invalid_timeout")
        if cfg.api_key is not None and (not isinstance(cfg.api_key, str)
                or not cfg.api_key or any(ord(c) < 33 or ord(c) > 126 for c in cfg.api_key)):
            return result("blocked", "invalid_api_key")
        if not isinstance(payload, dict):
            return result("blocked", "invalid_payload")
        try:
            body = json.dumps({"kind": kind, "idempotency_key": idempotency_key,
                               "payload": payload}, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError, RecursionError):
            return result("blocked", "invalid_payload")
        if len(body) > 1_048_576:
            return result("blocked", "payload_too_large")
        u = urlsplit(cfg.endpoint)
        # http.client does not consult ambient proxy variables or netrc files.
        conn = (http.client.HTTPSConnection(u.hostname, u.port, timeout=cfg.timeout,
                                          context=ssl.create_default_context())
                if u.scheme == "https" else
                http.client.HTTPConnection(u.hostname, u.port, timeout=cfg.timeout))
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                   "Idempotency-Key": idempotency_key}
        if cfg.api_key is not None:
            headers["Authorization"] = "Bearer " + cfg.api_key
        try:
            deadline = time.monotonic() + cfg.timeout
            target = (u.path or "/") + (("?" + u.query) if u.query else "")
            conn.request("POST", target, body, headers)
            if conn.sock is not None:
                conn.sock.settimeout(max(.001, deadline - time.monotonic()))
            response = conn.getresponse()
            if not 200 <= response.status < 300:
                return result("unknown", "gateway_http_outcome_unknown")
            # Bound a trickling body by elapsed time as well as per-read timeout.
            chunks = []
            size = 0
            while size <= 65_536:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return result("unknown", "gateway_outcome_unknown")
                if conn.sock is not None:
                    conn.sock.settimeout(remaining)
                chunk = response.read1(min(8192, 65_537 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            raw = b"".join(chunks)
            if len(raw) > 65_536:
                return result("unknown", "gateway_response_too_large")
            data = json.loads(raw)
            receipt = data.get("receipt") if isinstance(data, dict) else None
            if (not isinstance(data, dict) or data.get("idempotency_key") != idempotency_key
                    or not isinstance(receipt, dict)
                    or not isinstance(receipt.get("external_id"), str)
                    or not receipt["external_id"].strip()
                    or len(receipt["external_id"]) > 1024
                    or not _safe_url(receipt.get("url"), cfg.allow_loopback_http)):
                return result("unknown", "gateway_receipt_invalid")
            return result("delivered", "gateway_receipt_received",
                          {"url": receipt["url"], "external_id": receipt["external_id"]})
        except (OSError, http.client.HTTPException, ValueError, UnicodeError, RecursionError):
            return result("unknown", "gateway_outcome_unknown")
        finally:
            conn.close()
