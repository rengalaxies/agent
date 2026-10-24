# Источники и границы сравнения

Проверено 24.10.2026. Сравнение по официальным материалам описывает задачи,
а не доказывает превосходство. Часть альтернатив может быть компонентом сервиса.

| Источник | Что использовано | Слайд |
|---|---|---|
| [Предложение](../OFFER.md), [решения](../DECISIONS.md) | Автономность, Jira/PR, отсутствие постоянного инженера | 1, 3, 6, 8 |
| [Граф](../GRAPH.md), [конституции](../CONSTITUTION.md), [установка](../INSTALLATION.md) | Целевая структура и работа | 4, 6 |
| [Основания](../EVIDENCE.md), [backlog](../BACKLOG.md) | Реализация отдельно от плана | 7 |
| [Протокол](../PROTOCOL.md), [экономика](../ECONOMICS.md) | Как проверять эффект без придуманной выгоды | 8 |
| [Приёмка демо](../../../agent-graph-demo/deployments/2026-10-22/README.md) | Механизм одиночного запроса, только синтетика | 2, заметки |
| [Серия моделей](../../../../experiments/evidence_refs_v2/runs/2026-10-22-batch1/README.md) | Qwen 0/3 остановился на action до семантики, без нового прогона | 7, заметки |
| [Qwen-Agent](https://github.com/QwenLM/Qwen-Agent) | Инструменты, MCP, собственный endpoint | 5 |
| [Sourcegraph](https://sourcegraph.com/docs/code-navigation/precise-code-navigation) | Точная навигация по SCIP, определения/использования | 5 |
| [oasdiff](https://www.oasdiff.com/docs/getting-started) | OpenAPI diff, несовместимость и вывод CI/Markdown | 5 |
| [Pact](https://docs.pact.io/) | Контрактные проверки HTTP/сообщений | 5 |
| [Tempo](https://grafana.com/docs/tempo/latest/metrics-from-traces/service_graphs/) | Граф из трасс, наблюдаемые вызовы и метрики | 4–5 |
| [Cloud.ru Terraform](https://cloud.ru/docs/terraform-evolution/ug/topics/quickstart) | Основа облачного адаптера, не готовность нашего installer | 6, заметки |

Исследование Ontonet опубликовано в #48. Оно полезно как контекст, но не
основной конкурентный слайд: сервисы решают разные задачи. UX-аудит удалённо
не найден и не используется как доказательство поведения пользователей.
