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
| исправления продукта: runtime-only потребители, намерение Jira (D13) | [#64](https://github.com/rengalaxies/agent/pull/64) | `claude/mvp-service-impact-fixes` голова `18e360b` | `a1f12d037e71640df848dec66a5b2bfd2aec77a0` | 27.10.2026 |
| 6: ревизии 6-r1..6-r3, живые конфигурации readiness | [#63](https://github.com/rengalaxies/agent/pull/63) | `claude/mvp-6-readiness` голова `399bb56` | `00553f03dabcfc0cdcfcd7ad5986a8f9f982c3ff` | 27.10.2026 |
| 5Б: одна ВМ Cloud.ru, строки квот (D14), релиз с установкой опубликованного архива | [#62](https://github.com/rengalaxies/agent/pull/62) | `claude/mvp-5b-cloudru` голова `2309fc0` | `f5c0c36e8eb99ad0d1467cf3d31a3d660c69cb58` | 27.10.2026 |
| pin опубликованного релиза `f5c0c36` | [#65](https://github.com/rengalaxies/agent/pull/65) | `claude/mvp-release-pin` голова `81dd456` | `f4e6ab7906fe5db5fbce9700bcad6547757bb63e` | 27.10.2026 |

Ветки `claude/mvp-3-runtime-1b13b3` и `claude/mvp-4-service-814d77` устарели и в стек
не входят.

## Текущие PR

| PR | Назначение | База / голова | Push | CI головы | Merge | Следующий шаг |
|---|---|---|---|---|---|---|
| этот PR документов | STATUS, реестр и готовность после слияния #62–#65 и запуска серии 2Б | `main` `f4e6ab7` / `claude/mvp-docs-2b-series` | опубликован | см. checks PR | нет | слить только после серии 2Б: каждая фаза сверяет `main` с `f4e6ab7` |

Каждый merge 27.10 сделан по разрешению владельца в чате, на голове с зелёным CI
(`--match-head-commit`). Итоговая `main` для серии 2Б: `f4e6ab7`.

## Подготовленные ветки без PR

| Ветка | Пачка | Состояние |
|---|---|---|
| — | — | все подготовленные ветки опубликованы как PR |
