"""Small closed-demo HTTP Basic auth; credentials live only in operator config."""

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass

from .contracts import DemoError


@dataclass
class Actor:
    subject: str
    role: str
    allowed_session_ids: list


def authenticate(request, settings):
    try:
        scheme, token = request.headers.get("authorization", "").split(" ", 1)
        if scheme.lower() != "basic":
            raise ValueError()
        username, password = (
            base64.b64decode(token, validate=True).decode().split(":", 1)
        )
        users = json.loads(settings.auth_config_path.read_text())["users"]
        user = next(
            (
                u
                for u in users
                if hmac.compare_digest(u["subject"].encode(), username.encode())
            ),
            None,
        )
        candidate = hashlib.sha256(password.encode()).hexdigest()
        expected = user["password_sha256"] if user else "0" * 64
        valid = hmac.compare_digest(candidate, expected)
        if not user or not valid or user["role"] not in ("operator", "viewer"):
            raise ValueError()
        return Actor(user["subject"], user["role"], user.get("allowed_session_ids", []))
    except (ValueError, UnicodeError, KeyError, OSError):
        raise DemoError("authentication_required", 401) from None


def authorize_session(actor, session, write=False):
    if write and actor.role != "operator":
        raise DemoError("operator_required", 403)
    if (
        session["owner"] != actor.subject
        and session["id"] not in actor.allowed_session_ids
    ):
        raise DemoError("session_forbidden", 403)
