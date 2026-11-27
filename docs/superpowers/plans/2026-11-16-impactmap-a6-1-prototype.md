# ImpactMap A6.1 Prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Выбрать визуальное направление и проверить пять согласованных сценариев на кликабельном авторском прототипе.

**Architecture:** Отдельный throwaway frontend на синтетических данных, без подключения к worker/трекерам. После выбора макета — same-origin статические HTML/CSS/JS; результаты и операторский раздел в одном приложении. Реальная аутентификация и service projections относятся к A6.2, а не изображаются реализованными в прототипе.

**Tech Stack:** Built-in Image Gen для макетов; браузер Codex для проверки; для выбранного прототипа HTML/CSS/JS и существующий Python loopback server без новых runtime dependencies, если выбранный макет не требует иного.

**Spec:** [Утверждённый дизайн](../specs/2026-11-16-impactmap-ui-admin-design.md), подтверждение владельца16.11.2026 «Подтверждаю».

## Global Constraints

- Одна организация/одна установка, desktop в приоритете; узкий экран читабелен, native mobile не нужен.
- Первая UI read-only. Служебный ключ и реальные credentials в прототип не входят.
- CURRENT, состояние задания и публикация показаны отдельно; нет доступа не означает отсутствие влияния.
- Все случаи авторские; прототип не доказывает качество анализа и спрос.
- ВМ, установленный worker, Jira/Kaiten/Яндекс не изменяются этой пачкой.
- После трёх макетов нужен выбор визуального направления; утверждённый продуктовый дизайн повторно не согласовывать.

## Review Focus

- Новое FAILED поколение при старом полезном результате: ошибка наверху, старый результат STALE — Task2, сценарий failure.
- UNKNOWN публикация при CURRENT анализе: нет ложного общего успеха и кнопки повторного POST — Task2, сценарий publication.
- Нет доступа/неподдерживаемый случай: явное ограничение вместо «влияния нет» — Task2, сценарий partial.
- Длинный путь/код/неизвестный код состояния на390px: доступность текста без потери состояния — Task2, responsive journey.
- Переключение демонстрационной роли: явный label simulation, никакого обещания реальной серверной изоляции — Task2, role journey.

---

### Task1: Визуальные направления

**Files:**
- Modify: `docs/superpowers/specs/2026-11-16-impactmap-ui-admin-design.md` — зафиксировать подтверждение.
- Create: `docs/product/ui-admin-2026-11-16/visual-directions.md` — имена концепций, prompts, результат/выбор; фактические пути изображений фиксировать после генерации.
- Inputs: `docs/product/ui-admin-2026-11-16/screenshots/03-demo-change-evidence.jpg`.

**Interfaces:**
- Consumes: утверждённые5 сценариев, две роли, результаты + оператор; текущий screenshot как источник визуального языка.
- Produces: ровно3 независимых1440×1024 mockups; выбранное изображение становится визуальной целью Task2. Нумерация определяется порядком появления изображений в чате.

- [x] Step1: Прочитать дизайн и осмотреть существующий screenshot; подтвердить отсутствие нового скрытого контекста.
- [x] Step2: Три отдельных built-in Image Gen вызова с приложенным screenshot: разные иерархии одного result screen, одинаковые продуктовые ограничения, дата16.11.2026.
- [x] Step3: Проверить изображения: один экран на изображение, итог выше fold, понятные analysis/freshness/publication, evidence и вход в операторский раздел, авторские данные.
- [x] Step4: Показать три изображения, запросить выбор визуальной цели; не строить UI до выбора.
- [x] Step5: Сохранить prompts/статус в журнал и локальный commit. Отсутствующий выбор — pending preference, не ошибка выполнения и не отзыв авторизации проекта.

### Task2: Выбранный кликабельный прототип

**Files:**
- Create: `prototypes/impactmap-ui/index.html`, `styles.css`, `app.js`, `fixtures.js`, `README.md`.
- Create: `docs/product/ui-admin-2026-11-16/prototype-verification.md` и новые screenshots с отдельными именами.
- Modify: `CHECKPOINT.md`, `docs/product/roadmap-2026-11-14/UI-ADMIN-BATCH.md` — фактический прогресс.

**Interfaces:**
- Consumes: точно выбранный displayed mockup из Task1 и дополнения владельца; `fixtures.js` exports frozen author dataset, без сетевых credentials.
- Produces: hash routes `#/changes`, `#/changes/{id}`, `#/operations`, `#/connections`; состояния/evidence открываются по ID, fallback при неизвестном маршруте; выбранный visual target сохранён в repo перед handoff.

- [x] Step1: Прочитать image-to-code и сохранить выбранный visual reference; продуктовый объём не расширять.
- [x] Step2: Собрать shell/navigation и три авторских изменения: CURRENT/DELIVERED риск, FAILED+STALE, PARTIAL/UNKNOWN. Отдельно empty/closed/incompatible/unknown-code варианты в fixtures для проверки представления.
- [x] Step3: Реализовать список → результат → evidence, error→operations, connection→binding и новое исправленное поколение; не использовать реальный publication/retry.
- [x] Step4: Проверить все5 сценариев в браузере1440 и390; клавиатурные переходы/focus, длинные пути/код, отсутствие ложных success и секретов, browser refresh/deep route. Expected: все переходы доступны, ограничения явны, никаких внешних writes.
- [x] Step5: Сопоставить screenshot с выбранным reference при одинаковом viewport, исправить существенные расхождения; записать реальные границы проверки.
- [x] Step6: Финальная проверка и один независимый review, локальный commit, checkpoint и handoff рабочего preview. A6.2–A6.5 остаются отдельными пачками.

## Self-review

План покрывает A6.1, не всю A6: реальная auth/projections, service UI и LIVE приёмка требуют собственных планов после проверки прототипа. Новые автоматические тесты для throwaway макета не нужны; проверка значимых сценариев выполняется в браузере. Task1→Task2: единственная обязательная внешняя зависимость — выбранное изображение. Default execution — основной агент в текущем checkout; новый worktree и implementer subagents не требуются.

## Execution16.11

Task1: три макета с общим референсом созданы и просмотрены; prompts, копии и hashes — [журнал](../../product/ui-admin-2026-11-16/visual-directions.md). Фактические размеры1487×1058 вместо запрошенных1440×1024 — ограничение генератора; изображение не растягивалось. При реализации viewport будет1440 и пропорции будут проверены. Владелец выбрал displayed option2. Task2 завершён: отдельный prototype, браузерные сценарии и design QA passed; [verification](../../product/ui-admin-2026-11-16/prototype-verification.md). Повторное согласование объёма/метода выполнения не нужно: действующая авторизация работы сохранена, основным исполнителем остаётся текущий агент.

Task2 execution: HTML/CSS/JS + loopback Python, без новых runtime dependencies. Нестандартный Vite bootstrap не выполнялся: утверждённая архитектура статического throwaway прототипа сохранена, Node/npm отсутствуют. Browser verification1440/390 и exact-reference1487 завершена. Reviewer P2 inherited-property route воспроизведён и исправлен own-property check; constructor/__proto__/toString проверены. Локальный preview оставлен работающим. Полный repo suite не запускался: production source не менялся. A6.2–A6.5 остаются открыты.
