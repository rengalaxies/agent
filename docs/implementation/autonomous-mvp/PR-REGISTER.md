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
| [#62](https://github.com/rengalaxies/agent/pull/62) | 5Б: одна ВМ Cloud.ru, установка той же коробкой, inventory, digest плана, cleanup; plan без записи state; публикация релиза | `main` `c64c949` / `claude/mvp-5b-cloudru` | опубликован | см. checks PR; offline, actionlint, verify, configuration | нет | merge владельцем; затем релиз, pin, `lock-test`, `plan`, одобрение apply |
| [#63](https://github.com/rengalaxies/agent/pull/63) | 6: 6-r1 исторически с FAIL, ревизия 6-r2, held-out 65/65 без модели; содержит #64 | `main` `c64c949` / `claude/mvp-6-readiness` | опубликован | см. checks PR; box, core | нет | merge после #64 |
| [#64](https://github.com/rengalaxies/agent/pull/64) | исправления продукта: runtime-only потребители на PR, намерение Jira по имени сервиса | `main` `c64c949` / `claude/mvp-service-impact-fixes` | опубликован, `2b096ad` | box и core зелёные на `2b096ad` | нет | merge первым |

## Подготовленные ветки без PR

| Ветка | Пачка | Состояние |
|---|---|---|
| — | — | все подготовленные ветки опубликованы как PR |
