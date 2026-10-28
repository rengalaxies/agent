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
| этот PR документов | STATUS, реестр и готовность после слияния #62–#65 и запуска серии 2Б | `main` `f4e6ab7` / `claude/mvp-docs-2b-series` | опубликован | см. checks PR | интеграция этим PR, см. GitHub | серия 2Б завершена; #68 слит, финальные результаты M1 внесены |

Каждый merge 27.10 сделан по разрешению владельца в чате, на голове с зелёным CI
(`--match-head-commit`). Итоговая `main` для серии 2Б: `f4e6ab7`.

## M1 на 28.10.2026

- [#67](https://github.com/rengalaxies/agent/pull/67): сохранён план M1–M6, основной исполнитель Codex.
- [#68](https://github.com/rengalaxies/agent/pull/68): итог transport, режим модель OFF, исправления публикации и учёта. Проверенный head `6d6d7d1a6f52e5eb619c7d580f577e892cfe3086`; все четыре workflow зелёные; merge `1ef7eaca9b66256478022945eef7f8b205571dd2`.
- run 40566128227 завершён: все три модели DISABLED, дальнейших фаз нет. Заморозка main под старую серию снята; manifest не обновлять и live-серию не возобновлять.

## Подготовленные ветки без PR

| Ветка | Пачка | Состояние |
|---|---|---|
| — | — | все подготовленные ветки опубликованы как PR |

## M2 — 28.10.2026

- [#69](https://github.com/rengalaxies/agent/pull/69) слит: merge `14e65e8affe3b64a9ceb647f537e8af6ff7a1138`, head `f488380b9a003368b365cf2b52c5e98adeab4ca8`. Core 40692584761: 858 + 152 PASS; box 40692584737: 11/11 systemd PASS.
- [#70](https://github.com/rengalaxies/agent/pull/70): pin опубликованного актуального релиза и итоговые evidence. Release run 40693796501: release + install-published SUCCESS; sha256 `95648b846da2dd8fbdfdf76942d1c9563bc4be5d3f2cbfad3987ec3eade8a013`. Это CI, не M3.
- Отчёт: [M2](m2-2026-10-28/README.md); M2 **PARTIAL / LIVE BLOCKED**, MODEL OFF. Нужны установка M3 и согласованный тестовый App/Jira/HTTPS; чужие ВМ и pending cloud runs не менялись.
