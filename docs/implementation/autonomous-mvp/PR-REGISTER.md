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

Ветки `claude/mvp-3-runtime-1b13b3` и `claude/mvp-4-service-814d77` устарели и в стек
не входят.

## Текущие PR

| PR | Назначение | База / голова | Push | CI головы | Merge | Следующий шаг |
|---|---|---|---|---|---|---|
| [#61](https://github.com/rengalaxies/agent/pull/61) | исправления восстановления коробки (P1, P1, P2), типизированный допуск модели, manifest 2b-r1, SC2024 и lint на PR | `main` `0f0dc02` / `claude/mvp-recovery-fixes` | опубликован, удалённый SHA сверен | код `5f71999`: box 11/11 (systemd), lint, core, P1 зелёные | нет | merge, затем живая 2Б на принятой `main` |

## Подготовленные ветки без PR

| Ветка | Пачка | Состояние |
|---|---|---|
| `claude/mvp-5b-cloudru` | 5Б: Cloud.ru provisioning той же коробкой | офлайн-часть готова локально; PR после #61 |
| `claude/mvp-6-readiness` | 6: программа оценки технической готовности | в работе |
