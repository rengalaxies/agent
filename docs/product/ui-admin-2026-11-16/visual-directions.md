# A6.1 — визуальные направления, 16.11.2026

Продуктовый дизайн утверждён владельцем сообщением «Подтверждаю». Подготовлены три независимых mockup-изображения через built-in image_gen; интерактивный прототип выбранного варианта2 собран и проверен16.11; [проверка](prototype-verification.md). Порядок ниже соответствует фактическому порядку показа результатов в чате.

| Номер в чате | Концепция | Артефакт |
|---|---|---|
| 1 | Result first | [result-first.png](visuals/result-first.png) |
| 2 | Investigation workbench | [workbench.png](visuals/workbench.png) |
| 3 | Evidence document | [evidence-first.png](visuals/evidence-first.png) |

Выбор: **вариант2 / Investigation workbench**. Владелец выбрал16.11; вариант3 отмечен как тоже приемлемый, но не выбран. Это выбор компоновки; утверждённый объём повторно не запрашивается.

## Условия генерации

Референс: screenshot существующего demo `screenshots/03-demo-change-evidence.jpg`, непосредственно просмотрен и приложен ко всем трём вызовам как style/content reference, не edit target. Запрошен desktop1440×1024; фактические размеры сохраняются в visual-manifest.json. Дата привязки16.11.2026. Генерации отдельные, без коллажа. Исходные файлы в Codex generated_images сохранены; копии артефактов находятся в repo.

## Общий prompt

```text
Use case: ui-mockup. Create realistic, production-quality UI designs with clear hierarchy, strong typography and purposeful spacing. New design of a focused primary screen of the Russian ImpactMap web application, not a clone of the screenshot. Input screenshot is a reference image for the existing off-white background, forest green accents, readable system typography and evidence-driven content; it is not an edit target. Target dimensions 1440 x 1024 desktop, natural viewport ratio, app content only, no browser chrome, no devices. Current date anchor 2026-11-16, display 16 ноября 2026 if a date is needed. One coherent app with results for reviewer and an operator-only section; first version read-only. No invented charts, percentage scores, KPI tiles, AI assistant, logos made from complicated symbols, retry POST button, create-connection form, or marketing hero. Explicit small top label 'Прототип · авторские данные'. Avoid card nesting and large intro space. Use spacing, typography and simple row dividers before borders, shadows rarely. Body 14-16px. Monospace only for code and pins, maximum two fonts. Main user goal: immediately understand the possible effect of a PR, then inspect the exact supporting code. Evidence must be accessible as text, no giant graph required. Main content above fold. Example synthetic PR: 'PR #5 · Ограничение страницы Orders', 'Bitbucket → Kaiten', 'Поколение 2'. Show three independent text-labeled states compactly: 'Анализ: завершён', 'Основание: актуально', 'Публикация: доставлена'. State 'Возможна потеря части заказов', consumer 'Reporting', explanation 'Лимит страницы уменьшен до 100. В коде потребителя найден одиночный запрос.' Caution 'Статический риск. Тесты потребителя не запускались.' Evidence pinned: 'reporting / client.py', 'commit 2cba012ba204 · строка 5', code 'response = requests.get("http://orders:8000/orders", timeout=5)'. Show one primary action 'Открыть основание' or evidence already open with selected row, only one or two secondary actions. Product navigation only 'Изменения', 'Операции', 'Подключения', role 'Оператор'. All source paths and IDs synthetic. Keep readable Russian Cyrillic text, no cropped critical labels or fabricated successful tests. Focus this single frame on the change-to-evidence scenario; errors and connection management exist off-screen, don't cram them into this screen.
```

## Дополнения к независимым вызовам

### Result first

```text
Distinct visual direction: 'Result first'. A restrained report-like result page. Narrow 200px global left navigation; a generous two-column main area with narrative impact and selected consumer on the left, a precise evidence inspector on the right. Title and the three status labels at the top in a compact two-line header. Wide open paper surface, warm white, dark green selection, amber risk accent. No list of all changes on this screen. Strong hierarchy: risk summary first, evidence readable on the same row.
```

### Investigation workbench

```text
Distinct visual direction: 'Investigation workbench'. A compact investigation workbench. Narrow global navigation rail on far left with readable text labels. Left quarter contains a grouped change list with 3 rows, selected PR#5, each row has brief text status. Remaining main area is a focused master-detail workspace: compact selected PR header, risk explanation, then a broad code evidence panel below it. This variation prioritizes fast switching among changes, not a giant summary. Same off-white and forest green product family; white base, row separators, dark green active selection, amber caution. No metric cards.
```

### Evidence document

```text
Distinct visual direction: 'Evidence document'. A calm horizontal-navigation product workspace, no vertical sidebar. Top bar ImpactMap plus the 3 navigation labels and role; below a breadcrumb back to changes. Big readable change title and compact three-state line. Two-page-like content columns divided by a fine vertical rule: a compact affected-consumer outline on the left and a wide evidence document on the right with the actual code line, pinned provenance, and a small contextual 'Что проверить' paragraph. Risk headline is immediate above both, no large blank header. Same warm white/forest green product family; restrained report typography, minimal borders, no nested cards. This direction prioritizes reading the code evidence.
```

## Проверка и ограничения

Все три результата непосредственно просмотрены в текущем запуске: один связный экран, итог выше сгиба, анализ/актуальность/публикация раздельно, основание с pin и навигация в операторский раздел. Это авторские иллюстрации, не скриншоты работающего приложения. Цветные success-маркеры обозначают технические состояния, не безопасность изменения.

Изображения не являются эталоном исходников: генератор добавил контекстные строки кода в некоторых макетах. В прототипе использовать точные строки из авторского fixture, не переписывать нарисованные строки как настоящее evidence. Формулировку «без пагинации» заменить на «в обследованном фрагменте найден одиночный запрос»: статическое наблюдение само по себе не доказывает отсутствие пагинации во всём сервисе. Не добавлять нарисованный generation selector, если полноценная история не реализована. Кнопка перехода к уже открытому основанию должна иметь осмысленное действие focus/scroll либо быть исключена.

Клавиатура, responsive390 и реальные роли не проверяются по картинкам; эти проверки остаются Task2. Установленный worker/ВМ/трекеры не менялись. Следующий шаг — выбрать один из показанных макетов и реализовать его по плану A6.1.

