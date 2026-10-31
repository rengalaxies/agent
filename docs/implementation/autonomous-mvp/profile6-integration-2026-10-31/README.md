# Интеграция profile6 — 31.10.2026

По поручению владельца текущий исполнитель выполнил техническую проверку вместо
отдельного чата M3. Согласование зафиксировано в описании [#81](https://github.com/rengalaxies/agent/pull/81).
Это агентная проверка, не независимый человеческий approval GitHub.

## Точная поставка кода

- Исходный main: `8b9eb0e4f940ac0a6cfa2df58f0450dcd967de7a`.
- Проверенный head #81: `e217599c49b2d053faf6290742fc8d746b92d277`.
- Tree: `55ef17c631a3e5fdf20a2193c21620d19d6f4319`.
- Merge main: `5f60a0fb88369f1e1e7da00b960f6b6ed462c614`, дерево в точности совпало.
- #72 head `f25e82f9a83f4e15bdfeb16088fdf1fc6d335bee` входит в историю #81;
  GitHub автоматически отметил #72 merged. Дополнительного merge #72 нет.
- Profile6, публичные схемы и SQLite schema прежние. ВМ/pin/installer не изменялись.

## Повторные проверки текущего исполнителя

1. Чтение полного product diff между актуальным main и кандидатом: intent,
   bindings/provider guards, context/knowledge/code basis freshness и история.
2. 48 targeted tests PASS без skips: M4-A intent/providers/scenarios, mutation,
   source upgrade, demo profile, очередь и публикационные переходы.
3. 6 boundary cases PASS (пять DEFERRED_72 плюс контроль смешанного отрицания).
4. HTTP oracle matrix PASS: supported FP=0/FN=0 на авторском корпусе,
   runtime wrapper FN=1 сохранён как unsupported abstention. Не клиентский benchmark.
5. Отдельные old/new процессы 4→6→4→6 PASS: source unavailable, partial upgrade
   после ANALYZED, fresh head, re-upgrade. Те же три IDs комментариев и история.
6. Все jobs семи Actions run точного head completed/success: Core, P1, HTTP,
   box/systemd, evidence, workflow checks, offline qualifier.

Первый локальный запуск: 48 tests, errors=8, skipped=4 из-за отсутствующих optional
API dependencies; не PASS. После установки runtime hash-lock и oracle httpx 0.28.1 /
PyYAML 6.0.3 повтор выше прошёл. Полный Core/runner/Docker/systemd здесь заново
не исполнялись: для них сверены CI exact head, без переноса утверждения на целевую ВМ.

[Targeted log](targeted.log) · [Boundary observations](boundaries.json) ·
[HTTP observations](http-observations.json) · [Migration summary](migration-summary.json).

## Граница согласования и откат

Согласован код будущей поставки. Новый release не опубликован, pin остаётся прежним.
Исследован tools/agent_service/box/cli.py: rollback проверяет совместимость схемы;
при ok оставляет новый state (release_only), затем activate запускает старый процесс.
Это не профильная проверка совместимости. Поэтому команда rollback и предварительный
stop сами по себе не реализуют обещание «держать публикацию остановленной».

Не выполнять code-only downgrade profile6→release14e на новом state. Нужна отдельная
квалификация процедуры восстановления соответствующего pre-update backup до запуска
старого writer, с контролем публикации, новых внешних событий и сверки комментариев.
Не считать 4→6→4→6 на loopback стенде проверкой этой installer-процедуры или release14e.
Документы не являются обходом отсутствующего механизма блокировки публикации.

Обновление может быть подготовлено без ВМ, но recovery-квалификация остаётся обязательной
до установки. Смена кода на main не подтверждает наличие нового опубликованного asset.
DB/API не атомарны, окно устаревания при outage не имеет доказанного SLA.

## Что дальше

| Работа | Без ВМ | Критерий |
|---|---|---|
| Квалификация rollback на точных старом/новом releases | да, локально/CI | matching backup до старта старого writer, контроль публикации, сбои и восстановление |
| Новый release из принятого main | да | build twice, published asset download/hash/manifest/install-published |
| Разрешение конфликта #71 | да, оператор M3 | сохранены stopped-host/support и актуальная история |
| Пользовательская сессия | да | реальные наблюдения разработчика по PARTICIPANT-SESSION |
| Установка и target recovery | нет | доверенный хост, backup, loaded SHA, restart/reboot/restore/rollback |
| Настоящие App/Jira/webhooks | работающий сервис | HTTPS, credentials, согласованные внешние ресурсы, LIVE acceptance |

MODEL OFF. Participant/client/target VM/external integrations NOT_RUN.
