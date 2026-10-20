# Схемы архитектуры — редакция 3

Исторический набор PR №26. Источник: [редакция 3 по закрепленному commit](https://github.com/rengalaxies/agent/blob/9a942cac8cac4190845ec7cfb5c91ce45fe775b7/docs/product-architecture-2026-10-20.md). Текущие схемы: [редакция 4](../product-architecture-v4/README.md).

SVG — отдельные изображения для просмотра и обсуждения; MMD — извлеченный исходный Mermaid. Все девять схем проверены рендером Mermaid CLI в PR №26. Этот набор сохраняет историю: изменения текущей архитектуры вносятся в документ и галерею редакции 4.

| № | Схема | Изображение | Исходник |
|---|---|---|---|
| 1 | Общий консультативный процесс | [SVG](01-overview.svg) | [Mermaid](01-overview.mmd) |
| 2 | Сбор конституции до работы | [SVG](02-constitution.svg) | [Mermaid](02-constitution.mmd) |
| 3 | Использование, правила и полномочия | [SVG](03-context-layers.svg) | [Mermaid](03-context-layers.mmd) |
| 4 | Взаимодействие с coding agent | [SVG](04-agent-workflow.svg) | [Mermaid](04-agent-workflow.mmd) |
| 5 | Поиск HTTP/API-потребителей | [SVG](05-http-api.svg) | [Mermaid](05-http-api.mmd) |
| 6 | Поиск RabbitMQ-потребителей | [SVG](06-rabbitmq.svg) | [Mermaid](06-rabbitmq.mmd) |
| 7 | Состояния анализа, охват и актуальность | [SVG](07-analysis-state.svg) | [Mermaid](07-analysis-state.mmd) |
| 8 | Минимальная поставка | [SVG](08-deployment.svg) | [Mermaid](08-deployment.mmd) |
| 9 | Существующий задел | [SVG](09-existing-components.svg) | [Mermaid](09-existing-components.mmd) |

Это проектируемая архитектура; схема 9 показывает существующий задел, а пунктир в ней — возможное переиспользование. Наличие изображения не подтверждает реализацию.
