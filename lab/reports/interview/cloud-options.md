# Cloud placement assessment

Read-only assessment, 2026-10-17 UTC / 2026-10-18 MSK. This document is not deployment evidence. No resources, permissions, inference or managed demo were changed for this assessment. Scope: project `20853297-65b7-42a8-af40-25c8d2df4e11`.

## Decision

The existing VM remains the preferred path, conditional on authenticated OS access, measured capacity and HTTPS/authentication. Evolution Container Apps is **BLOCKED as a drop-in deployment of the current prototype**. This is a compatibility conclusion, not a claim that the service cannot host a redesigned application.

| Requirement | Documented capability / current implementation | Assessment |
|---|---|---|
| API plus asynchronous worker | Cloud.ru documents background work in hot containers; cold instances can stop after an idle timeout. | Use one hot instance and one application process; scaling or multiple workers is outside tested coverage. |
| Durable SQLite WAL | Documented persistent volume is an Object Storage bucket; ephemeral storage disappears with the instance. The docs give SQLite as an example, but do not establish this application's WAL, locking, atomicity or crash-recovery semantics. | Do not move SQLite to this mount without specific validation. Current persistence/restart evidence does not transfer. |
| PostgreSQL and RabbitMQ | Official FAQ explicitly says Container Apps cannot connect to Managed PostgreSQL; exposing external DB ports publicly is called unsafe. No private routing guarantee for the existing VM broker was established here. | Private source DB/broker connectivity remains unproved; public DB/broker ingress is not an acceptable workaround. |
| Fresh independent verifier | `lab/evaluator/verify.py` requires Docker CLI/Compose, builds the trusted image, creates fresh PostgreSQL/RabbitMQ containers, mounts candidate SQL read-only and destroys its disposable project. | A normal API container does not satisfy this requirement. |
| Privileged execution | The runtime documents privileged mode and Docker-in-Docker. | Availability is not approval: do not give the public API host Docker privileges or socket access. A separate restricted executor would require implementation and fresh isolation tests. |
| Candidate isolation | Current candidate changes are restricted to `lab/sql/expand.sql`; application/evaluator code is trusted. Docker network, volumes and generated credentials isolate verifier runs. | Preserve this boundary; do not execute candidate SQL against the persistent interview database or production services. |

Sources: [background processes](https://cloud.ru/docs/container-apps-evolution/ug/topics/faq__container-stopped), [volumes](https://cloud.ru/docs/container-apps-evolution/ug/topics/concepts__volumes), [database connectivity FAQ](https://cloud.ru/docs/container-apps-evolution/ug/topics/faq__database-connection), [runtime and privileges](https://cloud.ru/docs/container-apps-evolution/ug/topics/concepts__runtime). These are primary Cloud.ru documentation pages checked for this assessment.

## Cost boundary

The [effective tariff, version 260918](https://cloud.ru/documents/tariffs/evolution/container-apps), effective 28 September 2026, lists 1.891 RUB/vCPU-hour and 1.256966 RUB/GiB-hour including the listed VAT treatment. [Container Services billing](https://cloud.ru/docs/container-apps-evolution/ug/topics/pricing__container-services) lists monthly allowances of 25 vCPU-hours and 50 GiB-hours. Remaining project allowance is unknown.

Illustrative compute-only envelope for one hot 1-vCPU/2-GiB instance: 4.404932 RUB/hour before allowance, 105.72 RUB for 24 hours, or 211.44 RUB for 48 hours. This is not a full deployment quote: database/broker hosts, verifier compute, registry/storage/operations, traffic, secret service and inference are excluded. No resources are reserved. A viable managed design needs a priced private data/executor/storage architecture, then explicit approval for new paid resources or expanded permissions under the task's specific constraint.

## VM security and delivery requirements

Existing `infra/cloudru/lab/README.md` records no authenticated OS channel or measured guest capacity. Exact state/API resource identity and independently pinned host key must pass before authentication. Run fixed read-only inventory before FIT; do not infer free capacity from flavor. Preserve current encrypted Terraform state/lock; no replacement, resizing or old protected apply.

Use an isolated lab directory/project/network and persistent local block-backed volumes, exact source SHA and image digests. Only HTTPS reverse proxy is public; server authentication protects every UI/API route. PostgreSQL, RabbitMQ management, broker ports and Docker API/socket remain private. Application collectors receive a SELECT/catalog role and monitoring-only broker credential; source/broker administrator credentials stay with the trusted controller. Keep one worker and permanent server-side apply denial.

**Concrete security gap:** the current worker invokes the Docker verifier synchronously in its own process. Running that public API process in the host `docker` group would confer host control even without a public Docker port. Safe placement must either separate verification into a narrow trusted executor/CI workflow, or disable new verification on the public web process and clearly present saved verifier evidence as REPLAY. Do not mount `/var/run/docker.sock` into the web container. A verifier handoff must bind exact candidate/source digests, bounded fixed operation, results and cleanup; no arbitrary shell or participant SQL interface.

Cloud acceptance still requires actual target readiness, browser path, persistence restart, stale revision behavior, mode provenance and direct apply-403 checks. CI-only evidence does not satisfy those checks.
