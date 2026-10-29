"""One updatable service comment per resource.

The comment body is rendered from a provider-neutral document whose digest
is embedded next to a per-resource marker. Before any create the publisher
looks for an existing comment by marker and author, so a lost response or a
restart after the write never leads to a blind second create. Provider
contracts do not offer exactly-once writes; this is idempotent
reconciliation within the failure model tested in ``tests/service``.
"""

from __future__ import annotations

import json
from pathlib import Path

from .analysis import ResultView
from .connectors.base import Comment, marker_line
from .envelope import EventEnvelope, canonical, digest
from .http import AuthError, ClientError, NotFound, RateLimited, ServerError, TransportError

STATUS_TITLES = {
    "USEFUL": "Возможное влияние изменения",
    "PARTIAL": "Частичный вывод о влиянии",
    "ABSTAINED": "Вывод о влиянии не сделан",
    "FAILED": "Технический отказ анализа",
}
ORIGIN_LABELS = {"code": "код", "runtime": "наблюдаемые вызовы", "model_hypothesis": "гипотеза модели",
                 "correction": "исправление", "external_report": "внешняя проверка",
                 "unknown_origin": "неизвестный тип основания"}
CLAIM_LABELS = {"fact": "Факт в пределах профиля", "hypothesis": "Гипотеза"}
AUTH_RETRY_SECONDS = 900.0


def resource_marker(installation_id: str, resource_id: str) -> str:
    return digest({"installation": installation_id, "resource": resource_id})[:16]


def _versions(snapshot: dict, kind: str, generation: int) -> list[str]:
    if kind == "pr":
        lines = [f"PR {snapshot.get('repository')}#{snapshot.get('pr_id')}: base {snapshot.get('base_sha', '')[:12]}, "
                 f"head {snapshot.get('head_sha', '')[:12]}"]
        if snapshot.get("linked_jira_keys"):
            lines.append("Связанные задачи Jira: " + ", ".join(snapshot["linked_jira_keys"]))
    else:
        lines = [f"Jira {snapshot.get('key')}: версия полей {str(snapshot.get('revision', ''))[5:17]}"]
    lines.append(f"Поколение анализа: {generation}")
    return lines


def _evidence(items: list[dict]) -> str:
    return "; ".join(f"{ORIGIN_LABELS[e['origin']]} {e['ref']}" + (f" ({e['uncertainty']})" if e["uncertainty"] else "")
                     for e in items) or "основания не указаны"


def _risks(result: dict) -> dict[str, str]:
    """Deltas and findings of a raw result, keyed so that two generations compare."""
    risks = {}
    for d in result.get("deltas") or []:
        op = d.get("operation") or {}
        name = f"{op.get('service')} {op.get('method')} {op.get('route')}"
        risks[f"delta {name} {d.get('code')}"] = f"изменение {name}: {d.get('code')} {d.get('before')} -> {d.get('after')}"
    for f in result.get("findings") or []:
        consumer = (f.get("consumer") or {}).get("service")
        risks[f"finding {consumer} {f.get('code')}"] = f"{f.get('code')} у {consumer}"
    return risks


def since_previous(previous: tuple[int, dict] | None, current) -> list[str]:
    """What the last published result reported and the current one no longer does."""
    if previous is None or not isinstance(current, dict):
        return []
    generation, result = previous
    now = _risks(current)
    gone = [text for key, text in _risks(result).items() if key not in now]
    if not gone:
        return []
    return [f"Поколение {generation}: {text}. В текущей версии не обнаружено." for text in gone] + [
        "Это отсутствие находки в поддерживаемом профиле, а не выполненная проверка: тесты не запускались."]


def result_doc(view: ResultView, *, snapshot: dict, kind: str, generation: int, gaps: list[str],
               earlier: list[str] = ()) -> dict:
    """что изменилось → что затронуто → почему/путь → что проверить → неизвестные/свежесть → версии."""
    if not view.compatible:
        title = "Результат анализа несовместим с сервисом"
        status = f"Результат не показан: {view.reason_code}. Это не означает отсутствие влияния."
    else:
        title = STATUS_TITLES.get(view.status, STATUS_TITLES["FAILED"])
        status = view.summary or f"Статус: {view.status} ({view.reason_code})."
        if kind == "jira" and view.status in ("USEFUL", "PARTIAL"):
            status += " Это предварительный вывод по задаче до появления кода; он не доказывает поломку."
    affected = []
    for item in view.affected:
        # A named team is an addressee, not an approver; unknown stays unknown.
        if item["owner_status"] == "KNOWN":
            team = f"команда {item['teams'][0]} (источник: {item['owner_source']})"
        elif item["owner_status"] == "CONFLICT":
            team = f"владелец спорный: {', '.join(item['teams'])} (источник: {item['owner_source']})"
        else:
            team = "команда не определена"
        affected.append(f"{item['service']}: {team}")
    paths = [f"Изменение {d}" for d in view.deltas] + [f"Находка {f}" for f in view.findings]
    paths += [f"{CLAIM_LABELS[c['kind']]}: {c['statement']} Применимость: {c['applicability'].rstrip('.')}. "
             f"Неопределённость: {c['uncertainty']}. Основания: {_evidence(c['evidence'])}" for c in view.claims]
    paths += [f"Путь: {p['description']}. Основания: {_evidence(p['evidence'])}" for p in view.paths]
    unknowns = list(view.unknowns) + [f"Пробел входных данных: {g}" for g in gaps]
    unknowns += [f"{f['source']}: {f['status']}" + (f", проверено {f['checked_at']}" if f["checked_at"] else "")
                 for f in view.freshness]
    versions = _versions(snapshot, kind, generation)
    versions += [f"{k}: {v}" for k, v in sorted(view.versions.items()) if k != "snapshots"]
    versions += [f"снимок {repo}: {sha[:12]}" for repo, sha in sorted(view.versions.get("snapshots", {}).items())]
    if not view.compatible:
        affected, paths = [], []
    checks = list(view.checks)
    if view.compatible and view.status == "ABSTAINED":
        # An empty section reads as missing data; say what the abstention means instead.
        affected = affected or [f"Потребители не названы ({view.reason_code}). "
                                "Это не доказывает отсутствие влияния."]
        paths = paths or ["Путь влияния не построен."]
        checks = checks or ["Изменения вне поддерживаемого профиля сервис не классифицирует: "
                            "их проверяет обычный review."]
    versions.append(f"Статус: {view.status}, код: {view.reason_code}")
    sections = [{"title": "Что изменилось с прошлого вывода", "items": list(earlier)}] if earlier else []
    return {"title": title, "status_line": status, "sections": sections + [
        {"title": "Что может затронуть", "items": affected},
        {"title": "Почему и через какой путь", "items": paths},
        {"title": "Что проверить", "items": checks},
        {"title": "Неизвестные и свежесть", "items": unknowns},
        {"title": "Версии", "items": versions},
    ]}


def stale_doc(*, snapshot: dict, kind: str, generation: int) -> dict:
    return {"title": "Предыдущий вывод устарел",
            "status_line": "Ресурс изменился после анализа. Идёт новый анализ; прежний вывод не относится к "
                           "текущей версии.",
            "sections": [{"title": "Версии", "items": _versions(snapshot, kind, generation)}]}


def failure_doc(*, reason_code: str, snapshot: dict, kind: str, generation: int) -> dict:
    # No attempt counts or timestamps: identical failures keep an identical digest and cause no new write.
    recovery = ("Проверьте настройки и права API; новый анализ возможен после исправления и изменения ресурса."
                if reason_code in {"provider_rejected", "invalid_analysis_request"} else
                "Сервис повторит его автоматически при следующей сверке или изменении.")
    return {"title": STATUS_TITLES["FAILED"],
            "status_line": f"Анализ не выполнен ({reason_code}). {recovery} "
                           "Отсутствие вывода не означает отсутствие влияния.",
            "sections": [{"title": "Версии", "items": _versions(snapshot, kind, generation)}]}


def doc_digest(doc: dict) -> str:
    return digest(doc)


class DirectorySink:
    """Dry-run backend: one JSON file per resource, same update semantics, no external write."""

    def __init__(self, root: Path, identity: str = "dry-run"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.bot_identity = identity

    def _path(self, rid: str) -> Path:
        return self.root / (digest(rid)[:24] + ".json")

    def _read(self, rid):
        path = self._path(rid)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def list_comments(self, rid):
        item = self._read(rid)
        return [self._comment(item)] if item else []

    def get_comment(self, rid, comment_id):
        item = self._read(rid)
        return self._comment(item) if item and item["id"] == comment_id else None

    def _comment(self, item):
        from .connectors.base import parse_marker

        return Comment(item["id"], self.bot_identity, *parse_marker(item["marker"]))

    def create_comment(self, rid, doc, marker):
        item = {"id": digest(rid)[:12], "resource_id": rid, "doc": doc, "marker": marker}
        self._path(rid).write_text(canonical(item), encoding="utf-8")
        return item["id"]

    def update_comment(self, rid, comment_id, doc, marker):
        self.create_comment(rid, doc, marker)


class Publisher:
    def __init__(self, store, connectors: dict, backends: dict, *, hook=None):
        self.store, self.connectors, self.backends = store, connectors, backends
        self.hook = hook or (lambda phase, item: None)

    def _locate(self, backend, resource, intent) -> Comment | None:
        mine = lambda c: c and c.author == backend.bot_identity and c.marker == intent["marker"]  # noqa: E731
        if resource["comment_id"]:
            comment = backend.get_comment(resource["resource_id"], resource["comment_id"])
            if mine(comment):
                return comment
            self.store.forget_comment(resource["resource_id"], resource["comment_id"])
        found = [c for c in backend.list_comments(resource["resource_id"]) if mine(c)]
        if len(found) > 1:
            self.store.note("duplicate_service_comments", resource["resource_id"], f"count={len(found)}")
        return found[0] if found else None

    def _failed(self, intent, exc, *, writing: bool) -> str:
        rid = intent["resource_id"]
        if isinstance(exc, AuthError):
            provider = intent["resource_id"].split(":")[0]
            self.store.note("connection_unauthorized", provider, f"{provider}:{exc.status}")
            self.store.block_intent(intent, "connection_unauthorized", AUTH_RETRY_SECONDS)
            return "blocked"
        if isinstance(exc, RateLimited):
            self.store.note("rate_limited", rid.split(":")[0], f"retry_after={exc.retry_after}")
            # 429 is an answer: this write did not happen.
            return self.store.intent_retry(intent, "rate_limited", delay=exc.retry_after,
                                           state="UNKNOWN" if intent["state"] == "UNKNOWN" else "PENDING")
        if isinstance(exc, (ServerError, TransportError)):
            # A write that ended in 5xx/timeout may have been applied.
            state = "UNKNOWN" if writing or intent["state"] == "UNKNOWN" else "PENDING"
            return self.store.intent_retry(intent, exc.code, delay=exc.retry_after, state=state)
        if isinstance(exc, NotFound):
            self.store.intent_final(intent, "FAILED", "resource_missing")
            return "failed"
        if isinstance(exc, ClientError):
            self.store.intent_final(intent, "FAILED", "provider_rejected")
            self.store.note("provider_rejected", rid, str(exc.status))
            return "failed"
        raise exc

    def publish(self, intent, *, ingest_snapshot) -> str:
        """Run one publication attempt. ``ingest_snapshot(snapshot, event_id)`` opens a generation."""
        rid = intent["resource_id"]
        provider = rid.split(":", 1)[0]
        connector, backend = self.connectors[provider], self.backends[provider]
        if not self.store.intent_is_current(intent):
            self.store.intent_final(intent, "SUPERSEDED", "generation_changed")
            return "superseded"
        # Freshness check against the provider immediately before writing.
        try:
            current = connector.fetch(rid)
        except (AuthError, RateLimited, ServerError, TransportError, ClientError) as exc:
            return self._failed(intent, exc, writing=False)
        if current.closed or current.version != intent["resource_version"]:
            ingest_snapshot(current, f"freshness:{intent['intent_id']}")
            self.store.intent_final(intent, "SUPERSEDED", "changed_before_send")
            return "superseded"
        doc = json.loads(intent["body"])
        marker = marker_line(intent["marker"], intent["body_digest"], intent["generation"])
        resource = self.store.resource(rid)
        self.hook("before_send", intent)
        try:
            existing = self._locate(backend, resource, intent)
        except (AuthError, RateLimited, ServerError, TransportError, ClientError, NotFound) as exc:
            return self._failed(intent, exc, writing=False)
        if existing and existing.digest == intent["body_digest"]:
            self.store.intent_delivered(intent, comment_id=existing.comment_id, comment_digest=existing.digest,
                                        wrote=False)
            return self._postsend(intent, connector, ingest_snapshot, "unchanged")
        if existing is None and resource["create_unknown_at"] is not None:
            # A create of ours is in doubt and listing may lag: wait once before creating.
            settle = self.store.limits.create_settle_seconds
            waited = self.store.clock() - resource["create_unknown_at"]
            if waited < settle:
                return self.store.intent_retry(intent, "awaiting_listing", delay=settle - waited,
                                               state=intent["state"])
            self.store.clear_create_unknown(rid)
        operation = "update" if existing else "create"
        if not self.store.mark_sending(intent, operation=operation,
                                       comment_id=existing.comment_id if existing else None):
            self.store.intent_final(intent, "SUPERSEDED", "generation_changed")
            return "superseded"
        sending = {**intent, "state": "SENDING"}
        try:
            self.hook("sending", sending)
            if existing:
                backend.update_comment(rid, existing.comment_id, doc, marker)
                comment_id = existing.comment_id
            else:
                comment_id = backend.create_comment(rid, doc, marker)
        except NotFound:
            # Our comment was deleted between lookup and update: look again next attempt.
            self.store.forget_comment(rid, existing.comment_id if existing else "")
            return self.store.intent_retry(intent, "comment_deleted", delay=0.0, state="UNKNOWN")
        except (AuthError, RateLimited, ServerError, TransportError, ClientError) as exc:
            return self._failed(sending, exc, writing=True)
        self.hook("after_send", sending)
        self.store.clear_notice("connection_unauthorized", provider)
        current_at_delivery = self.store.intent_delivered(sending, comment_id=comment_id,
                                                          comment_digest=intent["body_digest"], wrote=True)
        return self._postsend(intent, connector, ingest_snapshot,
                              "delivered" if current_at_delivery else "delivered_stale")

    def _postsend(self, intent, connector, ingest_snapshot, outcome):
        # External APIs provide no conditional write against a PR/issue version.
        # A racing write can be briefly visible. Persist a recheck if the read
        # fails; do not resend the already confirmed comment to check freshness.
        rid = intent["resource_id"]
        try:
            after = connector.fetch(rid)
        except (AuthError, RateLimited, ServerError, TransportError, ClientError, NotFound) as exc:
            self.store.note("postsend_check_failed", rid, exc.code)
            event_id = f"postsend:{intent['intent_id']}"
            self.store.add_event(EventEnvelope(provider=connector.provider, source="postsend", event_id=event_id,
                                              event_kind="reconcile", resource_id=rid,
                                              payload_digest=digest(event_id), received_at=self.store.clock()))
            return outcome
        self.store.clear_notice("postsend_check_failed", rid)
        if after.closed or after.version != intent["resource_version"]:
            ingest_snapshot(after, f"postsend:{intent['intent_id']}")
            return "delivered_stale"
        return outcome
