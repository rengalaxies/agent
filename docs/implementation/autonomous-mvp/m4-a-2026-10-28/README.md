# M4-A — авторские офлайн-регрессии, 28.10.2026

Позднейшее [предметное ревью перед интеграцией](integration-review/README.md) воспроизвело
и исправило ещё 3 пробела: глагол редактирования документации, legacy knowledge без
config digest и persistent graph до пересчёта профиля. Теперь 25 авторских методов,
883 LOCAL PASS. Этот checkpoint дополняет датированные результаты ниже; прежний
CI на `214bec72` не является CI нового head. MODEL OFF; M3 release не менялся.

**OFFLINE PREPARATION. MODEL OFF. M4 и клиентская полезность не подтверждены.**
Это новые авторские сценарии и проверки исправлений, не независимый held-out benchmark.
Ожидаемые результаты основаны на исходном коде fixture и явно зарегистрированном
авторском требовании; они не являются ожиданиями независимого заказчика.

База main: `d5e25fde5927eca99e574b2ac82be80cd5adfe16` (#68–70 учтены).
Основные исправления M4-A: `8d0ff980d6653338e5eb51ecf641652e65263190`;
совместимость тестов с optional API dependencies: `9a0c3b4dcdc0a016565c80627cb2b785d09a2ad1`.
[Хеши кода и тестов](code-files.json), [фактические наблюдения](observations.json).
Работа выполнена в отдельной ветке `codex/m4-a-analysis-boundaries`,
[PR #72](https://github.com/rengalaxies/agent/pull/72). Финальный CI — в checks этого PR;
его зелёный результат не заменяет M3 ack или независимую M4.

## Что уже было доказано и не копировалось как новая находка

Перед новыми случаями прошли **94 существующие проверки** ([лог](existing-baseline.log)):
`tests/service/test_intent.py`, `tests/graph/test_discovery_regressions.py`,
`test_graph.py`, `test_graph_store.py`, `test_git_sources.py`,
`test_knowledge_regressions.py`, `test_coverage_noise.py`, `test_graph_query.py`.

| Уже существующая граница | Существующие проверки |
|---|---|
| README-only PR не даёт API delta | `test_results.ResultTests.test_readme_only_change_abstains`, `test_git_sources.ChangeTests.test_readme_edit_has_no_delta_and_removal_is_reported` |
| Явно неизменный маршрут не цель; другой маршрут может меняться | `test_intent.IntentTest.test_route_named_only_as_unchanged_is_not_a_target`, `test_english_unchanged_route_and_changed_route_select_only_the_changed_one` |
| Одинаковый маршрут двух провайдеров требует указания сервиса | `test_intent.IntentTest.test_route_of_two_providers_without_a_named_service_stays_ambiguous`, `test_graph_query.RuntimeNextToCodeTests.test_same_path_of_another_service_is_a_separate_operation` |
| Wrapper, Session, динамические параметры не становятся уверенным static fact | `test_graph.GraphTests.test_dynamic_wrapper_and_parameter_shadow_remain_unknown`, R3/R4 в `test_discovery_regressions.py`, `test_coverage_noise.py` |
| Изменение цитаты/адреса/требования инвалидирует основание | `test_graph_store.KnowledgeTests`, `test_knowledge_regressions.KnowledgeRegressions` |
| Отозванный repository скрывает старые context/IDs/граф/историю | `test_graph_store.AccessTests.test_revoked_repository_disappears_from_graph_cache_counters_history_and_old_ids`, `test_graph.GraphTests.test_revoked_access_cannot_read_cached_sources_summaries_or_checks` |

Новый fixture соединяет эти границы на других исходниках и с исполнением поведения;
это композиционная авторская проверка, не новое доказательство независимости тестов.

## Воспроизведённые ошибки и минимальные исправления

Первый прогон новых intent/provider проверок: **FAIL** на исходной реализации
([до исправлений](regressions-before.log)); положительные контроли в этом же прогоне
проходили. Дополнительные ошибки свежести и обработки неподдерживаемого синтаксиса
сохранены отдельно, до соответствующего исправления.

| Дефект / фактический исходный ответ | Минимальное исправление и контроли |
|---|---|
| `update README. Document GET /parcels pagination` выбирал операцию как `explicit` | Документационные фразы и их контекст не устанавливают изменение. Отдельное явное `GET ... changes page_size` сохраняет цель. Новый reason `documentation_only` идёт по существующему ABSTAINED fallback |
| `keep GET ... unchanged and change POST ...` отрицал обе операции | Поддержан узкий контраст `unchanged and <change action>`. Не добавлен универсальный разбор союзов/отрицаний |
| `ledger GET ... unchanged; depot GET ... changes` выбирал оба сервиса | Область сервиса определяется для конкретной фразы/операции. Явная метка поля `depot:` или route-free summary может задавать общий scope; название сервиса при другой операции не заимствуется |
| `GET ... не изменится` считался положительным упоминанием | Дополнена уже существующая группа русских отрицаний. Не заявляется понимание произвольной русской/английской формулировки |
| Буквальный текст `@@999@@` вызывал IndexError | Пользовательские marker-like токены не индексируют приватную таблицу маршрутов. Реальное route mention сохраняется ([воспроизведение](additional-before.log)) |
| `.fastapi`, подмена `FastAPI`, переприсваивание приложения или `api.get` давали достоверную HTTP operation | Для положительного объявления нужны абсолютный FastAPI import и непротиворечивые bindings фабрики/приложения. Подмены дают `provider_route_unsupported`, операций/зависимостей не доказывают. Исполненные impostor decorators действительно не регистрируют `/parcels` |
| Переход к неподдерживаемым APIRouter / `fastapi.FastAPI()` объявлялся `OPERATION_REMOVED` | Route-like decorator вне закрытого синтаксиса даёт gap. Такие конструкции не извлекаются как API; неизвестность не объявляется доказанным удалением ([до](additional-before.log)) |
| Старый extractor profile оставался CURRENT при неизменных pinned Git trees | Проверка profile до pinned freshness: STALE / `extractor_profile_changed` ([до](scenarios-before-profile-guard.log)) |
| Знание старого profile становилось CURRENT в новом контексте с теми же цитатами | Profile включён в digest основания знания. Содержимое истории не переписывается; требуется повторная проверка ([до](profile-knowledge-before.log)) |

Закрытый профиль **`http-requests-4` → `http-requests-5`** изменён для явного
инвалидирования прежних оснований после исправления ложных деклараций. Это сужение
положительных AST-доказательств и новая граница неизвестности, не поддержка новых HTTP
библиотек, APIRouter, wrapper/dataflow или произвольных фабрик. Схемы store/output
не изменены. Новый core identity отличается от установленного/подготовленного M3;
автоматического обновления M3 нет.

## Компактный авторский сценарий Depot / Dispatch

Исходники: `tests/graph/fixtures/m4_a/`; тесты: `test_m4_a_scenarios.py`.
Git-репозитории создаются только во временном каталоге; даты и автор commits фиксированы.
Анализатор читает их Git objects. **Сам анализатор исходники не исполняет.**

| Сценарий | Исходное основание | Фактическая проверка |
|---|---|---|
| Документация без API изменения | Только README commit; Python declarations не меняются | API/оба клиента возвращают те же 9 ID; deltas/findings пусты |
| Отрицание и несколько операций | Письменные task strings + реальные операции GET `/parcels`, POST `/labels` | Изменённая операция сохраняется отдельно от неизменной; docs не дают API intent |
| Один маршрут у разных сервисов | Depot и Ledger оба объявляют GET `/parcels` | Неуказанный сервис остаётся ambiguous; явные фразы выбирают только свой сервис |
| Поддерживаемые адреса/config | Operator map: Depot `https://edge.example.test/v2`, Ledger другой host | `HOST + "/v2/parcels"` разрешается только в Depot. Повтор без requirements сохраняет обнаруженную зависимость |
| Wrapper вне профиля | `wrapped.export → load(target) → requests.get(target)` | Он реально получает 9, затем 3 ID; static dependency отсутствует, gap виден. Уверенный consumer map из runtime oracle не передаётся анализатору |
| Цитируемый источник меняется | Новый commit `dispatch/client.py` | Старый pinned snapshot по-прежнему CURRENT как историческое дерево; знание в новом контексте STALE / `proposal_basis_differs` |
| Доступ отозван | Новый policy без Dispatch и его требования | Старый широкий context — `not_found`; source/dependency/requirement не видны в узком контексте |

Авторское требование `R-dispatch-all` задаёт все 9 ID без дублей; оно зарегистрировано
оператором теста с issuer и sha256 файла. Само наличие прозы не делает её approved.
При default 40 оба исполнения возвращают 0..8; при default 3 — 0..2. Анализатор
показывает для прямого Dispatch `POSSIBLE_TRUNCATION` с условием и
`test_executed=false`. Отдельный oracle исполнил потерю полноты, но не подменяет
статическую гипотезу анализатора статусом выполненного им теста.

Исполнение — настоящий Python/FastAPI handler через **in-process ASGI TestClient**;
вызов `requests.get` адаптирован к этому transport небольшим shim. `requests` package
в окружении не установлен. Поэтому не заявляются реальная сеть/requests serialization,
TLS/DNS/proxy parity или тест настоящих Jira/GitHub endpoints. ASGI использует служебный
asyncio socketpair: sandbox-прогон был остановлен, затем выполнен с разрешёнными локальными
сокетами. Новых пакетов/ВМ/SSH/credentials/реальной модели для этого не потребовалось.

## Проверки и воспроизведение

- LOCAL исходный существующий набор: **94 PASS**.
- LOCAL финальные авторские проверки: **20 PASS**, включая отрицательные контроли
  ([лог](author-tests-final.log)); целевой существующий+новый набор **51 PASS**
  ([лог](targeted-final.log)), lint F401/F811/F841 PASS.
- Финальный полный LOCAL набор на `8d0ff98`: **878 PASS** ([лог](full-local-tests.log)).
  Промежуточный прогон во время редактирования сработал на code fingerprint mismatch;
  он не использован как финальное evidence, защита квалификации не ослаблялась.
  CI окончательного PR фиксируется через его checks до окончания пачки.
- Минимальный graph-evidence CI первоначально упал без FastAPI (run 40743953907).
  Исправлена совместимость новых тестов, service/workflow dependencies не менялись:
  core-only venv — 20 обнаруженных тестов, **16 PASS + 4 SKIP** с явной причиной
  ([лог](core-only-tests.log)); с API dependencies — **20 PASS, 0 SKIP**
  ([лог](author-tests-optional-final.log)). Пропускается только исполнение ASGI/регистрации,
  чистые extraction/freshness/access случаи остаются активны в core-only CI.
- Независимый проект, настоящие endpoints и клиентская полезность: **NOT_RUN**.

```bash
PYTHONPATH=.:src:tests:tools python -m unittest tests.service.test_m4_a_intent tests.graph.test_m4_a_providers tests.graph.test_m4_a_scenarios -v
PYTHONPATH=.:src:tests:tools python tests/graph/ci_unittest.py discover -s tests -v
```

## Граница с M3 и интеграция

Сверена ветка M3 `m3/dm-p1-ui-install` на
`c87f9735ff7ba27d19c91158dc569aa8c57d146a`, [PR #71](https://github.com/rengalaxies/agent/pull/71).
Она готовит установку проверенного release `14e65e8affe3…`, а не M4-A.
M3 меняет STATUS, READINESS, M1–M6 plan и новый `m3-2026-10-28/`.
M4-A эти файлы **не меняет**: свой отчёт находится в отдельном каталоге, source scope —
`src/agent_graph/{__init__,discovery,engine}.py`, `src/agent_service/intent.py` и новые тесты.
На сверенных SHA пересечения файлов нет. Статическая сверка не является ответом исполнителя:
**подтверждение M3 через PR до интеграции ещё требуется**.
[Запрос границы опубликован в #71](https://github.com/rengalaxies/agent/pull/71#issuecomment-6477016920);
молчание не считается согласием, автоматическое слияние не включалось.

Deployment, release pin, installer, credentials, очередь и коннекторы не менялись.
Установленный/подготовленный M3 release не обновляется этой пачкой. Перед будущей
согласованной интеграцией нужно повторить compare к свежей main и M3 head, получить
ack границы, учесть новый core identity/profile и пересчитать граф. Расширять допуск
модели, перезаписывать старые манифесты или выдавать старую квалификацию за новую нельзя.

## Что требуется для независимой M4

Нужны проект и ожидаемые последствия, подготовленные другим человеком до проверки
анализатором: реальные repo/commit pairs, источник требований и применимость, владельцы,
разрешённые address/config mappings, контрольные отрицательные случаи, доступный
runtime-source с идентичностью и свежестью. Сначала зафиксировать ожидания/границы,
затем запускать анализ; не передавать разметку потребителей в его конфигурацию.
Проверить новые и отозванные доступы, динамические формы, freshness и ложные связи,
сопоставить с независимо выполненными тестами и учитывать FN/FP и реальный труд человека.

20 авторских проверок не оценивают обобщающую способность или пользу заказчику.
Исторические 2b-r1/6-r1..6-r3, их корпуса/манифесты/результаты не менялись.
