"""Read-only human view of the graph: impact paths, origins, freshness, owners.

One self-contained HTML page per environment, built from a grant-scoped
GraphQuery, so it shows exactly what the reader may see. No scripts, no external
assets, every value escaped. make_app() serves it over WSGI with an environment
filter and no caching. It is a viewer, not an editor.
"""
from __future__ import annotations

from html import escape
from urllib.parse import parse_qs, quote

from .contracts import GraphError
from .graph_query import GraphQuery

STATUS = {"ACTIVE": "действует", "STALE": "устарело", "CONFLICT": "конфликт", "RETRACTED": "снято"}
FRESH = {"CURRENT": "свежее", "STALE": "устарело", "UNKNOWN": "неизвестно"}
ORIGIN = {"code": "код", "runtime": "runtime", "ownership": "владение"}
REASON = {
    "source_unavailable": "источник недоступен", "age_exceeded": "истёк срок свежести",
    "window_gap": "разрыв окна наблюдения", "sampled_source": "sampling", "partial_coverage": "неполное покрытие",
    "worktree_not_reproducible": "рабочая копия, не закреплённый commit", "basis_changed": "основание изменилось",
    "code_removed": "код удалён", "code_changed": "фрагмент изменился", "code_moved": "вызов перенесён",
    "target_not_declared": "операция больше не объявлена", "ownership_changed": "владелец сменился",
    "route_conflict": "runtime видит другой маршрут этой пары", "runtime_after_removal":
    "трафик после удаления из кода",
}
CSS = """body{font:14px/1.45 system-ui,sans-serif;margin:16px;max-width:1100px;color:#1d1d1f;background:#fff}
h1{font-size:20px}h2{font-size:17px;margin-top:28px}h3{font-size:15px;margin:18px 0 6px}
table{border-collapse:collapse;width:100%;margin:6px 0}td,th{border:1px solid #ddd;padding:4px 6px;
text-align:left;vertical-align:top}th{background:#f5f5f7}.b{display:inline-block;padding:0 6px;border-radius:8px;
background:#eef;margin-right:4px}.warn{color:#a40}.muted{color:#666}nav a{margin-right:10px}
@media (prefers-color-scheme:dark){body{background:#111;color:#eee}th{background:#222}td,th{border-color:#444}
.b{background:#334}.muted{color:#aaa}.warn{color:#f96}}"""


def _e(value):
    return escape("" if value is None else str(value), quote=True)


def owner_text(owner):
    if owner["status"] == "KNOWN":
        return _e(owner["teams"][0]["team"]) + f' <span class="muted">({_e(owner["source"])})</span>'
    if owner["status"] == "CONFLICT":
        return '<span class="warn">конфликт владельцев: ' + _e(", ".join(t["team"] for t in owner["teams"])) + "</span>"
    return '<span class="warn">команда не определена</span>'


def freshness_text(freshness):
    reasons = ", ".join(REASON.get(r, r) for r in freshness["reasons"])
    cls = "" if freshness["status"] == "CURRENT" else ' class="warn"'
    return f'<span{cls}>{_e(FRESH[freshness["status"]])}</span>' + (f' <span class="muted">({_e(reasons)})</span>'
                                                                     if reasons else "")


def basis_text(b, source_links):
    if b["origin"] == "code":
        where = f'{b["repository"]}/{b["path"]}:{b["start_line"]}'
        symbol = b.get("callsite", {}).get("symbol")
        text = _e(where) + (f' ({_e(symbol)})' if symbol else "") + (
            f' @{_e(b["commit"][:12])}' if b.get("commit") else ' <span class="muted">рабочая копия</span>')
        template = (source_links or {}).get(b["repository"])
        if template and b.get("commit") and template.startswith(("https://", "http://")):
            url = template.format(repository=quote(b["repository"]), commit=quote(b["commit"]),
                                  path=quote(b["path"]), line=b["start_line"])
            text = f'<a href="{_e(url)}" rel="noreferrer">{text}</a>'
        return '<span class="b">код</span>' + text
    if b["origin"] == "runtime":
        a = b["aggregates"]
        route = f' {b["method"]} {b["route"]}' if b.get("route") else " (без маршрута)"
        count = f'запросов: {a["request_count"]}' + (f', оценка {a["estimated_request_count"]}'
                                                    if "estimated_request_count" in a else "")
        return ('<span class="b">runtime</span>' + _e(f'{b["source"]}{route}, окно {b["window"]["start"]}'
                                                       f' .. {b["window"]["end"]}, {count}'))
    return '<span class="b">владение</span>' + _e(f'{b["team"]} ({b["source"]} {b["source_version"]})')


def history_text(b):
    reason = REASON.get(b["closed_reason"], b["closed_reason"])
    return _e(f'{ORIGIN[b["origin"]]}: закрыто в версии {b["closed_version"]}, {reason}')


def render_html(query: GraphQuery, *, environments=(), source_links=None):
    q = query
    out = [f"<!doctype html><html lang=ru><head><meta charset=utf-8>"
           f"<meta name=viewport content='width=device-width,initial-scale=1'>"
           f"<title>Граф зависимостей</title><style>{CSS}</style></head><body>",
           f"<h1>Граф зависимостей: {_e(q.installation_id)} / {_e(q.environment)}</h1>"]
    if environments:
        out.append("<nav>Окружение: " + "".join(
            f'<a href="?environment={_e(quote(env))}">{"<b>" + _e(env) + "</b>" if env == q.environment else _e(env)}</a>'
            for env in environments) + "</nav>")
    s = q.summary()
    out.append(f'<p class="muted">Версия графа {_e(s["graph_version"])}. Связей: {s["relationships"]}, '
               f'активных оснований: {s["active_bases"]}, закрытых: {s["closed_bases"]}. '
               f'Показано только то, что разрешено текущими правами.</p>')
    out.append("<h2>Источники</h2><table><tr><th>Тип</th><th>Источник</th><th>Состояние</th><th>Версия</th>"
               "<th>Проверено</th><th>Свежесть</th></tr>")
    for src in q.source_freshness():
        out.append(f'<tr><td>{_e(src["source_kind"])}</td><td>{_e(src["source_id"])}</td><td>{_e(src["status"])}</td>'
                   f'<td>{_e((src["source_version"] or "")[:12] if src["source_kind"] == "git" else src["source_version"])}</td><td>{_e(src["freshness"]["checked_at"])}</td>'
                   f'<td>{freshness_text(src["freshness"])}</td></tr>')
    out.append("</table><h2>Операции и кто от них зависит</h2>")
    operations = sorted((e for e in q._entities.items() if e[1]["kind"] == "operation"),
                        key=lambda kv: (kv[1]["service"], kv[1]["route"], kv[1]["method"]))
    for op_id, op in operations:
        out.append(f'<h3>{_e(op["service"])} {_e(op["method"])} {_e(op["route"])}</h3>'
                   f'<p>Владелец {_e(op["service"])}: {owner_text(q.owner(op["service"]))}</p>')
        for rel in (r for r in q._rels.values() if r["kind"] == "declares" and r["target"] == op_id):
            declared = q.relationship(rel["id"])
            lines = [basis_text(b, source_links) for b in declared["bases"]]
            lines += [f'<span class="muted">{history_text(b)}</span>' for b in declared["history"]]
            out.append(f'<p>Объявление ({_e(STATUS[declared["status"]])}): ' + "<br>".join(lines) + "</p>")
        impact = q.impact(op_id, depth=2, limit=50)
        if not impact["paths"]:
            out.append('<p class="muted">Потребители не найдены в разрешённых источниках. '
                       'Это не доказывает их отсутствия.</p>')
            continue
        out.append("<table><tr><th>Путь влияния</th><th>Статус</th><th>Свежесть</th><th>Команда потребителя</th>"
                   "<th>Основания</th></tr>")
        for path in impact["paths"]:
            rel = impact["relationships"][path["relationship_refs"][-1]]
            bases = "<br>".join(basis_text(b, source_links) for b in rel["bases"])
            history = q.relationship(rel["id"])["history"]
            if history:
                bases += "<br>" + "<br>".join(f'<span class="muted">{history_text(b)}</span>' for b in history)
            conflicts = "".join(f'<br><span class="warn">{_e(REASON.get(c["code"], c["code"]))}</span>'
                                for c in rel["conflicts"])
            level = ' <span class="muted">(уровень сервиса, маршрут неизвестен)</span>' if path["service_level"] else ""
            out.append(f'<tr><td>{_e(path["summary"])}{level}</td><td>{_e(STATUS[rel["status"]])}{conflicts}</td>'
                       f'<td>{freshness_text(rel["freshness"])}</td>'
                       f'<td>{owner_text(q.owner(path["consumer"]))}</td><td>{bases}</td></tr>')
        out.append("</table>")
    # Pairs where no route is known at all; a pair with an operation edge is shown above.
    precise = {(q._entities[r["source"]]["service"], q._entities[r["target"]]["service"])
               for r in q._rels.values() if r["kind"] == "calls" and q._entities[r["target"]]["kind"] == "operation"}
    service_level = [r for r in q._rels.values() if r["kind"] == "calls"
                     and q._entities[r["target"]]["kind"] == "service"
                     and (q._entities[r["source"]]["service"], q._entities[r["target"]]["service"]) not in precise]
    if service_level:
        out.append("<h2>Вызовы без маршрута (только runtime)</h2><ul>")
        for r in sorted(service_level, key=lambda r: r["id"]):
            view = q.relationship(r["id"], history=False)
            out.append(f'<li>{_e(view["source"]["service"])} → {_e(view["target"]["service"])}: '
                       f'{freshness_text(view["freshness"])}. Это не зависимость от конкретной операции.</li>')
        out.append("</ul>")
    out.append("</body></html>")
    return "\n".join(out)


def make_app(query_for, environments, *, source_links=None):
    """WSGI app. query_for(environment) -> GraphQuery for the current reader's grants."""
    environments = list(environments)

    def app(environ, start_response):
        headers = [("Content-Type", "text/html; charset=utf-8"), ("Cache-Control", "no-store"),
                   ("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'"),
                   ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer")]
        if environ.get("REQUEST_METHOD", "GET") != "GET":
            start_response("405 Method Not Allowed", headers)
            return [b"read-only"]
        if environ.get("PATH_INFO", "/") not in ("", "/"):
            start_response("404 Not Found", headers)
            return [b"not found"]
        env = parse_qs(environ.get("QUERY_STRING", "")).get("environment", [environments[0]])[0]
        if env not in environments:
            start_response("404 Not Found", headers)
            return [b"unknown environment"]
        try:
            body = render_html(query_for(env), environments=environments, source_links=source_links)
        except GraphError as exc:
            start_response("403 Forbidden" if exc.code == "forbidden" else "500 Internal Server Error", headers)
            return [exc.code.encode()]
        start_response("200 OK", headers)
        return [body.encode("utf-8")]
    return app
