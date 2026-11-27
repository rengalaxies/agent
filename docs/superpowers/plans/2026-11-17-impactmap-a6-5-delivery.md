# A6.5: пилотная поставка UI ImpactMap

Основание: утверждённый docs/superpowers/specs/2026-11-16-impactmap-ui-admin-design.md; база01968c8. Исполнение inline по уже данному поручению «следующая пачка».17.11 владелец уточнил: использовать публичный IP Cloud.ru вместо обязательного домена/туннеля.

## Границы

Отдельный release/состояние и loopback upstream; работающий worker не заменять. Публичный вход только HTTPS с доверенным IP SAN, автоматическим продлением и proxy allowlist /ui. Секреты/служебный Bearer не выдаются. Публичный HTTP обслуживает лишь ACME challenge и redirect; новые default accounts отсутствуют. Нет права объявлять независимую оценку, личную приёмку5 сценариев, LIVE Яндекс или общий gate10 пройденными.

## Task 1: коробочная доставка UI и восстановление доступа

Interfaces: BoxConfig.ui.origin → generated private ui.json и optional service ui_config_path → launch guarded entry. UI origin HTTPS, backend loopback. Auth DB фиксирована state/ui/auth.sqlite, private owner/mode. Без ui всё работает как раньше; наличие старого файла не включает UI.

Сначала тесты: optional UI config, private launch selection, rejected public backend/HTTP origin, auth DB входит в backup; restore отзывает все сессии/challenges и выключает восстановленные учётные записи до локального approve/enable, fault rollback сохраняет прежний комплект. Старые backups без auth не сохраняют доступ старых users. Затем минимальная реализация. Config files при restore не заменяются; origin не переезжает незаметно.

Команда: PYTHONPATH=src:.:tests:tools work/a6-2/build-venv/bin/python -m unittest tools.agent_service.box.tests.test_ui_delivery tools.agent_service.box.tests.test_state tools.agent_service.box.tests.test_config -q. Expected: GREEN (Linux-only tests проверяются на ВМ). Commit с исходниками/тестами.

## Task 2: защищённые ссылки трекеров

Interfaces: валидированный UISettings → Service result document → Jira ADF/Kaiten comment. Только fixed /ui/result?resource_id= encoded current resource; никаких токенов или model-generated link fields. Summary/truncation сохраняют ссылку, default без UI не меняется.

Сначала тесты: origin/path injection, summary Jira link, Kaiten4096 budget/marker/link, service stamping only from configured origin. Затем реализация и профильная проверка UI/connectors/service. Expected: GREEN. Commit.

## Task 3: Linux, публичный IP HTTPS, эксплуатационная приёмка

Interfaces: immutable commit/release → isolated Linux upstream → existing nginx separate443 virtualhost. Перед изменениями сохранить текущий nginx config и loaded runtime receipts; не раскрывать legacy HTTP/backend API через новый HTTPS. Certbot>=5.4/IP shortlived, staging validation перед trusted issuance; renew timer+deploy hook. Не менять trust store браузера/не обходить TLS warnings. Проверить внешний TLS, login/role/scoped result, restart, backup/restore на отдельном state. Если cloud ingress/SSH недоступен — сохранить точную диагностику и продолжить доступную локальную часть.

Выполнить полный Linux unittest discover и box suite непривилегированным пользователем, packaged smoke. Expected: GREEN или явно перечисленные реальные failures. Выполнить browser keyboard/focus/zoom checks с отдельным QA account, не считать их owner acceptance. Реальные tracker записи только на ранее выделенных тестовых целях и при подтверждённом доступе. Пароли не печатать/не commit; локальный UI admin создаёт владельцу доступ по защищённому каналу.

Финал: fresh-context source review всего диапазона, один RED→GREEN fix-pass важных находок. Отчёт docs/operations/a6-5-2026-11-17 с evidence manifest и точными OPEN gates; CHECKPOINT update. Не отмечать A6.5 полностью DONE до личной приёмки/реальных link cycles. Отдельный commit отчёта.

## Review Focus

Restore с отозванными credentials и прерванным swap; отключение UI не зависит от оставшегося файла; summary/truncation не выкидывают link; reverse proxy не открывает служебные endpoints/не подделывает scope; сертификат IP и повторное продление проверяются отдельно от получения первого сертификата.
