# Свежая проверка перед репетицией — 11.11.2026

PASS: технический выбранный demo-контур сохранился после паузы. Проверка read-only;
worker/ВМ не перезапускались, исходники/конфигурации/страницы/задачи не менялись.
Модель и платные ресурсы не включались. Это не новый change/fix прогон и не репетиция человека.

- SSH по настроенному pinned-key профилю: dm-p1-ui,82.202.141.50.
- Загруженный runtime a02ffa7854dcc38cecc7fe5c5317466059926cd9, UID995, autostart enabled,
  publication live, jira.comment_format=summary_ru, model_not_configured (OFF).
- agent-bitbucket, agent-service, Nginx, Docker, ssh.socket active. HTTP loopback80/8080/
  8091/8092=200; защищённое демо18081=401 как ожидалось. dmrp-ui healthy.
- Статус без notices, очередь проверяемого PR4 DONE, generation12/published_generation12.
- Bitbucket credential реально читает OPEN PR4 на восстановленном head
  01b6ebfa4cefb633f9606b2bded4f2e00c3be96d. Jira identity соответствует владельцу,
  comment10046 и список[10013,10046] сохранены. Confluence360725current/v6;
  storage body SHA256 совпал с восстановленным исходным текстом.
- Credentials в процессе совпали с текущим secrets.env. По приватной метаинформации
  даты окончания годовых токенов08.11.2027; текущие Jira/Bitbucket/Confluence API reads PASS.
  Значения credentials не включены в отчёт.

Доказательства:[verification.json](verification.json).

## Интеграция документов

До этой пачки PR102 (37fb6eb) и PR104 (18a071e) оставались открытыми и оба изменяли
STATUS/READINESS/план. Отдельное ревью их точных heads не нашло Critical/Important.
PR102 слит как6d205e423cbdade5b2e9da32f8839610042e4421. В PR104 сохранены все
исторические дополнения PR102 и текущая сводка; docs-only разрешение пересечения
не переносит старые runtime-результаты на новый SHA. Финальный факт слияния и SHA —
[PR104](https://github.com/rengalaxies/agent/pull/104).

Main после слияния документов отличается от installed code SHA — это ожидаемо:
релиз/архив/pin и код процесса не менялись, повторный выпуск не нужен.

## Что делаем дальше

Следующая пачка — владелец проходит [репетицию5–7минут](../demo-acceptance-2026-11-09/REHEARSAL.md).
Исполнитель ведёт технические действия, владелец оценивает понятность вывода;
независимость=false. Затем запись и слайды. Человеческая репетиция/метрики,
независимый проект, исходный GitHub webhook/App gate и ранее перечисленные
непройденные host-recovery проверки остаются открытыми.
