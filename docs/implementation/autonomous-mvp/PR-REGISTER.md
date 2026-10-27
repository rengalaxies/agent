# Реестр PR автономного MVP

Каждая строка: что делает PR, ветка и база, опубликованная голова, CI этой головы,
merge и следующий шаг. SHA коммита, который добавляет строку, в самой строке не
пишется: его ещё нет в момент записи.

## Интегрированные пачки

| Пачка | PR | Ветка | Merge commit | Дата |
|---|---|---|---|---|
| 2А: ядро, контракты, конституция | [#56](https://github.com/rengalaxies/agent/pull/56) | `claude/mvp-2a-core-205322` | `ab3f8b5b95f3177ccb423a15d4de9d8958534e47` | 25.10.2026 |
| 3: граф и runtime | [#57](https://github.com/rengalaxies/agent/pull/57) | `claude/mvp-3-runtime-2a` | `db25c2a563bd5a8fe26c01f4371c1bd440f53a67` | 25.10.2026 |
| 4: Jira/PR, очередь, публикация, допуск модели | [#58](https://github.com/rengalaxies/agent/pull/58) | `claude/mvp-4-service-2a` | `a386d90778d4d541562b06a33ac4ca115f0b2f7e` | 25.10.2026 |
| 2Б: программа квалификации | [#59](https://github.com/rengalaxies/agent/pull/59) | `claude/mvp-2b-prep-9d9655` | `177d1d2ab65d60790cac8639a186ffcddfcdac77` | 25.10.2026 |
| 5А: коробка и установщик | [#60](https://github.com/rengalaxies/agent/pull/60) | `claude/objective-feistel-a46433` | `0f0dc0276ef599bd953bc6d20e593aab4035233a` | 25.10.2026 |
| исправления коробки и допуска модели | [#61](https://github.com/rengalaxies/agent/pull/61) | `claude/mvp-recovery-fixes` | `c64c949e2c3558cbfea0c62922d141355d6684c9` | 25.10.2026 |

Ветки `claude/mvp-3-runtime-1b13b3` и `claude/mvp-4-service-814d77` устарели и в стек
не входят.

## Текущие PR

| PR | Назначение | База / голова | Push | CI головы | Merge | Следующий шаг |
|---|---|---|---|---|---|---|
| [#62](https://github.com/rengalaxies/agent/pull/62) | 5Б: одна ВМ Cloud.ru, установка той же коробкой, inventory, digest плана, cleanup; plan без записи state; строки квот (D14); публикация релиза и установка опубликованного архива | `main` `c64c949` / `claude/mvp-5b-cloudru` | опубликован, `2309fc0` | offline, verify, actionlint, configuration зелёные на `7a5d47e`; для `2309fc0` см. checks PR | нет | merge владельцем; затем релиз, pin, `lock-test`, `plan`, одобрение apply |
| [#63](https://github.com/rengalaxies/agent/pull/63) | 6: 6-r1 и 6-r2 исторические, ревизия 6-r3 (F14, правило полноты human, живые конфигурации), held-out 70/70 без модели; содержит #64 | `main` `c64c949` / `claude/mvp-6-readiness` | опубликован; голова этой записи см. PR | см. checks PR; box, core, verify, actionlint, configuration | нет | merge после #64 |
| [#64](https://github.com/rengalaxies/agent/pull/64) | исправления продукта: runtime-only потребители на PR, намерение Jira по имени сервиса, маршрут только как неизменный (D13) | `main` `c64c949` / `claude/mvp-service-impact-fixes` | опубликован, `18e360b` | box и core зелёные на `18e360b` | нет | merge первым |

Порядок merge: #64, затем #63 (уже содержит `18e360b`), затем #62. #62 и #63 не пересекаются по
файлам; пробное слияние `origin/main` + #63 + #62 проходит без конфликтов (27.10).

## Подготовленные ветки без PR

| Ветка | Пачка | Состояние |
|---|---|---|
| — | — | все подготовленные ветки опубликованы как PR |
