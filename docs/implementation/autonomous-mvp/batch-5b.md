# Пачка 5Б: коробка на ВМ Cloud.ru, офлайн-часть

Задача [#53](https://github.com/rengalaxies/agent/issues/53), вторая часть. Ветка
`claude/mvp-5b-cloudru` от `main` `0f0dc02`.

В облаке ничего не создано. `terraform apply` не запускался, workflow не запускались,
ни один API Cloud.ru не вызывался. Terraform на машине разработки не установлен, поэтому
`terraform fmt` и `terraform validate` здесь не выполнены: их делает
`cloudru-box-validate.yml` на pull request.

## Сверка 26.10.2026

В облаке по-прежнему ничего не создано: ни `lock-test`, ни `plan`, ни `apply` не запускались.
Ниже то, что проверено существующим доступом без записи.

| Что | Как проверено | Результат |
|---|---|---|
| Среды GitHub | API `environments` и `deployment-branch-policies` от аккаунта исполнителя `swan-Dive` (право `write`, не admin) | `cloudru-box-production` и `cloudru-box-review`: required reviewers `rengalaxies` и `swan-Dive`, branch policy только `main`, `can_admins_bypass: true`, `prevent_self_review: false`. Секретов и переменных уровня среды нет: workflow берёт секреты репозитория |
| Защита `main` | API `branches/main`, `rulesets` | branch protection выключена, rulesets нет |
| Квоты | [run 40266720846](https://github.com/rengalaxies/agent/actions/runs/40266720846) `cloudru-discovery.yml` на `c64c949`, только data sources | проект: `network.ip.quantity` лимит 3, занято 2; `compute.vcpu` лимит 16, занято 4; `compute.ram` без лимита, занято 12. Организация: IP лимит 5, занято 3; vCPU 16, занято 7; RAM 68, занято 18. Первый apply (1 IP, 2 vCPU, 4 GiB) помещается |
| Инвентаризация проекта | тот же прогон | 2 ВМ, 2 диска, 2 IP, 1 подсеть, 1 NAT: это P1. Ресурсов с именем `amvp-box-*` нет |
| Права ключа на чтение | тот же прогон | чтение проекта, квот и коллекций Compute работает |
| Права ключа на создание и удаление | не проверено | без настоящего запроса на создание не доказать. Первый `apply` и есть эта проверка; при отказе guard ничего не удаляет, а `status` покажет, что успело создаться |
| Тарифы | HTML таблицы «Тарифы Evolution Compute», версия 261014, действует с 14.10.2026, НДС 22% | ставки сметы ниже совпали с прежними; ставка SSD теперь проверена |

Замечания по средам. `swan-Dive` (исполнитель) сам числится reviewer в обеих средах, и
самопроверка не запрещена. Исполнитель не одобряет развёртывания, которые сам запустил: это
делает владелец. Чтобы это обеспечивала сама платформа, владельцу стоит включить
`prevent_self_review` в `cloudru-box-production` (тогда запустивший run не может его
одобрить). `can_admins_bypass: true` позволяет администратору обойти правило; для
`cloudru-p1-production` он выключен, для коробки стоит выключить так же.

## Состояние

| | Что |
|---|---|
| Сделано | топология одной ВМ (Terraform), первая установка тем же `box` из 5А через cloud-init, read-only инвентаризация проекта, классификация владения, восстановление прерванного apply, reviewed plan digest, TTL, ledger и cleanup только своих ресурсов, тест блокировки state, защищённый workflow, офлайн-workflow проверок |
| Проверено офлайн | 41 unit-тест (Windows, Python 3.14.5, Git Bash для `provision.sh`); 7 внесённых дефектов, каждый ловится тестом; CLI `boxctl.py` прогнан на фикстурах; оба workflow разобраны PyYAML 6.0.3, actionlint 1.7.7 без замечаний (shellcheck не установлен); `bash -n provision.sh` |
| Не проверено | всё, что требует облака: права, квота, provider schema, cloud-init на ВМ Cloud.ru, блокировка на пути `terraform/box/`, цены на сегодня. Список в разделе «Что не проверено» |

## Что уже есть в проекте

Проект `20853297-65b7-42a8-af40-25c8d2df4e11`, зона `ru.AZ-2`. Чужие проекты код не читает:
`project_id` закреплён валидацией в обоих Terraform-корнях и проверяется в каждой записи
инвентаризации, state и плана.

- В проекте живут ресурсы P1 (отчёт `lab/reports/access-2026-10-18/REPORT.md`): ВМ
  `dm-p1-ui` (gen-2-4, включена, публичный IP `33a27f64...`), ВМ `dm-p1-core` (выключена),
  их диски 30 и 80 GiB, sNAT `dm-p1-core-snat`, группы безопасности. Их state лежит в
  `test-bucket-ds` под `terraform/p1/`. Коробка их не трогает и не переиспользует: issue
  #6 держит по этой топологии NO-GO. Инвентаризация коробки считает их чужими (`foreign`),
  guard не пропустит план, который их меняет или удаляет.
- Эти ресурсы P1 продолжают тарифицироваться, около 3,7 тыс. ₽ за 30 дней (UI-ВМ 720 ч,
  диски 110 GiB, IP, sNAT; по ставкам ниже). Это решение владельца, вне 5Б.
- Issue #9: `READY_FOR_STATE_TEST`, все защищённые значения в GitHub есть. Проверяет только
  наличие и форму, не права.
- Issue #10: `READ_ONLY_PASS`, чтение бакета есть. Строка `Lockfile: NOT_TESTED` в этом
  issue записана в workflow константой и не отражает прогоны. Шаг «Verify real encrypted S3
  backend and concurrent lock» в run
  [38458566308](https://github.com/rengalaxies/agent/actions/runs/38458566308) 13.10
  завершился success (прочитано через API jobs): SSE-C state и lock, отказ второму клиенту,
  чтение из свежего каталога. Это было на `test-bucket-ds`, под `terraform/p1/backend-probe-*`,
  общим ключом проекта. Для пути и ключа коробки это не доказательство.
- Права на создание ресурсов у ключа `CLOUDRU_KEY_ID` были 13.10 и 18.10: protected apply
  run [38466919178](https://github.com/rengalaxies/agent/actions/runs/38466919178) создал
  диски и sNAT, lab-прогоны 18.10 создавали и удаляли правила SG. Права на сегодня этим не
  доказаны.

## Топология

Один корень `infra/cloudru/box/main.tf`, 11 ресурсов на первый apply (10, если SSH не
открывать). Имена: `amvp-box-<box_id>-<вид>`, `box_id` из 3-16 строчных букв и цифр без
дефиса. Ниже для `box_id = pilot1`.

| Ресурс | Имя | Параметры |
|---|---|---|
| ВМ | `amvp-box-pilot1-vm` | `gen-2-4` (2 vCPU, 4 GiB), образ `Ubuntu-24.04` `fe51a6e6-...` (python3.12 и git есть), пользователь `boxadmin` с ключом владельца, cloud-init из раздела «Первая установка» |
| Загрузочный диск | `amvp-box-pilot1-boot` | 20 GiB SSD, `encrypted = true` |
| Интерфейс | `amvp-box-pilot1-nic` | существующая подсеть проекта `d58e80ef-fff1-43eb-b601-96fb358224b7` (10.0.0.0/24), только чтение, не управляется |
| Публичный IPv4 | `amvp-box-pilot1-ip` | на интерфейсе ВМ |
| Группа безопасности | `amvp-box-pilot1-sg` | описание `amvp-box:pilot1 managed by infra/cloudru/box` |
| Правила egress, 5 шт. | | TCP 443, TCP 80, UDP 53, TCP 53, UDP 123 в `0.0.0.0/0` |
| Правило ingress, 0 или 1 | | TCP 22 только с `/32` владельца; пусто, значит входящих правил нет |

Почему такой размер. Сервис после установки занимал 66 МиБ RSS (67 316 KiB на раннере
GitHub, ubuntu-24.04, PR #60), установка с нуля 7,1 с. 5А называла ориентир 2 vCPU, 2 GiB,
но в каталоге проекта (run 38599890963) нет 2 vCPU меньше 4 GiB. `gen-2-4` самый маленький
flavor с полной долей CPU и единственный с проверенной ценой. `low-2-4` и
`lowcost10-2-4` в каталоге есть, их цены в репозитории нет (UNVERIFIED), а доля CPU 10%
может растянуть построение графа на репозиториях компании, которое ещё не замерено. Память
на репозиториях компании тоже не замерена, запас в 4 GiB это покрывает. Переход на
`gen-2-8` разрешён переменной без пересоздания топологии.

Диск 20 GiB: образ требует минимум 10 GiB, остальное занимают ОС, релиз с venv (архив 9 МБ),
Git-зеркала компании (размер неизвестен) и до 7 ежедневных копий SQLite. Разница с 10 GiB
114 ₽ в месяц.

Почему публичный IP, а не NAT. Коробке нужен только исходящий трафик: GitHub (зеркала,
API, скачивание релиза), Jira, Foundation Models API. Webhook выключен, сервис сверяется
сам раз в 15 минут. IP и sNAT стоят одинаково, 0,2074 ₽/ч. Свой sNAT ради одной ВМ дороже
не будет, но не даёт входа по SSH, а через него владелец доставляет секреты. sNAT P1 уже
оплачивается, но принадлежит state P1 с `prevent_destroy`, его исходящий путь не проверен,
и коробка стала бы зависеть от чужого жизненного цикла. Поэтому один IP на ВМ. Если
владелец после установки закроет SSH (apply с пустым `admin_cidr`), входящих правил не
останется, IP останется только для исходящего трафика.

Квота: 13.10 apply P1 упал на `Organization quota for network.ip.quantity exceeded`.
Инвентаризация читает квоты и не даёт планировать, если места под ещё один IP нет.

## Первая установка

cloud-init (`local.cloud_init` в `main.tf`) кладёт на ВМ только несекретное:
`/etc/agent-service-box-provision/release.env` (URL, sha256, имя релиза),
`/usr/local/sbin/agent-service-box-provision` (это `provision.sh`) и два unit systemd. Затем
запускает провизию один раз.

`provision.sh`, каждый шаг идемпотентен:

1. скачивает архив релиза только с `https://github.com/rengalaxies/agent/releases/download/`,
   сверяет sha256 с закреплённым; несовпадение удаляет архив и останавливает всё;
2. распаковывает, если верхний каталог архива ровно имя релиза;
3. ждёт `/etc/agent-service/box.yaml` и `/etc/agent-service/secrets.env`, фазы
   `waiting_for_config` и `waiting_for_secrets`;
4. запускает `./box install --config /etc/agent-service/box.yaml`, затем `./box doctor`.
   Код 0 даёт `installed_ready`, 2 `installed_not_ready`, 1 `install_failed`.

Итог пишется в `/var/lib/agent-service-box-provision/status.json`, вывод в
`/var/log/agent-service-box-provision.log`. Установщик тот же, что в 5А, копии или форка
нет. Обновления релиза потом идут через `box update` на ВМ; Terraform игнорирует изменения
`cloud_init_userdata` и ВМ из-за них не пересоздаёт.

### Как секреты попадают на ВМ

Секреты не проходят через Terraform-переменные, state, user-data, GitHub и логи workflow.
Владелец копирует файлы по SSH со своей машины (ключ из `CLOUDRU_SSH_PUBLIC_KEY`, вход с его
`/32`):

1. сверить отпечаток host key ВМ с выводом cloud-init в консоли ВМ Cloud.ru (VNC/serial),
   как с `ui-host-pin.json` в lab, и только потом подключаться;
2. сначала ключ GitHub App, потом `box.yaml`, последним `secrets.env`: запись
   `secrets.env` запускает установку (`agent-service-box-provision.path`, `PathChanged`).

```bash
ssh boxadmin@<ip> 'sudo install -d -m 755 /etc/agent-service && sudo sh -c "umask 077; cat > /etc/agent-service/github-app.pem.tmp && mv /etc/agent-service/github-app.pem.tmp /etc/agent-service/github-app.pem"' < github-app.pem
```

```bash
ssh boxadmin@<ip> 'sudo sh -c "umask 022; cat > /etc/agent-service/box.yaml.tmp && mv /etc/agent-service/box.yaml.tmp /etc/agent-service/box.yaml"' < box.yaml
```

```bash
ssh boxadmin@<ip> 'sudo sh -c "umask 077; cat > /etc/agent-service/secrets.env.tmp && mv /etc/agent-service/secrets.env.tmp /etc/agent-service/secrets.env"' < secrets.env
```

Значения идут через stdin и в аргументы команд не попадают. `provision.sh` ставит на
`secrets.env` владельца root и права 600 и не читает его. `box` печатает имена переменных,
не значения (5А, сценарий `doctor_wrong_credentials`). После `installed_ready` владелец может
закрыть SSH: новый plan и apply с пустым `ssh_admin_cidr` удаляют одно правило, guard это
разрешает.

## Plan, apply, status, cleanup

Чистая логика в `infra/cloudru/box/ownership.py`, команды в `boxctl.py`, порядок шагов в
`.github/workflows/cloudru-box.yml`.

Инвентаризация перед каждым планом. Корень `inventory/main.tf` только читает: коллекции ВМ,
дисков, публичных IP и подсетей (те же data sources, что в `infra/cloudru/inventory.tf`) и
квоты (как в `cloudru-discovery.yml`). В выход попадают id, имена и статусы, адресов нет.
`boxctl.py classify` делит живые ресурсы:

| Класс | Правило | Что дальше |
|---|---|---|
| owned | имя ровно `amvp-box-<id>-<вид>` и id есть в state | план их не дублирует |
| orphan | имя коробки, id в state нет: apply прервался после создания | план запрещён; владелец выбирает `adopt` (import) или удаляет сам |
| duplicate | два живых ресурса с одним именем коробки | план запрещён до решения владельца |
| missing | в state есть, в проекте нет | отчёт; план создаст заново |
| foreign | всё остальное, включая P1 и `amvp-box-pilot1-vm-copy` | не трогается никогда |

Совпадения по префиксу недостаточно, это проверяет тест. Коллекций для групп
безопасности, правил и интерфейсов среди проверенных data sources нет, поэтому сироты этих
видов не видны. Они бесплатные; все платные виды (ВМ, диск, IP) покрыты.

Восстановление прерванного provisioning:

- повторный apply идемпотентен: созданное записано в state, план создаёт только остаток;
- интерфейс, который provider пометил tainted после создания (так было в P1), снимается с
  пометки вместо пересоздания; остальные tainted ресурсы план пересоздаёт, guard это
  разрешает только для tainted. Операция `plan` state не пишет: `recover` только перечисляет
  адреса, `boxctl.py recovery-copy` копирует конфигурацию и скачанный state во временный
  каталог с override на локальный backend и снимает пометку там, review-план считается на этой
  копии с `-lock=false`. Список адресов входит в проекцию (формат `amvp-box-plan-2`), значит и
  в digest. Настоящий `terraform untaint` выполняет только одобренный `apply`: сначала он
  повторяет план на копии и сверяет digest, потом пишет state, строит план на настоящем backend
  и сверяет digest ещё раз (`test_recovery.py`: ни один шаг plan, destroy-plan и status не
  пишет state, `untaint` есть только в apply);
- ресурс, созданный без записи в state, становится orphan; вход `adopt=vm=<uuid>` пишет
  `import`-блок только для настоящего сироты этой коробки;
- оставшийся после убитого раннера lock снимается `terraform force-unlock <ID>`. lock-test
  проверяет, что такой lock блокирует и снимается по точному ID.

Guard плана (`boxctl.py guard`). Apply: только 6 типов ресурсов коробки, только проект
`20853297-...`, только имена коробки, не больше 11 созданий, удаление или замена только
tainted ресурсов и правил SG, import только из списка `adopt`. Destroy: только удаления,
только записанных в state id, и все они.

Reviewed plan digest. План сводится к проекции: каждое изменение с before и after, где
чувствительные значения, адрес `/32` владельца и IP заменены тегом HMAC-SHA256 на ключе
`CLOUDRU_STATE_SSE_CUSTOMER_KEY`, а `cloud_init_userdata` своим sha256. Digest это sha256
проекции вместе с commit, `box_id` и режимом. Запуск `plan` печатает проекцию и digest в
summary. Запуск `apply` строит план заново из того же commit `main` и применяет его, только
если digest равен введённому. Файл плана между запусками не передаётся: в нём значения
переменных, включая ключи. Изменение мира между review и apply меняет digest, и apply
останавливается.

TTL. `expires_on` обязателен для plan и apply, не дальше 120 дней. Он записан в output
`ownership` в state и в ledger. На ресурсах его нет: поддержка `tags` в provider не
проверена, а смена описания SG могла бы пересоздать группу. `status` показывает остаток
дней и выходит с кодом 3 после срока. Автоматического удаления нет.

Ledger и cleanup. После каждого apply, и успешного, и упавшего, workflow пишет
`terraform/box/<box_id>.ownership.json` (SSE-C) из state: адреса и id. `destroy-plan`
проверяет destroy-план против state, ledger и инвентаризации: удаляется только то, что
записано и там, и там; сироты и чужие ресурсы перечисляются как оставленные. Расхождение
ledger и state или отсутствие ledger останавливает cleanup.

## Remote state и проверка блокировки

Backend S3 тот же бакет `vars.CLOUDRU_STATE_BUCKET`, отдельный ключ
`terraform/box/<box_id>.tfstate`, `use_lockfile=true`, `encrypt=true`, SSE-C ключом
`CLOUDRU_STATE_SSE_CUSTOMER_KEY`. Перед init workflow запускает
`infra/cloudru/deploy/check_state_bucket.py`: бакет приватный, версионирование включено,
тег проекта на месте. Учётные данные выбираются как в `cloudru-apply-protected.yml`:
отдельный ключ state, если он задан, иначе ключ проекта только для `test-bucket-ds`.

`boxctl.py lock-test` (операция `lock-test`) доказывает блокировку на настоящем бакете и
создаёт только два объекта `terraform/box/lock-probe-<run>-<attempt>.tfstate[.tflock]`:

1. пока идёт apply, lock-объект существует и зашифрован SSE-C;
2. второй клиент из другого каталога получает `Error acquiring the state lock`;
3. state зашифрован, без ключа не читается, свежий клиент его читает, повтор даёт пустой план;
4. убитый apply оставляет lock, lock по-прежнему блокирует, `force-unlock` по ID из lock-объекта
   его снимает.

Удаляются только версии этих двух ключей с точным сравнением имени (тест: префикс run 12
не задевает run 123 и `terraform/box/pilot1.tfstate`). Код не запускался.

## Workflow

`cloudru-box.yml`, только `workflow_dispatch`, без push и schedule. 9 входов: операция,
UUID проекта, `box_id`, `expires_on`, `/32` для SSH, digest, потолок ₽, фраза, `adopt`.

| Операция | Окружение | Что делает |
|---|---|---|
| `plan` | `cloudru-box-review` | проверка релиза (скачать, sha256), инвентаризация, init, classify, предложенное восстановление, план на локальной копии state, guard, проекция и digest в summary и artifact; state не пишется |
| `apply` | `cloudru-box-production` | то же на `main`, потолок не меньше 3300 ₽, фраза `AUTHORIZE-BOX-APPLY`, digest копии равен проверенному, затем `untaint` из проверенного списка, новый план на настоящем backend с тем же digest, `terraform apply` этого плана, ledger, status |
| `status` | `cloudru-box-review` | ресурсы, расхождения, сироты, TTL |
| `destroy-plan` | `cloudru-box-review` | destroy-план, guard, ledger, cleanup-check, digest |
| `destroy` | `cloudru-box-production` | на `main`, фраза `AUTHORIZE-BOX-DESTROY`, digest равен проверенному destroy-plan |
| `lock-test` | `cloudru-box-production` | тест блокировки на `main` |

Один `concurrency` на проект без отмены. Публичный IP в лог не попадает (output
`public_ip` sensitive), `/32` маскируется. `cloudru-box-validate.yml` на PR: unit-тесты,
`bash -n`, `terraform fmt -check`, `init -backend=false` и `validate` обоих корней с
provider из зеркала Cloud.ru, без секретов.

## Смета на 30 дней (720 ч)

Ставки сверены 26.10.2026 по таблице «Тарифы Evolution Compute» версии 261014 (действует с
14.10.2026, НДС 22%): строки «Виртуальная машина 2vCPU/4GB RAM» 2,9707 ₽/ч, «Диск SSD NVMe»
0,01586 ₽/ГБ·ч, «Аренда публичного IP адреса» 0,2074 ₽/ч, «Публичный IP адрес. Исходящий
трафик» 0,00366, строка 88 (хранилище резервных копий) 0,005856 ₽/ГБ·ч. Это публичный
прайс; скидки и условия гранта не учтены, фактический биллинг не измерен.

| Статья | Формула | ₽ | Статус ставки |
|---|---|---:|---|
| ВМ `gen-2-4` | 2,9707 × 720 | 2 138,90 | тариф 261014 |
| SSD 20 GiB | 20 × 0,01586 × 720 | 228,38 | тариф 261014 |
| Публичный IPv4 | 0,2074 × 720 | 149,33 | тариф 261014 |
| Исходящий трафик, допущение 5 GiB | 5 × 1024 × 0,00366 | 18,74 | ставка 261014; единица в HTML-таблице читается неоднозначно, взята за МБ (дороже); объём не замерен |
| Копии вне ВМ (снимок диска, необязательно) | 20 × 0,005856 × 720 | 84,33 | ставка 261014; копий вне ВМ пока нет |
| State и ledger в Object Storage | килобайты в существующем бакете | около 0 | UNVERIFIED |
| **Итого инфраструктура** | | **2 619,68** | |
| **С запасом 25%** | × 1,25 | **3 274,60** | потолок в workflow 3300 |

Копии `box backup` лежат на том же диске и входят в строку SSD. При выключенной ВМ диск и
IP продолжают тарифицироваться.

Модель (Foundation Models API) отдельно. Пока квалификация 2Б не дала QUALIFIED, секция
`model` в `box.yaml` пустая и расход 0. Ориентир из `batch-2b.md` (тариф 261023, ожидание по
допущениям, фактический биллинг NOT_MEASURED):

| Модель | ₽ за case-run, ожидание | Худший case-run, 12 запросов | 200 анализов в месяц |
|---|---:|---:|---:|
| `openai/gpt-oss-120b` | 1,00 | 15,6 | 200 |
| `Qwen/Qwen3-Coder-Next` | 4,42 | 108,7 | 885 |
| `Qwen/Qwen3.6-35B-A3B` | 9,31 | 190,2 | 1 862 |
| порог 2Б «в среднем не больше 20 ₽» | 20 | | 4 000 |

200 анализов в месяц это допущение, число PR и задач компании неизвестно.

## Ворота, которые ещё закрыты

0. Слияние #62 в `main`: `cloudru-box.yml` и `agent-service-release.yml` запускаются только с
   default branch.
1. Encrypted backend и блокировка на пути коробки: нужна операция `lock-test` со статусом
   PASS ключом, которым будет работать apply. Прошлый PASS 13.10 был на `terraform/p1/` и
   общим ключом.
2. Права на создание: у сервисного аккаунта `CLOUDRU_KEY_ID` в проекте должны быть
   создание и удаление ВМ, дисков, интерфейсов, публичных IP, групп безопасности и правил.
   Сегодня не проверено.
3. Квота `network.ip.quantity`: 26.10 в проекте занято 2 из 3, место под один IP есть
   (discovery 40266720846). `plan` проверит снова.
4. Опубликованный релиз: в `release.json` сейчас локальная сборка 5А `c8df16b`
   (`c0273146...`), такого asset нет, шаг проверки релиза упадёт до плана. Публикует
   `agent-service-release.yml` с принятого `main`, затем PR с новым pin.
5. Одобрение владельца этого плана: digest из запуска `plan` на `main` и потолок 3300 ₽.
6. Окружения GitHub: созданы владельцем, required reviewer и только `main` подтверждены через
   API 26.10. Остаётся `prevent_self_review` и `can_admins_bypass` (см. «Сверка 26.10.2026»).

## Что нужно от владельца

Не нужно повторно: создавать среды (созданы, проверены 26.10), подтверждать квоту IP
(проверена), собирать релиз (это делает `agent-service-release.yml`), выдавать ключ модели
(секрет `CLOUDRU_FOUNDATION_API_KEY` уже есть).

Нужно, по порядку:

1. Слить #62 после зелёного CI: без этого `cloudru-box.yml` не запускается.
2. Одобрить в GitHub (Actions, кнопка Review deployments) запуск `lock-test` в среде
   `cloudru-box-production`. Он создаёт только два объекта `terraform/box/lock-probe-*` и
   удаляет их; облачных ресурсов нет.
3. Одобрить запуск `plan` в среде `cloudru-box-review`. Plan state не пишет. Для SSH нужен
   свой публичный IPv4 `/32`; без него SSH-правило не создаётся.
4. Прочитать summary plan: список ресурсов, recovery, digest, смету. Затем отдельным
   сообщением одобрить конкретный apply: digest, `expires_on`, потолок ₽ в месяц.
5. Желательно в настройках сред: `prevent_self_review` в `cloudru-box-production` и
   `can_admins_bypass` выключить.

Секреты сервиса нужны только после того, как ВМ поднята, и только для живого контура:
приватный ключ GitHub App и её id и installation id, API token Jira с почтой и адресом сайта,
секреты webhook GitHub и Jira. Путь доставки описан выше («Как секреты попадают на ВМ»): три
команды `ssh` со своей машины, значения идут через stdin и не попадают в Terraform state,
user-data, GitHub и логи. Сборку `box.yaml` и диагностику исполнитель делает сам по выводу
`status`, владельцу отлаживать SSH не нужно. Упрощение до одной команды (например,
зашифрованный на открытый ключ ВМ пакет) не реализовано.

Порядок после этого: `lock-test` → `plan` → одобрение конкретного apply → `apply` →
сверить host key в консоли ВМ → три файла по SSH → `status` и `status.json` на ВМ → doctor
и readiness → сквозной smoke → `plan` и `apply` с пустым `/32`, чтобы закрыть SSH.

## Что не проверено

- `terraform fmt` и `validate`: terraform не установлен. Не проверено, что provider 2.1.3
  принимает `IP_PROTOCOL_UDP`, `image_metadata` вместе с `cloud_init_userdata` на одной ВМ
  (в P1 UI-ВМ шла с `image_metadata`, core с `cloud_init_userdata`, вместе ни разу) и
  import этих типов для `adopt`.
- Что cloud-init user-data вообще исполняется на ВМ Cloud.ru: bootstrap core P1 так и не
  подтверждён. Если не исполняется, `provision.sh` из репозитория запускается по SSH теми же
  файлами, с `release.env` рядом.
- Что ограниченный egress (443, 80, 53, 123) не мешает DNS подсети и сервису метаданных.
- Что `PathChanged` срабатывает на `mv` в `/etc/agent-service` на этой ВМ.
- Смысл полей квот (`individual_limit`, `aggregated_usage`) взят из discovery, не из документации.
- Объём трафика; фактический биллинг по сравнению с публичным прайсом.
- `lock-test`, `ledger-put`, `ledger-get`, все шаги workflow: код не выполнялся ни разу.
- Коробка на настоящей ВМ: память и время графа на репозиториях компании, живые GitHub и
  Jira, модель.

## Проверки этой сессии

```bash
python -m unittest discover -s infra/cloudru/box -p "test_*.py"   # Ran 41 tests, OK
```

```bash
bash -n infra/cloudru/box/provision.sh                            # OK
```

```bash
actionlint .github/workflows/cloudru-box.yml .github/workflows/cloudru-box-validate.yml   # 1.7.7, rc 0
```

PyYAML 6.0.3: оба workflow разбираются, у `cloudru-box.yml` единственный триггер
`workflow_dispatch` и 9 входов. Тесты `provision.sh` запускают скрипт настоящим bash на
настоящем tar.gz, `box` в архиве заменён заглушкой, сеть отрезана недоступным proxy.
Проверка тестов дефектами: префиксное совпадение имён, неточное удаление probe-объектов,
нераскрытый `/32` в проекции, разрешённая замена здоровой ВМ, игнор ledger, доверие
кешированному архиву с чужим sha256, установка без `secrets.env`. Каждый дефект уронил тест.

## Коммиты

| Коммит | Что |
|---|---|
| `05734eb` | топология одной ВМ, inventory-корень, `provision.sh`, unit systemd, `release.json` |
| `d7039d0` | `ownership.py`, `boxctl.py`, фикстуры и 41 тест |
| `896c2d2` | `cloudru-box.yml`, `cloudru-box-validate.yml` |
| этот | отчёт |
