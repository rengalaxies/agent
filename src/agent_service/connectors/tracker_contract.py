"""Additive identity helpers for future task trackers; no provider registration.

Legacy Jira resource/comment IDs remain unchanged. New adapters use scoped,
versioned identities rather than display keys or ambiguous delimiters.
"""
from dataclasses import dataclass
import hashlib
import json

from .base import ResourceNotAllowed


def _identifier(value):
    if not isinstance(value, str) or not value or len(value) > 300 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("invalid_tracker_identity")
    return value


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class TaskIdentity:
    provider: str
    tenant: str
    native_id: str

    def __post_init__(self):
        if self.provider not in {"jira", "kaiten", "yandex_tracker"}:
            raise ValueError("invalid_tracker_provider")
        _identifier(self.tenant)
        _identifier(self.native_id)

    def as_list(self):
        return [self.provider, self.tenant, self.native_id]


@dataclass(frozen=True)
class CommentIdentity:
    task: TaskIdentity
    native_id: str

    def __post_init__(self):
        if not isinstance(self.task, TaskIdentity):
            raise ValueError("invalid_tracker_identity")
        _identifier(self.native_id)

    def encode(self):
        return "tracker-comment:v1:" + _json(self.task.as_list() + [self.native_id])

    @classmethod
    def decode(cls, value, *, expected=None):
        try:
            if not isinstance(value, str) or not value.startswith("tracker-comment:v1:") or len(value) > 8000:
                raise ValueError
            parts = json.loads(value[len("tracker-comment:v1:"):])
            if not isinstance(parts, list) or len(parts) != 4:
                raise ValueError
            result = cls(TaskIdentity(*parts[:3]), parts[3])
        except (ValueError, TypeError):
            raise ValueError("invalid_comment_identity") from None
        if expected is not None and result.task != expected:
            raise ResourceNotAllowed("linked_tracker_changed")
        return result


def semantic_version(task: TaskIdentity, fields: dict, field_names, *, closed=False):
    """Hash complete explicit semantic projection, before presentation truncation.

    Adapters supply a fixed field allowlist and normalized set-valued fields.
    Never include native version/updated/comment metadata in that allowlist.
    """
    payload = [task.as_list(), bool(closed), {name: fields.get(name) for name in field_names}]
    return "task:v1:" + hashlib.sha256(_json(payload).encode()).hexdigest()
