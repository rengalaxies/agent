"""Static viewer for demo.json: what a person sees in the PR and the Jira issue, step by step.

No scripts and no external assets, so the page opens from disk and in any artifact store.
"""
from __future__ import annotations

import html
from pathlib import Path
import re

STYLE = """
:root { --bg:#f6f7f9; --card:#fff; --ink:#1d2330; --muted:#5b6475; --line:#d9dde5; --accent:#1f5fbf;
        --ok:#1d7a46; --warn:#9a5b00; --bad:#b3261e; --code:#eef1f6; }
@media (prefers-color-scheme: dark) { :root { --bg:#14171c; --card:#1c2027; --ink:#e6e9ef; --muted:#9aa3b2;
        --line:#2e343e; --accent:#7fb0ff; --ok:#5fd08f; --warn:#f0b35a; --bad:#ff8a80; --code:#252a33; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width:1080px; margin:0 auto; padding:24px 16px 64px; }
h1 { font-size:24px; margin:0 0 4px; } h2 { font-size:19px; margin:32px 0 8px; }
.banner { border:1px solid var(--warn); border-radius:8px; padding:10px 14px; margin:12px 0 20px; }
.banner b { color:var(--warn); }
.meta { color:var(--muted); font-size:13px; }
.grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:8px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:14px 16px; }
.step { margin:18px 0; } .step > .head { display:flex; gap:10px; align-items:baseline; flex-wrap:wrap; }
.num { font-weight:700; color:var(--accent); }
.comment { border-left:3px solid var(--accent); padding:4px 0 4px 14px; margin:10px 0; overflow-wrap:anywhere; }
.comment h3 { font-size:16px; margin:4px 0 6px; } .comment ul { margin:4px 0 8px; padding-left:20px; }
.comment p { margin:6px 0; } .sec { font-weight:600; margin-top:10px; }
code { background:var(--code); padding:1px 4px; border-radius:4px; font-size:13px; }
.where { font-size:13px; color:var(--muted); }
.ok { color:var(--ok); font-weight:600; } .bad { color:var(--bad); font-weight:600; }
table { border-collapse:collapse; width:100%; font-size:14px; } td, th { border-bottom:1px solid var(--line);
        padding:6px 8px; text-align:left; vertical-align:top; }
details summary { cursor:pointer; color:var(--accent); }
a { color:var(--accent); }
"""

LEGEND = [
    ("Предварительный вывод", "Результат по задаче Jira до появления кода. Указывает, где искать, и не доказывает поломку."),
    ("Факт в пределах профиля", "Связь найдена в коде поддерживаемого HTTP/Python-профиля на закреплённом коммите."),
    ("Гипотеза", "Возможное следствие, которое сервис не проверял выполнением."),
    ("STALE / UNKNOWN", "Источник устарел или не прочитан. Вывод опирается на него с этой оговоркой."),
    ("PARTIAL / ABSTAINED", "Сервис дал часть ответа или воздержался и пишет почему."),
    ("Тесты не запускались", "Сервис не выполняет код потребителя. Что проверить, перечислено в разделе «Что проверить»."),
    ("Модель OFF", "Строка «Детерминированный результат»: модель не вызывалась."),
]


def _inline(text: str) -> str:
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    return re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", out)


def render_markdown(body: str) -> str:
    """The subset the service emits: ### title, **section**, - items, paragraphs, hidden marker."""
    parts, items = [], []

    def flush():
        if items:
            parts.append("<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>")
            items.clear()

    for line in body.splitlines():
        if not line.strip() or line.startswith("<!--"):
            flush()
        elif line.startswith("### "):
            flush()
            parts.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("- "):
            items.append(_inline(line[2:]))
        elif re.fullmatch(r"\*\*[^*]+\*\*", line.strip()):
            flush()
            parts.append(f'<div class="sec">{_inline(line.strip()[2:-2])}</div>')
        else:
            flush()
            parts.append(f"<p>{_inline(line)}</p>")
    flush()
    return "".join(parts)


SECTIONS = {"Что изменилось с прошлого вывода", "Что может затронуть", "Почему и через какой путь", "Что проверить",
            "Неизвестные и свежесть", "Версии"}


def render_text(body: str) -> str:
    """Jira comment as plain text (ADF): first line is the title, known lines are section headings."""
    lines = [line for line in body.splitlines() if line.strip() and not line.startswith("agent-service marker=")]
    parts = [f"<h3>{_inline(lines[0])}</h3>"] if lines else []
    for line in lines[1:]:
        parts.append(f'<div class="sec">{_inline(line)}</div>' if line in SECTIONS else f"<p>{_inline(line)}</p>")
    return "".join(parts)


def _changed(steps, index, resource, comment) -> str:
    if index == 0:
        return "новый"
    before = {c["id"]: c["body"] for c in steps[index - 1]["comments"].get(resource, [])}
    if comment["id"] not in before:
        return "новый"
    return "тот же комментарий, текст обновлён" if before[comment["id"]] != comment["body"] else "без изменений"


def write_site(report: dict, directory: Path):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    steps = report["steps"]
    (directory / "graph.html").write_text(steps[-1]["graph_html"], encoding="utf-8")
    commits = report["sources"]["commits"]
    rows = "".join(f"<tr><td>{html.escape(repo)}</td><td>{html.escape(branch)}</td><td><code>{sha[:12]}</code></td></tr>"
                   for repo, branches in commits.items() for branch, sha in branches.items())
    checks = "".join(f'<tr><td>{html.escape(c["check"])}</td><td class="{"ok" if c["ok"] else "bad"}">'
                     f'{"PASS" if c["ok"] else "FAIL"}</td></tr>' for c in report["checks"])
    legend = "".join(f"<tr><td><b>{html.escape(k)}</b></td><td>{html.escape(v)}</td></tr>" for k, v in LEGEND)
    blocks = []
    for index, step in enumerate(steps):
        event = step.get("event") or {}
        shown = []
        for resource, comments in step["comments"].items():
            for comment in comments:
                state = _changed(steps, index, resource, comment)
                if state == "без изменений" and step["key"] != "restart":
                    continue
                kind = "Jira" if "#" not in resource else "GitHub PR"
                body = render_text(comment["body"]) if kind == "Jira" else render_markdown(comment["body"])
                shown.append(f'<div class="where">{kind} {html.escape(resource)} · комментарий '
                              f'<code>{html.escape(comment["id"])}</code> · {state}</div>'
                              + (f'<div class="comment">{body}</div>' if state != "без изменений" else ""))
        evt = html.escape(", ".join(f"{k}={v}" for k, v in event.items() if k != "result")
                          + (f", result={event['result']}" if "result" in event else ""))
        blocks.append(f'<section class="card step"><div class="head"><span class="num">{index + 1}</span>'
                      f'<b>{html.escape(step["title"])}</b><span class="meta">{html.escape(step["at"])}</span></div>'
                      f'<p>{html.escape(step["action"])}</p><div class="meta">Событие: {evt}</div>'
                      + "".join(shown) + "</section>")
    page = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pilot local demo</title><style>{STYLE}</style></head><body><main>
<h1>Влияние изменения: локальный показ сервиса</h1>
<div class="meta">code <code>{html.escape(report["code_version"][:12])}</code> · profile
<code>{html.escape(report["profile"])}</code> · model {html.escape(report["model"])} · status
<span class="{"ok" if report["status"] == "PASS" else "bad"}">{html.escape(report["status"])}</span></div>
<div class="banner"><b>LOCAL, не LIVE.</b> Код сервиса, очередь, анализатор, приёмник webhook и SQLite настоящие.
GitHub и Jira заменены локальными стендами на 127.0.0.1. Исходники Orders/Reporting авторские, это не независимый
проект и не измерение пользы. Модель не вызывалась.</div>
<h2>Как читать комментарий</h2><div class="card"><table>{legend}</table></div>
<h2>Сценарий</h2>{"".join(blocks)}
<h2>Проверки сценария</h2><div class="card"><table>{checks}</table></div>
<h2>Источники</h2><div class="card"><table><tr><th>repository</th><th>branch</th><th>commit</th></tr>{rows}</table>
<p class="meta">Генератор: {html.escape(report["sources"]["generator"])}. Записей истории в state:
{report["history_entries"]}. Python {html.escape(report["python"])}.</p>
<p><a href="graph.html">Граф зависимостей после сценария</a> (та же страница, что отдаёт <code>/graph</code>).</p></div>
</main></body></html>
"""
    (directory / "index.html").write_text(page, encoding="utf-8")
