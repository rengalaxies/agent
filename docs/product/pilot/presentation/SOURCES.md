# Приложение: источники и подтверждения ключевых утверждений

Редакция 24.10.2026. Дополняет [CLAIMS.md](CLAIMS.md): там статус и правило
использования каждого утверждения, здесь где лежит источник и как самому
проверить число со слайда.

## Состояние источников

| Источник | Путь | Состояние на 24.10.2026 | Как использован |
|---|---|---|---|
| Предложение пилота, протокол, решения, экономика, backlog | `docs/product/pilot/` | Ветка `docs/pilot-proposal` (`0fab62a`), PR #47 открыт. Решения D1-D17 в статусе "Предложено", пересмотр владельцем 27.10.2026 | Основа рассказа, содержание пилота, критерии. Подаётся как предложение, не как утверждённое решение |
| Отчёт установки HTTP-демо и скриншоты | `docs/agent-graph-demo/deployments/2026-10-22/` | `main`, PR #38 | Цифры 250/100/250, экраны слайдов 6, 7, П4 |
| Аудит интеграции PR | `docs/audits/pr-integration/` | `main`, PR #43 | Сила свидетельств, F1, F2, F7, L1, L5, L8 |
| Отчёт модельной серии, пачка 1 | `experiments/evidence_refs_v2/runs/2026-10-22-batch1/` | `main`, PR #35 | Слайд 9, П5 |
| Технический аудит архитектуры | `docs/audits/architecture/` | Ветка `docs/architecture-audit` (`d7ee647`), PR #44 открыт | Замеры скорости и шума, ADR-004, ADR-007 |
| UX-аудит | `docs/audits/ux/` | В удалённом репозитории отсутствует (по EVIDENCE.md это незакоммиченная работа ветки `feat/demo-decision-path`) | Только вывод I3 в пересказе EVIDENCE.md, со статусом "гипотеза" |
| Исследование Ontonet | `docs/research/ontonet/` | Не опубликовано (по EVIDENCE.md ветка `docs/ontonet-research`) | Только выводы I1, I2, I5 в пересказе EVIDENCE.md, со статусом "гипотеза" |
| Код ядра | `src/agent_graph/discovery.py`, `src/agent_graph/engine.py` | `main` `8f010cf` | Границы распознавания (C25-C27) |

Сами UX-аудит и исследование Ontonet при подготовке не читались. Если их
выводы отличаются от пересказа в EVIDENCE.md, слайды 3, 10 и 11 нужно
сверить заново.

## Подтверждения чисел со слайдов

| Число на слайде | Слайд | Где подтверждается | Как проверить |
|---|---|---|---|
| Reporting 250 / 100 / 250 / 250 по версиям A, B, D, E | 5, П4 | DEPLOY README, таблица "Реальная приёмка целевой ВМ"; `target-report.json`, поле `shows` | Открыть `target-report.json`, поле `shows`: receipts версий A, B, D, E в каждом показе |
| 5 полных показов, 20 проверок | 8, П4 | DEPLOY README, тот же раздел | `python -c "import json;d=json.load(open('docs/agent-graph-demo/deployments/2026-10-22/target-report.json',encoding='utf-8'));print(d['sequential_full_shows'])"` печатает 5 |
| 0 вызовов модели в показе | 8 | DEPLOY README "Негативные проверки"; `target-report.json`, поле `model_calls` | Там же, `model_calls` |
| `reporting/client.py`, строка 5, снимок B | 5, 6 | `target-desktop-B.png`, панель "На чём основана связь" | Открыть исходный скриншот |
| Запуск записан как наблюдение оператора | 6, П4 | DEPLOY README: `origin=operator_runner`, `independently_verified=false`; FINDINGS F2 | `grep -n independently_verified docs/agent-graph-demo/deployments/2026-10-22/README.md` |
| Новый потребитель не считается изменением | 7 | FINDINGS L5 | `grep -n "L5" docs/audits/pr-integration/FINDINGS.md` |
| Нелитеральный default даёт RECHECK вместо тишины | 8 | FINDINGS F1, вывод `repro_page_default.py` до и после `5d7ee0f` | `python docs/audits/pr-integration/repro_page_default.py` (Linux) |
| 3,2 с на 1000 файлов, 28 с на 9000 | 8, П6 | ARCH MEASUREMENTS §2, столбец `analyze_change`: 3,18 и 28,48 | `git show origin/docs/architecture-audit:docs/audits/architecture/MEASUREMENTS.md` |
| 3120 из 3181, 4163 из 4190, связей 0 | 10, П6 | ARCH MEASUREMENTS §4 | Там же |
| 2 из 6 полных циклов, GPT OSS 2/3, Qwen 0/3, decoy не завершён | 9, П5 | BATCH1 README, таблица "Раздельная оценка шести результатов" | `python analyze_batch1.py report.json manifest.json final-ledger.json pricing.json --output /tmp/a.json` в папке серии |
| Принятый кандидат повторяет статическое ребро | 9, П5 | FINDINGS F7; `src/agent_graph/evidence_refs.py`, функция `dependency_sufficiency` | Прочитать функцию |
| 23 запроса, около 2,58 ₽, биллинг не измерялся | П5 | BATCH1 README "Запросы, usage, время и расчёт стоимости" | Тот же скрипт `analyze_batch1.py` |
| Клиент модели без прокси и CA-bundle | 9 | ARCH ADR-007; EVIDENCE O10 | `git show origin/docs/architecture-audit:docs/audits/architecture/adr/ADR-007-llm-role.md` |
| Только Linux | 10 | FINDINGS L8 | `grep -n "L8" docs/audits/pr-integration/FINDINGS.md` |
| 12 изменений, 6 ретро и 6 живых, минимум 8, 6 недель | 13 | OFFER "Ход пилота"; PROTOCOL §3 | `docs/product/pilot/OFFER.md` |
| Порог `R / \|C\| ≥ 0,5` | 12, П3 | PROTOCOL §2; DECISIONS D7 | `docs/product/pilot/PROTOCOL.md` |
| `FN_A2 ≤ FN_A1`, `T_A2 ≤ 0,8 × T_A1` | 15, П2 | PROTOCOL §1, §8; DECISIONS D8; `docs/product-architecture-roast-2026-10-20.md` §3 | Там же |
| 12-16 ч клиента; 4-5 ч техлида; 15-20, 30, 30-45 мин на изменение | 14 | OFFER "Что делает команда клиента" | Оценка до замера |
| 50-75 ч нашей стороны | П8 | ECONOMICS §1 | Оценка до замера |
| Около 2-2,5 недель разработки до старта | 12 | BACKLOG "Итого" | Оценка до замера |

## Материалы, которые сознательно не использованы

| Материал | Почему |
|---|---|
| `docs/competitive-evidence-2026-10-16.md` | Описывает прежний продукт, исполнителя изменений (EVIDENCE K6) |
| `docs/migration-completion-offer.md`, `docs/product-rebuild-2026-10-16.md` | Прежняя гипотеза автономного исполнителя |
| Цена 100-150 тыс. руб. | Отозвана (DECISIONS D12) |
| Экраны мобильной версии и CI-скриншоты из `docs/agent-graph-demo/screenshots/` | Для показа достаточно кадров с целевой ВМ |
