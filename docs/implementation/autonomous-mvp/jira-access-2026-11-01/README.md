# Jira read-only access probe

Владелец сообщил site rengalaxies.atlassian.net, проект KAN, создание protected
environments и secrets. Публичный tenant_info дал cloudId
d0b47b8d-4655-4cb1-9f81-30573fd372c3 (HTTP200). Это не аутентификация.
Наличие и корректность токена/PEM не проверены; значение не извлекалось.

Новый workflow agent-pilot-jira-probe.yml: manual, main-only, exact expected_main_sha,
без rerun, environment agent-pilot-jira. Владелец должен установить required reviewer,
main-only branch policy и отключить admin bypass до запуска. Не рассчитывать на
автоматически созданный environment. Текущий Connector не имеет прав их проверить.

Secrets: JIRA_EMAIL, JIRA_API_TOKEN. Используется scoped REST token и API gateway
https://api.atlassian.com/ex/jira/d0b47b8d-4655-4cb1-9f81-30573fd372c3.
Это не MCP agent-interface token. Ни webhook, ни service DB не используются.

Четыре GET: myself, project/KAN, mypermissions, search/jql (пять ID/key, без текста).
Проверяются BROWSE_PROJECTS, ADD_COMMENTS, EDIT_OWN_COMMENTS, но право публикации
по фактической записи не доказывается. Пустая выборка допустима; полный обход не
квалифицируется. HTTP статусы сохраняются без исключений/response body/credentials.
Чужой project/task, неактивная identity или недостаток прав дают FAIL до продолжения.

Регрессии используют scripted responses: шесть RED до реализации, после исправления
targeted вместе с существующими App/preparation/demo проверками PASS. Это не LIVE.
Обязательные Core/P1/workflow CI должны пройти на окончательном head до merge.

После интеграции владелец открывает Actions → Agent pilot Jira identity probe →
Run workflow, branch main, expected_main_sha = актуальный полный SHA. Reviewer
одобряет конкретный run. Не включать секреты в inputs. Для App аналогично использовать
agent-pilot-app-probe.yml. Если main изменился до checkout, exact check отказывает;
создать новый run с пересверенным SHA, не rerun.

Read probe PASS не означает intent-quality, webhook delivery, доступ к service на ВМ,
фактическую запись комментария или клиентскую пользу. MODEL OFF. KAN-1..3 не изменяются.
Секреты не переносятся из Actions на ВМ; оператор получает их доверенным каналом отдельно.
