# Русский формат Jira — установлен на Cloud.ru 08.11.2026

На существующей dm-p1-ui (82.202.141.50) установлен опубликованный релиз
`a02ffa7854dcc38cecc7fe5c5317466059926cd9`. PR103 CI4/4 PASS;
[release / published install / published recovery](https://github.com/rengalaxies/agent/actions/runs/42479463480) PASS.
Архив, manifest, файлы и wheels проверены на целевом хосте. State/core/recovery
контракты совпали с предыдущим c4053c6. Отдельный agent-bitbucket.service:
UID995, model OFF (model_not_configured), автозапуск enabled, 127.0.0.1:8092,
jira.comment_format=summary_ru, secrets0600/config0640. Другие службы active.

## Живой результат

[KAN-9, комментарий10046](https://rengalaxies.atlassian.net/browse/KAN-9?focusedCommentId=10046)
обновлён штатным worker в 16:57:29 Moscow. ID, автор, время создания и список
комментариев сохранены: [10013,10046]. Текст3413→625символов, включая marker.
Русский вывод, необходимость review и оговорка об отсутствии интеграционных тестов
сохранены. Confluence: заголовок, версия4 и ссылка вместо полной страницы.
PR4 сейчас исправлен, поэтому вывод честно сообщает отсутствие поддерживаемой
дельты, а не демонстрирует найденную зависимость. Новую USEFUL-дельту эта пачка
не создавала. Полный neutral outbox сохранён:4217символов с требованиями Confluence.

Штатно переоткрыты4 известных Bitbucket-ресурса при остановленном worker;
параллельный reconcile не запускался. Очередь завершена. Два FAILED intents —
ожидаемые поколения1/2 негативного PR3 без связанной Jira, причина
exactly_one_linked_jira_required. Status notices пусты. После реального restart
новый PID60331, тот же SHA, очередь и опубликованное тело/IDs комментариев неизменны.
Это restart на целевой ВМ; reboot в этой пачке NOT_RUN.

## Backup и ограничения

Matching backup: /var/backups/agent-bitbucket/summary-20261108T135625Z/snapshot.tar.gz.
SHA256: bfbb37d18864a9e9870b55b5b404547330b6f0748d596766103e402821e3a71e.
Scratch restore PASS:114файлов побайтово по SHA256, integrity_check всех6 SQLite
(активные2 и сохранённые исторические копии). Первый preflight ошибочно ожидал
ровно2базы; остановился до смены конфигурации, вернул старый worker. Исправленная
проверка требует обе активные базы по текущей конфигурации и проверяет все копии.
Production restore / downgrade на ВМ в этой пачке NOT_RUN.
Доказательства: [LIVE-VERIFICATION.json](LIVE-VERIFICATION.json).

## Откат

Предыдущий immutable release сохранён:
/opt/agent-bitbucket/releases/agent-service-0.1.0-gc4053c6d4a95-linux-x86_64-cp312.
Для отмены только представления: при остановленном agent-bitbucket сохранить
свежую safety-копию состояния/receipts, атомарно вернуть current на этот release,
вернуть прежние analysis.code_version и jira.comment_format=full (или убрать поле),
сохранив текущие credentials. State/core контракты проверены совместимыми.
После старта сверить loaded/status и журналы. Само переключение конфигурации не
переписывает уже опубликованный комментарий; для возврата полного текста нужна
контролируемая повторная обработка через ServiceStore API при остановленном worker.
Не отматывать БД на pre-update backup после внешних публикаций без сверки receipts:
это может потерять сведения о доставке. Matching архив сохранён для восстановления,
но его применение к production после публикаций отдельно не проверялось.
Не менять основной agent-service, Nginx, демо, VPN и не применять старый Terraform plan.
