# Protected Cloud.ru runtime: BLOCKED

Final observation: 2026-10-18 16:48 UTC. PR23; main and managed demo unchanged. No LLM calls, VM recreation, tariff change, broad SSH opening, full verifier execution or new paid resource.

Product source already staged: `107dfd14292a5ab06593d424bf0b94f1cccb0b90`, tree `540a48cc47d87d1656e744aa20ab996d6af7bca8`. Runtime controller tested: `f5cd5f26f3b29bd9b6597d5ba5d9c78768784388`. Prepared configuration and acceptance checks are implementation, not a passed cloud deployment.

| Capability | Actual status |
|---|---|
| Cloud UI | BLOCKED: no authenticated browser acceptance, HTTPS not confirmed |
| New agent runs | UNAVAILABLE; server boundary rejects enqueue |
| New independent checks | UNAVAILABLE; local executor not qualified |
| Saved demonstrations | AVAILABLE in source/CI as explicit REPLAY; cloud access BLOCKED |
| Automatic application | BLOCKED, unchanged |
| Resource qualification | NOT PERFORMED on target scenario |

## Evidence and unsuccessful attempts

Every deployment attempt remains visible in Actions. The initial runtime attempt reached pinned authenticated OS and rechecked source/tree, but native Docker build exited 1 before containers started. It created private preparation directories and a private runtime secrets file; this report does not claim the VM was untouched. Exact native build stderr has not yet been retrieved because subsequent attempts could not reach the guest. Images now build/export in trusted CI without cloud credentials; this successful build is not a VM runtime success.

| Run | Result |
|---|---|
| [39119453665](https://github.com/rengalaxies/agent/actions/runs/39119453665) | 60-second TCP readiness timeout; cleanup passed |
| [39119769324](https://github.com/rengalaxies/agent/actions/runs/39119769324) | connection failure before mutation; queued retry cancelled |
| [39119769469](https://github.com/rengalaxies/agent/actions/runs/39119769469) | pinned/authenticated read-only SSH qualification passed after 64.21 seconds |
| [39119966922](https://github.com/rengalaxies/agent/actions/runs/39119966922) | guest survey/source check passed; native Docker build failed |
| [39120467480](https://github.com/rengalaxies/agent/actions/runs/39120467480) | API HTTP failure before runtime; final actual SG audit passed |
| [39120869989](https://github.com/rengalaxies/agent/actions/runs/39120869989) | Terraform plan read failed, no cloud mutation |
| [39120869986](https://github.com/rengalaxies/agent/actions/runs/39120869986) | CI images built; Terraform apply failed; cleanup/final SG audit passed |
| [39121182509](https://github.com/rengalaxies/agent/actions/runs/39121182509) | VM API 504 before mutation |
| [39121655343](https://github.com/rengalaxies/agent/actions/runs/39121655343) | SG gRPC read unavailable during plan |
| [39122134128](https://github.com/rengalaxies/agent/actions/runs/39122134128) | VM API 503 after bounded safe reads; final SG audit passed |
| [39125140553 attempt 1](https://github.com/rengalaxies/agent/actions/runs/39125140553/attempts/1) | fresh VM/NIC/SG match, own /32 created; 24 TCP timeouts/188.11 sec; own rule absent and final actual SG audit passed |
| [39125140553 attempt 2](https://github.com/rengalaxies/agent/actions/runs/39125140553/attempts/2) | same failure, fresh runner 172.184.247.4; 24 TCP timeouts/188.10 sec; own rule absent and final actual SG audit passed |
| [39125218197](https://github.com/rengalaxies/agent/actions/runs/39125218197) / [39125410129](https://github.com/rengalaxies/agent/actions/runs/39125410129) | read-only same-runner Raven TCP/TLS controls; target public port 80 also timed out |

The two final attempts passed 21 infrastructure unit checks, the authentication/application/verifier boundary test, and pinned image build/export. Neither reached SSH host-key negotiation or authentication. No runtime images or new containers were delivered by these attempts. Final live SG: original operator /32 only for TCP22, public TCP80/443, no broad administrative rule; exact original operator source hash is retained in network-final.json.

See RAVEN-COMPARISON.md for observed differences, exact remaining uncertainty, console commands and the targeted support-request draft. Support was not messaged by this agent. The executor has not obtained a browser console session or read a new support response.

## Prepared delivery after network recovery

See infra/cloudru/runtime/PLACEMENT.md. One UID10001 web/worker, private PostgreSQL and RabbitMQ, persistent SQLite/state, non-root Caddy, total memory caps 1536 MiB, CPU quotas 2, no Docker socket. CI artifact digests identify exact images; runtime scripts verify staged source and image identities before service actions. Existing port80 nginx is retained. Candidate hostname is `45-151-31-140.sslip.io`; it is not a working access handoff. Original admin password remains with its owner; no password is published here.

After packet-path recovery, run the existing protected-runtime workflow once: verify current attachment, temporary /32, pinned SSH, staged identity, load CI images, start isolated runtime, obtain trusted certificate, test all-route authentication and three scenarios, session isolation/reset/restart persistence, apply rejection and verifier no-job boundary, response secret checks and cgroup peaks/OOM/remaining host RAM, then revoke temporary acceptance identity and temporary SSH rule. Only those passing actual checks permit READY. T13/T14 are not promoted by this work; normal settled-session restart is not an interrupted-action recovery test. Backup/restore instructions and interview script are prepared; no restore drill or cloud interview success is claimed.
