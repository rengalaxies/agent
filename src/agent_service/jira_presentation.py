"""Russian Jira presentation; the full analysis document remains in the outbox."""

from __future__ import annotations

import re

REASONS = {
    "no_supported_delta": "В текущей версии не найдено изменений, для которых анализатор может оценить влияние на другие сервисы.",
    "intent_unclear": "Недостаточно данных, чтобы однозначно определить сервис или операцию в задаче.",
    "insufficient_evidence": "Недостаточно оснований для вывода о влиянии.",
    "no_consumer_found_within_profile": "В доступном коде не найдены потребители рассматриваемой операции.",
    "out_of_scope": "Изменение находится за пределами доступной области анализа.",
    "hypotheses_only": "Есть только предположения о влиянии; подтверждённой связи пока нет.",
    "source_stale": "Часть источников устарела: вывод неполный и требует перепроверки.",
    "coverage_gaps": "Анализ выполнен не полностью: часть кода или связей не удалось проверить.",
    "runtime_unavailable": "Данные наблюдаемых вызовов недоступны; вывод ограничен другими источниками.",
    "model_unavailable": "Дополнительный модельный анализ недоступен; его выводы не использованы.",
    "owner_unknown": "Возможное влияние найдено, но ответственный за потребителя не определён.",
    "unclassified_change": "Изменение обнаружено, но его поведение не удалось классифицировать.",
}


def _unique(items):
    return list(dict.fromkeys(items))


def russian_check(consumer: str, text: str) -> str:
    preliminary = re.fullmatch(
        r"Before the change lands, check how (\S+) uses (.+?)(?: against requirement (\S+) \(([^)]+)\)\.|; whether it needs the complete collection is not known\.)",
        text,
    )
    if preliminary:
        who, where, requirement, predicate = preliminary.groups()
        where = where.replace(" at ", ", вызов: ")
        result = f"До изменения проверьте, как {who} использует {where}."
        if requirement:
            condition = {
                "complete_collection": "полнота набора данных",
                "first_page_only": "только первая страница",
            }.get(predicate, predicate)
            result += f" Сверьте требование {requirement} ({condition})."
        else:
            result += " Неизвестно, нужен ли потребителю полный набор данных."
        return result
    runtime = re.fullmatch(
        r"Find how (\S+) calls (.+): only runtime calls show it( and they are stale)?; ask its owner or locate its call site\.",
        text,
    )
    if runtime:
        who, route, stale = runtime.groups()
        return (
            f"Уточните у владельца {who} или найдите в коде вызов {route}: "
            "связь известна только по наблюдаемым запросам."
            + (" Эти наблюдения устарели." if stale else "")
        )
    page_check = re.fullmatch(
        r"Run consumer with more than (\d+) records; compare full expected set, page traversal and explicit limits",
        text,
    )
    if page_check:
        return (
            f"{consumer}: выполните проверку на наборе больше {page_check[1]} записей; "
            "сравните полный ожидаемый набор, обход страниц и явные ограничения."
        )
    if (
        text
        == "Exercise the changed operation against this consumer's independent expectations"
    ):
        return f"{consumer}: проверьте изменённую операцию на независимых ожиданиях потребителя."
    # Arbitrary source-authored guidance is quoted, never silently dropped or
    # guessed by an unqualified translator/model. Built-in prose is Russian.
    return (
        f"{consumer}: {text}"
        if any("а" <= c.lower() <= "я" for c in text)
        else f"{consumer}: рекомендация источника — «{text}»"
    )


def summary_doc(view, raw: dict, *, kind: str, gaps, earlier) -> dict:
    """Called only after result/request validation; never parses rendered prose."""
    if not view.compatible:
        return {
            "title": "Результат анализа не показан",
            "status_line": "Результат не прошёл проверку совместимости. Это не означает отсутствие влияния.",
            "sections": [
                {
                    "title": "Что проверить",
                    "items": [
                        "Проверьте версию и настройки сервиса перед повторным анализом."
                    ],
                }
            ],
        }
    title = {
        "USEFUL": "Возможное влияние на другие сервисы",
        "PARTIAL": "Вывод о влиянии неполный",
        "ABSTAINED": "Результат анализа изменений",
        "FAILED": "Анализ не выполнен",
    }.get(view.status, "Результат анализа требует проверки")
    summary = REASONS.get(view.reason_code)
    if summary is None:
        summary = (
            "Найдены потребители, которые могут зависеть от изменяемой операции."
            if view.status in {"USEFUL", "PARTIAL"}
            else "Надёжный вывод о влиянии получить не удалось. Проверьте доступность источников и настройки анализа."
        )
    if kind == "jira":
        summary += " Это предварительный вывод по задаче, до проверки изменения кода."
    affected, reasons, checks, limits = [], [], [], []
    for item in view.affected:
        owner = (
            f"команда {', '.join(item['teams'])}"
            if item["owner_status"] == "KNOWN"
            else "ответственный не определён"
            if item["owner_status"] == "UNKNOWN"
            else "ответственный указан неоднозначно: " + ", ".join(item["teams"])
        )
        affected.append(f"{item['service']}: {owner}.")
    for delta in raw.get("deltas", []):
        op = delta["operation"]
        name = f"{op['service']} {op['method']} {op['route']}"
        if delta["code"] == "OPERATION_REMOVED":
            reasons.append(f"В изменении удалена операция {name}.")
        elif delta["code"] == "PAGE_DEFAULT_CHANGED":
            reasons.append(
                f"У {name} размер страницы по умолчанию изменён: {delta['before']} → {delta['after']}."
            )
        else:
            reasons.append(
                f"Обнаружено изменение {name}; его поведение требует отдельной проверки."
            )
    for finding in raw.get("findings", []):
        consumer = finding["consumer"]["service"]
        call = finding["callsite"]
        reasons.append(
            f"Потребитель {consumer}: вызов в {call['repository']}:{call['path']}:{call['line']}."
        )
        if finding["code"] == "OPERATION_REMOVED":
            checks.append(
                f"Сохраните прежний маршрут или обновите вызов в {consumer}; затем проверьте совместимость."
            )
        elif finding["code"] == "POSSIBLE_TRUNCATION":
            checks.append(f"Проверьте пагинацию и полноту данных у {consumer}.")
        else:
            checks.append(f"Повторно проверьте контракт вызова у {consumer}.")
    relationships = {item["id"]: item for item in raw.get("relationships", [])}
    evidence = {item["id"]: item for item in raw.get("evidence", [])}
    for path in raw.get("impact_paths", []):
        for ref in path["relationship_refs"]:
            rel = relationships[ref]
            if rel["kind"] == "calls":
                target = rel["target"]
                source_name = rel["source"].get("service", "неуточнённый потребитель")
                target_name = target.get("service", "неуточнённый сервис")
                route = (
                    f" {target['method']} {target['route']}"
                    if "method" in target and "route" in target
                    else " (точный маршрут не определён)"
                )
                reasons.append(f"Связь: {source_name} → {target_name}{route}.")
                for evidence_ref in rel.get("evidence_refs", []):
                    item = evidence[evidence_ref]
                    if item["origin"] == "code":
                        reasons.append(
                            f"Основание в коде: {item['repository']}:{item['path']}:{item['start_line']}."
                        )
    for check in raw.get("checks", []):
        checks.append(russian_check(check["consumer"]["service"], check["text"]))
    if view.status == "ABSTAINED":
        checks.append(
            "Обычное ревью остаётся необходимым: отсутствие находок не гарантирует совместимость."
        )
    if view.status == "PARTIAL":
        limits.append("Вывод неполный: часть оснований или проверок недоступна.")
    if gaps or any(
        "unmapped_call" in x or "helper_semantics_unknown" in x for x in view.unknowns
    ):
        limits.append(
            "Не все вызовы и их поведение удалось сопоставить; часть влияния может быть пропущена."
        )
    if any("requirement_unknown" in x for x in view.unknowns):
        limits.append(
            "Ожидания потребителя не подтверждены; документационный контекст сам по себе их не доказывает."
        )
    known = (
        "unmapped_call",
        "helper_semantics_unknown",
        "requirement_unknown",
        "owner_unknown",
        "jira_without_diff",
    )
    if any(not any(code in x for code in known) for x in view.unknowns):
        limits.append(
            "Есть дополнительные неопределённости; полный перечень сохранён в данных анализа."
        )
    for source in view.freshness:
        if source["status"] != "CURRENT":
            limits.append(
                f"Источник {source['source']} устарел или недоступен; его данные требуют перепроверки."
            )
    if not any(f.get("test_executed") for f in raw.get("findings", [])):
        limits.append("Интеграционные тесты в рамках этого анализа не запускались.")
    sections = []
    if earlier:
        sections.append(
            {
                "title": "Что изменилось",
                "items": [
                    "Часть прежних предупреждений в этой версии больше не обнаружена. Это не заменяет проверку совместимости."
                ],
            }
        )
    for heading, items in [
        ("Что может затронуть", affected),
        ("Почему и через какой путь", reasons),
        ("Что проверить", checks),
        ("Ограничения", limits),
    ]:
        items = _unique(items)
        if items:
            # Bound the visible presentation without losing the full audit data.
            shown = items[:5]
            if len(items) > 5:
                shown.append(
                    f"Ещё {len(items) - 5} пунктов сохранены в полном результате анализа."
                )
            sections.append({"title": heading, "items": shown})
    return {"title": title, "status_line": summary, "sections": sections}


def documentation_summary(doc: dict, pages: list[dict]) -> dict:
    result = {
        **doc,
        "sections": [s for s in doc["sections"] if s["title"] != "Документация"],
    }
    items = []
    for page in pages:
        if page.get("status") == "UNAVAILABLE":
            items.append(
                f"Страница Confluence недоступна: {page['url']}. Её текст не использован."
            )
        else:
            items.append(f"{page['title']} — версия {page['version']}: {page['url']}")
            if page["truncated"] or page["unsupported_blocks"]:
                items.append(
                    "Страница прочитана не полностью: есть обрезка или неподдерживаемые блоки."
                )
    if items:
        items.append("Соответствие кода требованиям отдельно не проверялось.")
        result["sections"].append({"title": "Документация", "items": items})
    return result
