# Actual lab status - 2026-10-17

Overall: **проверенный агентный проход в CI; Cloud.ru deployment NOT READY**. Real Foundation Models analyst and executor produced a SQL repair independently verified on fresh PostgreSQL/RabbitMQ. Controlled CI R6-R8 qualification passes; automatic application stays BLOCKED. Exact commits, all failures, token usage and remaining deployment steps: [agent CI report](reports/agent-ci-summary.md). Historical evidence and original full-scenario gaps follow.

## Evidence

S1 commit-gap recovery now has a scoped PASS: [report](reports/commit-gap-summary.md), [Actions 39067222291](https://github.com/rengalaxies/agent/actions/runs/39067222291), source `ce6fa97dde09e4bcea72b701d203430395d9e2d5`. Hard controller death after durable S1 commit, persisted journal, fresh-process reconciliation, safe-stop and blind-retry denial are independently checked. T13/T14 are PARTIAL_PASS for this window only; full coverage remains open. No new model calls or VM actions.

Operational access update, 2026-10-17 22:45 MSK: the operator added the Foundation Models key. Rerun job 117487080370 in run 39061894797 returned PASS_API_RESPONSE for openai/gpt-oss-120b with 70 input + 16 completion tokens. Earlier missing-key/403 reports are historical. At that point real agent repair had not yet run; the later agent CI report supersedes this access-only status. Operator console supplied the UI Ed25519 host fingerprint at 22:50 MSK; read-only SSH qualification follows.

- Final verified code: `7bb70630bfb72e58e11bda36aa9f0ee7dc6a4e90`. [Full lab CI run 39062576562](https://github.com/rengalaxies/agent/actions/runs/39062576562) PASS, including 12 lab + 5 infrastructure unit checks, live application suite, restart, broken control and independent correct/wrong artifact execution. Main scenario outcome remains INCOMPLETE. All final JSON and immutable image manifests are preserved under `reports/ci-39062576562/`. [Existing P1 regression run 39062579591](https://github.com/rengalaxies/agent/actions/runs/39062579591) also PASS. Independent review confirmed the late authority/context recheck fix. No automatic transition is authorized by financial-only PASS. [Draft PR23](https://github.com/rengalaxies/agent/pull/23) has no deletions or unrelated changes; final documentation/report commits do not change this verified code.

- [Application CI run 39061632161](https://github.com/rengalaxies/agent/actions/runs/39061632161), code `9b7c687f4956333c573ba6575825ab5539481b0f`: successful execution; main suite outcome INCOMPLETE, broken control PASS. Preserved JSON under `reports/ci-39061632161/`. This commit's intermediate repository tree omitted pre-existing files; the later complete-tree repair restores every original path. The tested lab sources and original results remain identifiable by exact commit.
- [Full-tree CI run 39061894752](https://github.com/rengalaxies/agent/actions/runs/39061894752), code `8998afc7129b51c237ddd481a19b874a03723ecd`: successful application and artifact-control execution. Independent verifier ran actual candidate SQL in separate fresh PostgreSQL/RabbitMQ projects: compatible artifact PASS, wrong artifact FAIL as required. Main suite remains INCOMPLETE. Preserved JSON and immutable manifests under `reports/ci-39061894752/`.
- [Exact-project preflight 39040055755](https://github.com/rengalaxies/agent/actions/runs/39040055755), rerun job `117481021499`: source state serial 15; UI running/gen-2-4, core stopped/gen-2-8; approved project/zone identity checked. Existing state and recovery SSH key readable with SSE-C; key public part matches UI metadata. API/state only, not guest authentication. Runner TCP22 was connected in an earlier run and unreachable in later runs, including this rerun. TCP443 unreachable. No OS capacity measurement or FIT decision exists.
- [Model access probe 39061894797](https://github.com/rengalaxies/agent/actions/runs/39061894797): `CLOUDRU_FOUNDATION_API_KEY` absent; existing `CLOUDRU_WORKFLOW_API_KEY` received HTTP 403 from the documented Foundation Models chat endpoint with the documented `openai/gpt-oss-120b` model ID. No agent scenario was executed. Preserved report `reports/model-probe-39061894797.json`.

## Original matrix, combined actual application results

Restart qualification: [CI run 39062162959](https://github.com/rengalaxies/agent/actions/runs/39062162959), source `9ba0a730846d581f81b943ff2c77b266cab33836`, passed component restart control. Source/Billing rows survived PostgreSQL and RabbitMQ restart unchanged; a pending published event was consumed afterward into one ledger record for 12500 minor units. Evidence is preserved under `reports/ci-39062162959/`. This does not fulfill independent-operator restore T19. Independent static review additionally identified a grant/context time-of-check gap; the subsequent dispatcher fix reloads authority and revalidates hashes immediately before the effect. Expiry/revocation/context-change tests pass locally; the full R6 scenario remains unqualified.

PASS below describes only the frozen scenario's exercised application behavior. Unit tests do not upgrade other rows. The detailed original expectations remain in `evaluator/expectations.json`.

| Case | Status | Evidence / remaining scope |
|---|---|---|
| T01 safe change | NOT_RUN | No live product finding/inbox evaluation |
| T02 silent semantic change | PASS | Broken control: intended 12500 minor, Billing and Analytics observed 1250000; REJECT |
| T03 correct scoped transition | BLOCKED | S0-S5 financial control passed; agent repair and controlled CI R6-R8 now pass separately; full deployment-bound dispatcher acceptance remains blocked |
| T04 excessive patch | NOT_RUN | Unit path/evaluator edit rejection only |
| T05 wrong routing | PASS | Live missing binding detected; outbox retry after restoring route |
| T06 rare consumer absent from trace | NOT_RUN | Static scanner exercise only |
| T07 hidden consumer | NOT_RUN | No live recall experiment |
| T08 unknown/conflicting owner | NOT_RUN | No live exception-routing acceptance |
| T09 invalidated PASS | NOT_RUN | Unit context guard only |
| T10 expired/revoked grant | NOT_RUN | Unit guard only |
| T11 lost confirm | PASS | Real broker duplicate publication, one ledger business record |
| T12 commit before ack | PASS | Durable Billing commit, connection closes before ack, redelivery deduplicated |
| T13 partial transition failure | PARTIAL_PASS | S1 post-commit controller death, observation and safe-stop passed; S4 partial broker cutover/recovery untested |
| T14 UNKNOWN action outcome | PARTIAL_PASS | Persisted INTENDED after hard death reconciled to committed S1; retry denied before effect, invocation/update counters prove no repetition; other windows untested |
| T15 fractional coexistence | PASS | Explicit compatibility rejection; no rounding, S6 not performed |
| T16 invalid inputs | PASS | Separate rejection evidence for NULL, negative, fraction, currency, overflow, bool |
| T17 signal/revision | NOT_RUN | Local inbox logic only |
| T18 environment collision | NOT_RUN | Unit environment scope only |
| T19 independent installation/restore | NOT_RUN | Independent operator and actual restore unqualified |

Additional live controls: baseline, SELECT-only verifier privileges, wrong migration transactional rollback, mixed permitted versions, per-order and aggregate money invariants at every S1-S5 state, durable outbox commit/publication gap, idempotent backfill replay. Initial snapshot: 6 orders, exact total 214848377900 minor units. S5 control: 11 orders, exact total 214848379900. This is synthetic engineering evidence, not a customer or manual-comparator measurement.

## Concrete blockers and next authorized actions

1. Establish trusted runner-to-guest access. The read-only workflow supports an existing matched encrypted recovery key and `CLOUDRU_LAB_SSH_KNOWN_HOSTS`; it does not auto-accept a newly observed host key. Network reachability also needs qualification. Do not rerun VM replacement recovery or alter cloud-init expecting replay. Once accessible, run `host_inventory.py`, measure free RAM/disk/runtime/ports/workloads, then issue FIT/DOES_NOT_FIT before deployment.
2. Foundation Models API access is now qualified. The bounded real-agent CI scenario now passes; see the agent CI report. The workflow pins the verified model when the repository variable is absent. Keep secrets in Actions; no private key/password in chat is required. Workflow-key 403 is a verified access failure, not proof that Foundation Models is unavailable to the account.
3. Complete T01/T04/T06-T10/T13-T14/T17-T19 with actual product decisions, scoped effects and recovery. Retain their current status until evidence exists. Current repair generation supports one SQL migration file; broader related service patches and automatic live-source collection are future work.
4. Deliver a reviewed exact commit/image ID to a qualified existing VM using the authenticated channel. Existing core startup is authorized after resource/identity validation, but startup alone does not deliver code. No core start was performed while delivery is blocked. Resource recreation, new paid resources and capacity increases remain outside this implementation.
5. Test persisted data across component restart and operator restore, then run a real model's discovery/repair, independent verification and granted transition. Compare ordinary engineering, a strong agent and the module only with actual participants/runs under `evaluator/protocol.json`.

## Remaining implementation limits

CLI/controller-driven services, one host, no public UI, no production daemon supervision or telemetry backend, no general corporate discovery, no independent process-level read/write isolation for each model role, no signed multi-party grant service. Static provenance and owner uncertainty are exposed; repository hashes do not attest deployed state. Existing runtime uses trusted operator files for authorization. Test fixtures have broader administrative reach than product model output and must remain private to the lab controller.

The initial specification accepts integer rubles only; the uploaded 123.45 RUB example conflicts with that coexistence profile. The implementation rejects fractional rubles while v1 survives. No rounding, legacy retirement or arbitrary change to the research protocol was introduced. Kafka remains unimplemented with separate adapter requirements in `README.md`.

No VMs were created, replaced, resized or started. Earlier SSH qualification created and removed one temporary runner-only security-group rule; this agent CI phase made no cloud infrastructure changes. Main, the managed demo and frozen research artifacts were not changed. Three-mode labor/cost comparison, model costs and infrastructure cost are NOT_MEASURED. Real external notifications were not sent.
