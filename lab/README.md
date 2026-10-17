# PostgreSQL / RabbitMQ experimental lab

This is an isolated implementation candidate. Cloud.ru VM deployment and real-model execution remain unqualified. Read `status.md` for actual evidence; a successful CI job is not full acceptance of T01-T19.

## Components and boundaries

`app/service.py` implements Orders, transactional PostgreSQL outbox, RabbitMQ publisher, Billing consumer with durable deduplication, Analytics SQL views and the controlled S0-S5 transition. They are separately callable processes in one application image. This is a quiescent, controller-driven experiment, not a production service mesh. PostgreSQL has separate source/Billing databases and owner roles; evaluator reads use a separate SELECT-only role. RabbitMQ queues/messages and database volumes persist across container restarts. No database, broker or management ports are published.

`runtime/run.py` makes separate real analyst/executor model calls, writes an actual bounded SQL candidate and invokes the independent evaluator. The supported generated patch is only `lab/sql/expand.sql`; arbitrary service repair is not implemented. The model receives repository sources and declared requirements but no evaluator files. `runtime/dispatch.py` applies one explicit S1-S5 action after fresh verification and an exact expiring grant. It is an operator API, not a public command endpoint. There is no production merge/deploy tool.

`evaluator/expectations.json` contains the original specification's T01-T19 matrix and independently fixed amounts. `FREEZE.sha256` detects expectation changes. `tests/integration.py` executes real database/broker checks; uncovered cases retain NOT_RUN/BLOCKED. A finance-only candidate PASS does not prove R6-R8 or full T03. `evaluator/protocol.json` defines the three future comparison modes; manual labor and commercial savings are NOT_MEASURED.

## Exact version and clean setup

Use a reviewed exact 40-character commit. The CI workflow resolves PostgreSQL, RabbitMQ and Python image digests and records the built application image ID with the source commit. Use those verified digests for deployment; default version tags alone are insufficient for a frozen experiment. Python wheels are hash-locked for CPython 3.12 Linux amd64.

On an already qualified Docker host, create a private environment file outside Git, with a fresh password for each of `PG_ADMIN_PASSWORD`, `ORDERS_PASSWORD`, `BILLING_PASSWORD`, `VERIFIER_PASSWORD`, `RABBIT_PASSWORD`. Use hex characters for the connection strings. Set `POSTGRES_IMAGE`, `RABBITMQ_IMAGE`, `PYTHON_IMAGE` to the recorded `repository@sha256:...` values, and `LAB_APP_IMAGE` to an isolated image name. Never paste passwords into reports or run `docker compose config` into public logs.

Run from the repository root; replace the example environment path with the private file:

```sh
docker compose --env-file /secure/lab.env -p dmrp-money-lab -f lab/compose.yaml build app
docker compose --env-file /secure/lab.env -p dmrp-money-lab -f lab/compose.yaml up -d --wait postgres rabbitmq
docker compose --env-file /secure/lab.env -p dmrp-money-lab -f lab/compose.yaml run --rm bootstrap
docker compose --env-file /secure/lab.env -p dmrp-money-lab -f lab/compose.yaml run --rm app create-order --order-id demo-125 --amount-rub 125
docker compose --env-file /secure/lab.env -p dmrp-money-lab -f lab/compose.yaml run --rm app publish
docker compose --env-file /secure/lab.env -p dmrp-money-lab -f lab/compose.yaml run --rm app consume
docker compose --env-file /secure/lab.env -p dmrp-money-lab -f lab/compose.yaml run --rm verifier
```

The standalone transition CLI is a trusted fixture/controller tool. It does not establish agent authorization. For the agent path use `runtime/dispatch.execute` with a scoped grant and freshly verified candidate; never expose the fixture CLI to an untrusted model.

## Repeat the independent application scenario

The integration suite requires a **fresh empty** dedicated Compose project; do not run it against existing experiment data. CI automates setup, main suite and a second independent project for the deliberately broken control. It publishes sanitized JSON and immutable image manifests:

```sh
python -m unittest discover -s infra/cloudru/lab -p 'test_*.py'
docker compose --env-file /secure/lab.env -p dmrp-money-fresh -f lab/compose.yaml up -d --wait postgres rabbitmq
docker compose --env-file /secure/lab.env -p dmrp-money-fresh -f lab/compose.yaml run --rm bootstrap
mkdir -p /tmp/lab-evidence
chmod 0777 /tmp/lab-evidence
docker compose --env-file /secure/lab.env -p dmrp-money-fresh -f lab/compose.yaml run --rm --entrypoint python -v /tmp/lab-evidence:/evidence app -m lab.tests.integration --output /evidence/integration.json
```

For the broken control repeat setup with another fresh project, then pass `--broken-only` and a different output filename. Test mutation hooks and the broad scenario controller stay in this isolated test contour.

## Model and execution

The live runtime requires `CLOUDRU_FOUNDATION_API_KEY` and `CLOUDRU_LLM_MODEL`; see `runtime/README.md` for model limits, exact API and separate permissions. IAM and Workflow keys are not assumed to be inference keys. `--mode dry-run` exercises discovery only. A missing key yields BLOCKED with zero calls. Use a fresh audit directory per run:

```sh
python -m lab.runtime.run --intent-file lab/catalog/change.example.json --output /audit/change-unique --mode live
```

The host-controlled isolated candidate evaluator requires Docker and explicit `LAB_ENABLE_ISOLATED_VERIFIER=1`; it never runs candidate Python. Its disposable project is distinct from the target transition project. A real repair experiment must use a genuinely broken candidate; formatting the correct reference SQL is not a repair result.

## Transition and recovery

S1 expands/backfills `amount_minor` without changing `amount_rub`; S2 enables the version-aware Billing implementation; S3 introduces Analytics v2; S4 persists a pause/watermark, drains outbox/queue and switches routing with a delivery probe; S5 reconciles every order and both totals. Source/Billing effects are checked independently of publisher confirms. Delivery is at least once with idempotent business effects, not an exactly-once transport claim.

The authoritative initial profile uses integer rubles. While v1 exists, 12345 or 12501 minor units must be rejected without rounding. The uploaded 123.45 RUB example conflicts with this profile. Supporting it requires an explicitly revised decimal-v1 contract or separately accepted S6 retirement. Neither is silently inferred. S6 is not implemented.

Stop only this lab with the same environment file and project name using `docker compose ... stop`. Restart using `up -d --wait postgres rabbitmq`; retain volumes. Do not use `down --volumes` on target data. For an interrupted transition first capture `app snapshot`, queue/binding state and dispatcher journal; an UNKNOWN dispatcher outcome blocks retry until reconciliation. Resume only the verified allowed step. Re-running bootstrap does not rotate passwords in existing roles. Backup/restore and independent-operator T19 acceptance are still unqualified; do not claim them from volume configuration alone.

## Cloud.ru and subsequent adapters

Only project `20853297-65b7-42a8-af40-25c8d2df4e11` is authorized. Run the read-only preflight before host deployment. A retained recovery key and an open TCP22 do not prove a trusted authenticated OS channel. Core startup, host measurements, FIT decision, exact image delivery, persistence verification and business acceptance must precede a VM-ready claim. See `../infra/cloudru/lab/README.md` and `../docs/lab-cloudru-tools-2026-10-17.md`.

Kafka is not deployed. Its future adapter must separately model topic/partition/key, consumer groups, offsets/replay, retention, ordering, schema compatibility and deduplication. RabbitMQ exchange/binding/queue results do not qualify that adapter.
