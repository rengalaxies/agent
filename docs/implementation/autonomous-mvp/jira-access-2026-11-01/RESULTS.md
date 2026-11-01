# Доступы — реальные пробы 01.11.2026

Оба запуска main aa757a8f70375ae4a92ab1a258dc1ea61da26260 прошли exact SHA gate.

## Jira: REAL API READ PASS

[Run 41329447561](https://github.com/rengalaxies/agent/actions/runs/41329447561),
artifact 13092343586, SHA256 f8844237b38bcf839be34806f67266d9c6f7ff8286677472e376f59ac8bc0a26.
Скачанный ZIP сверён с digest GitHub; JSON прочитан исполнителем.

Identity active, проект KAN и три задачи KAN-1..3 доступны, все четыре GET HTTP200.
BROWSE_PROJECTS, ADD_COMMENTS, EDIT_OWN_COMMENTS подтверждены API. Значения credentials
не извлекались. Фактическая запись комментария, webhook, полный обход, качество
намерений и установленный сервис NOT_RUN. MODEL OFF.

## GitHub App: BLOCKED до сетевого запроса

[Run 41329418283](https://github.com/rengalaxies/agent/actions/runs/41329418283),
artifact 13092233035, SHA256 14b6d953d1681c9aec9b76dfbedf50114ebbae40dda792adb6e34cb8b8ed6b1c.
Отчёт: BLOCKED / PermissionError. Это не отказ GitHub credentials и не App auth PASS.

Причина в probe: build_connectors создаёт dry-run DirectorySink, а placeholder
state=/unused направлял mkdir в root-owned путь. Зависимость была скрыта прежними
тестами, подменявшими build_connectors целиком. Реальная сборка коннекторов теперь
проверяется с синтетической подписью/HTTP ответом, настоящими sinks и filesystem.
Регрессия RED запрещает root-owned placeholder; исправление использует owned
TemporaryDirectory, удаляемую до чтений API и при ошибке сборки. Секреты и права
не ослабляются, service DB/publisher не запускаются.

После merge исправления нужен НОВЫЙ main-only App probe с новым expected_main_sha,
не rerun: workflow намеренно запрещает run_attempt > 1. Jira повторять не требуется.
PEM менять по этому отказу оснований нет. ВМ/pin/service/model не менялись.
