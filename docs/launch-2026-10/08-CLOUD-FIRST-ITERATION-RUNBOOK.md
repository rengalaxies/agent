# Cloud.ru P1: исполняемый runbook до создания ВМ
Дата: 2026-10-13. Статус: подготовка, **ничего не создано**. Проект Cloud.ru: `20853297-65b7-42a8-af40-25c8d2df4e11`. Секрет в переписке СКОМПРОМЕТИРОВАН - отозвать через IAM до любой работы. Новый ключ не записывать в Git/чат.
## Baseline recommendation
Минимальная конфигурация - отдельная UI VM с выделенным публичным IPv4 + core VM только с приватным адресом. UI reverse proxy не получает управление release без аутентификации. API модели доступен только backend. PostgreSQL graph read-model + существующий knowledge-1. На core отдельные logical domains с раздельным state/ACL; Kafka для первой итерации допускается только после проверки memory budget. Не менять действующие механизмы научного ядра для демо. Никаких Kubernetes/GPU/managed Neo4j.
### Прямо подтверждённые примеры опубликованных ставок Cloud.ru
Опубликованная документация VM использует **пример**, а не текущий коммерческий прайс: VM 1 vCPU/2 GiB 30% CPU = 0,88452 ₽/ч; 4 vCPU/32 GiB 100%=11,844 ₽/ч; boot disk 0,0156 ₽/GiB-ч; IP 0,204 ₽/ч. **Не выбирать VM 1 vCPU/2 GiB как фактически подтверждённый тариф UI 2/4 и не считать эти примеры фиксированными ценами.**
Для иллюстрации: 4/32 core * 160 часов = 1 895,04 ₽ compute; диск 200 GiB на 720 часов при примерной ставке = 2 246,40 ₽; IP на 720 ч = 146,88 ₽. UI 24/7 оплачивается отдельно по выбранному flavor. 4/32 core может быть слишком слабым для полного Kafka+PostgreSQL+3 domains+agent graph; прежде выполнить короткий load/health pilot. При необходимости upgrade без архитектурной миграции.
Сумма известной части иллюстрации: **4 288,32 ₽**, к ней прибавить UI compute, UI disk, snapshots, NAT/egress если платный, Foundation Models и прочие SKU. Окончательная сумма НЕ подсчитана, пока не определены актуальные flavors и тарифы интерфейса.
Вариант более мощного 8/64 core, по примеру 23,688 ₽/ч: 160ч = 3 790,08 ₽ compute, +200 GiB disk 2 246,40 ₽; применим для интеграционного стенда, но RAM/CPU выбираются после profiling. Всегда работает лишь UI; core включается по расписанию и перед интервью. При остановке VM disk и IP остаются тарифицируемыми.

## Как запустить без утечки ключа
1. В личном кабинете Cloud.ru -> IAM/API keys удалить ранее опубликованный keyId и создать новый с минимально необходимыми правами. Ключ хранить локально в менеджере секретов/переменных окружения, не передавать ассистенту.
2. Открыть Cloud.ru Evolution для проекта по ID; подтвердить статус счета/гранта, регион/зону, quotas на 2 VM, сети/VM flavors, наличие публичных адресов.
3. Проверить корзину до подтверждения создания: UI 2 vCPU/4 GiB (или ближайший доступный) и boot 30 GiB; core 4 vCPU/32 GiB или 8 vCPU/32-64 GiB, disk 150-200 GiB; 1 public IP; private subnet; snapshots/NAT по необходимости.
4. В `Контроль затрат` поставить бюджетные уведомления 50/75/90%; если hard cap технически недоступен, это только уведомления, назначить ручную остановку.
5. Зафиксировать текущие стоимость ₽/час каждой VM и ₽/GB-hour диска, public IP и SNAT, лимиты Foundation Models. Внести в матрицу ниже, получить письменное GO по **полной** оценке до provisioning.
6. После согласования: сеть -> security groups -> private core VM -> UI VM -> public IP -> TLS -> auth -> demo scenarios -> metrics/backups -> E4 только на отдельно запланированной топологии.
7. Для изоляции E1 остановить публичный демо-трафик или использовать отдельное окно/стенд. Версии образов, commit SHA и manifests сохранять для воспроизводимости.
8. Restore drill, deny public Kafka/Postgres, smoke-test 3 исходов, бюджета и rollback до приглашения внешних пользователей.

## Price form to populate in console
| SKU | Usage / month | Actual tariff incl VAT | Projected cost |
|---|---:|---:|---:|
| UI VM 2/4 | 720 h | UNKNOWN | UNKNOWN |
| Core VM 4/32 or 8/32-64 | 160 h (pilot) | UNKNOWN | UNKNOWN |
| UI system disk 30 GiB | 720 h | UNKNOWN | UNKNOWN |
| Core storage 150-200 GiB | 720 h | UNKNOWN | UNKNOWN |
| Dedicated public IP | 720 h | UNKNOWN | UNKNOWN |
| Egress/NAT, snapshots, backups | quote | UNKNOWN | UNKNOWN |
| Model tokens input/output | instrumented | depends model | UNKNOWN |
| TOTAL incl reserve 25% | | | NOT YET KNOWN |

## Guardrails
- Cost: UI continuously only if needed; core off by schedule; no always-on 2nd compute VM unless justified; tokens limited per run and per day; log rotation and short synthetic Kafka retention; delete unused snapshots/disks/IP; alert without assuming a hard stop.
- Performance: size core for combined Kafka+Postgres+agents with >=25% RAM headroom; reserve disk space; healthchecks; memory limits + restart; realistic demo concurrency (1-3 users), no E1 load during interviews. Upgrade core VM vertically first; scale to three physical nodes only for E4.
- Data integrity: immutable snapshots and per-domain source of truth, V2 final authorization, missing consumer -> NEEDS_REVIEW, no approval from model output.
- Public security: only 443 inbound, TLS, auth, rate limits, synthetic data, no API secrets in JS, SSH only through narrow allowlist/VPN.

## Authoritative documentation to recheck
https://cloud.ru/docs/virtual-machines/ug/topics/pricing
https://cloud.ru/docs/public-ip/ug/topics/pricing
https://cloud.ru/docs/public-ip/ug/topics/guides__allocate-ip
https://cloud.ru/docs/terraform-evolution/ug/topics/reference/resources/cloudru_evolution_compute_vm
https://cloud.ru/docs/tutorials-evolution/list/topics/vm__vm-terraform
https://cloud.ru/docs/foundation-models/ug/topics/pricing

## Next required from author
**One action, not a questionnaire**: revoke the exposed key and open the Cloud.ru project console. Share screenshot of current VM flavor selection/pricing, or the displayed eligible instance price table, without any API key. Then calculate exact total and approve before clicking Create.
