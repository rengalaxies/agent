# Placement and acceptance contract

Product source is the existing clean staged checkout of `107dfd14292a5ab06593d424bf0b94f1cccb0b90`, tree `540a48cc47d87d1656e744aa20ab996d6af7bca8`. Runtime boundary/controller has its own recorded commit. Delivery is not repeated. The runtime does not modify this checkout.

| Component | Placement | Memory cap | CPU quota | Persistence |
|---|---|---:|---:|---|
| Web + one existing sequential worker | UID/GID 10001 container, read-only root, all capabilities dropped | 640 MiB | 0.75 | `/opt/agent-cloud-runtime/state`: SQLite WAL, session registry, artifacts |
| PostgreSQL | Private Docker network, no host port | 384 MiB | 0.50 | named `postgres-data` volume |
| RabbitMQ | Private Docker network, no host port | 384 MiB | 0.50 | named `rabbit-data` volume |
| Caddy | UID/GID 10001, private + egress network; host 443 only | 128 MiB | 0.25 | private certificate/config directories |

Total caps: 1,536 MiB / 2 CPU; capacity remains unqualified until actual target scenario, kernel memory peaks, OOM counters, and remaining host memory are measured. This is a sequential interview stand, not a concurrent production capacity claim. PostgreSQL and RabbitMQ hold only the declared lab dataset. Bootstrap is a separate bounded controller action with temporary administrative credentials; web gets SELECT-only PostgreSQL and monitoring-only RabbitMQ credentials.

No Docker socket, SSH/cloud/GitHub/LLM credentials or database administrator password reach web. Docker `unless-stopped` restart policy persists the runtime. An independent root systemd timer re-attests monitoring-only broker permissions every five minutes. This controller does not execute user patches. The legacy collector source enum is retained for schema compatibility; the attestation issuer explicitly identifies the Cloud.ru root controller.

TLS candidate: `45-151-31-140.sslip.io`; DNS must resolve to the existing VM and public ACME TLS-ALPN-01 must succeed on 443 before HTTPS is claimed. Existing nginx port 80 is untouched. Caddy authenticates the whole origin with the existing `admin` bcrypt hash; the original password stays with its owner outside GitHub. A random short-lived acceptance identity is removed in `finally`; it is never an access handoff. The proxy substitutes a separate internal credential, and product middleware also authenticates all routes. UI role selection remains demonstrational.

New agents and fresh independent checks are UNAVAILABLE. Server rejects those jobs before enqueue. Historical receipts are a separate REPLAY route, including their original commit/run/input/candidate context; they never populate current verification results. Preparation from explicit REPLAY remains available. Application is always blocked by the existing server endpoint.

## Restart and recovery (only after confirmed installation)

Authorized operator on the VM:

```
sudo docker compose -f /opt/agent-cloud-runtime/compose.json ps
sudo docker compose -f /opt/agent-cloud-runtime/compose.json restart web
sudo systemctl start agent-cloud-attest.service
sudo docker compose -f /opt/agent-cloud-runtime/compose.json up -d --wait
```

Never use `down -v`. For a consistent backup, stop web and the attestation timer, stop PostgreSQL/RabbitMQ cleanly, and privately archive `/opt/agent-cloud-runtime` plus the two named Docker volume data directories. The archive includes secrets and TLS keys: keep it encrypted and do not upload it as public CI evidence. Restore only into the same stopped runtime with the recorded image digests, ownership and permissions, then start services and check authenticated readiness. No restore drill is claimed until performed.

## Interview script (pending cloud acceptance)

Open the confirmed HTTPS address and use `admin` with the previously retained UI password. Start “Подтверждённая зависимость”, save the provided change, collect LIVE catalog evidence, explicitly select REPLAY and analyze. Open billing/analytics cards; acknowledge the exact revision without granting application. Prepare the REPLAY patch; explain that fresh verification is unavailable and historical PASS is separate. Start “Неизвестный владелец” with explicit CONTROL analysis; observe the coordinator question. Start “Устаревание после новой ревизии”, analyze in REPLAY then create revision 2 and observe stale cards. Reset only the selected session.
