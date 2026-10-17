# Verified agent pass in CI - 2026-10-17

Result: **проверенный агентный проход в CI**. This is one bounded SQL repair task with two separate real Foundation Models calls, not Cloud.ru VM deployment or full T01-T19 acceptance. Main and VMs were not modified in this phase. Automatic application remains BLOCKED; no execution grant was issued.

## Exact runs and all failures

| Run | Source commit | Outcome | Provider tokens |
|---|---|---|---:|
| [39066044410](https://github.com/rengalaxies/agent/actions/runs/39066044410) | `dfcdfb8e3016721a397a1655c642873d19cfab9a` | BLOCKED: missing model variable, zero inference calls | 0 |
| [39066184605](https://github.com/rengalaxies/agent/actions/runs/39066184605) | `46807a9ab58c4f0f7818a4dd56ecf1afa574b3ef` | FAIL: analyst returned unsupported status enum; patch step not called | 14563 |
| [39066354050](https://github.com/rengalaxies/agent/actions/runs/39066354050) | `88826fc4c2121657f18d8a2ec00a1605b508f1ee` | PASS: analyst, actual model SQL patch, independent fresh financial verification | 24410 |
| [39066576814](https://github.com/rengalaxies/agent/actions/runs/39066576814) | `4b17adcba527f7d309b900cf1c35e9f153fc13d5` | PASS: independent controlled-world R6-R8 qualification and 13 unit/authority-race tests; no inference | 0 |

Model: `openai/gpt-oss-120b`, endpoint `https://foundation-models.api.cloud.ru/v1/chat/completions`. Model access is restricted to the inference step; no IAM/VM credentials are supplied to this workflow. Temperature 0, serial calls, 6000 maximum completion tokens per call. Per attempt: at most two requests, 64000 conservative token budget, 240 seconds. After the first real failure one final attempt was allowed: total two real attempts, three actual calls, **38973 provider tokens** (36311 prompt + 2662 completion, including reasoning). No more attempts are scheduled. Monetary model charges, CI infrastructure charges and manual time are NOT_MEASURED; no verified price was configured. This is a token/call/time cap, not a claimed currency cap.

Additional full regression: [39066430733](https://github.com/rengalaxies/agent/actions/runs/39066430733), source `57c071f7623d3b10de89f16f154f2708613fb13b`, PASS for 13 lab tests, scope guards, live application checks, component restart and independent correct/wrong candidate controls. Main scenario coverage remains INCOMPLETE.

## Input and independent evidence

The exact submitted input is `agent-ci-39066354050/agent-evidence/input.json`. It introduces the incompatible backfill `amount_minor=amount_rub`. Before inference, the independent controller executes that exact artifact on a fresh PostgreSQL/RabbitMQ project: FAIL as expected. The analyst identifies the unit conversion failure from permitted source evidence. The executor emits actual SQL JSON, saved in `proposal.json` and `model.patch`: `amount_minor = amount_rub * 100`.

The reference migration in the model evidence is replaced with the submitted broken SQL. The model receives open business requirements and the submitted diff (including its removed line), so this is a repair with an explicit requirement, not a blind synthesis benchmark. Neither stateless model role receives evaluator/test files or held-out case values. No model assertion counts as acceptance. The trusted host controller imports its own evaluator, mounts only candidate SQL read-only, and uses fresh disposable databases/broker, an independent SELECT-only verifier and frozen expectations. Negative control and repaired candidate use different fresh Compose projects. The repaired candidate passes baseline, rollback control, read-only role control and mixed-version S0-S5 monetary invariants. S5 has 11 orders, exactly 214848379900 minor units. Application candidate verdict is scoped R1-R5 PASS, not automatic execution authorization.

Exact request/response payloads (without auth headers), analysis, SQL, candidate bundle, source/input/suite/candidate digests, usage, all checks and immutable dependency image manifests are committed under the three `agent-ci-*` directories. Actions artifacts additionally retain the original upload. Candidate digest: `32cd6e1899c8aaf94c9648a89a773107c1e318c3d5e975eb21293c8d96d31585`. The successful run's frozen suite digest is `c0b7e19ec8aaf6240fcf4f53779de567eaaf37d5a16c570fa275f3e234425cfa`.

## R6-R8 - qualified CI scope

- R6: reject wrong action, object, environment, expired/revoked authority, stale context, path escape and app/evaluator writes. Dispatcher tests simulate expiry/revocation/context change during verification and assert no transition call occurs. These are controlled authorization tests, not a deployed multi-tenant permission service.
- R7: a rare static SQL reader is found without traces; missing owner remains UNKNOWN, conflicting owners remain CONFLICT, a same-name binding from another environment is excluded. Empty source retains coverage gaps. In the independently specified two-consumer world only one is visible: one detection, zero false positives, one miss, precision 1.0 and recall 0.5. No general completeness claim is made.
- R8: grounds digest changes for source, contract, topology, runtime, evaluator suite sources, data input, authority and candidate. Exact successful model revision and later boundary-qualification revision are recorded separately. Authority/context race controls pass. A later suite revision does not silently upgrade the old financial verdict; candidate evaluator still accepts R1-R5 only and the dispatcher requires R1-R8, so automatic application remains blocked.

Evidence: `boundaries-ci-39066576814/r6-r8.json` and `boundary-tests.log`. These close the specified controlled CI boundary checks; they do not attest live Cloud.ru state, live topology or data freshness. The result is intentionally not promoted to full T03 or all T01-T19 acceptance.

## Remaining before Cloud.ru deployment

1. Establish authenticated VM delivery; resolve incoming SSH / GitHub network timeouts or qualify Object Storage delivery. Measure existing guest RAM, disk, Docker and workloads, then record FIT/DOES_NOT_FIT.
2. Deliver a pinned reviewed commit/image to the existing VM and repeat business verification on a fresh isolated lab there. No VM start, resize, replacement or deployment was performed in this phase.
3. Bind a future execution decision to current deployed code, topology, requirements, data snapshot and fresh operator authority. Reverify the exact candidate after any material changes. No present CI report authorizes automatic application.
4. Complete remaining original scenarios, especially partial cutover recovery T13, UNKNOWN reconciliation T14 and independent installation/restore T19; qualify broader discovery/inbox behavior separately. Then perform the three-way experimental comparison. One simple backfill repair does not establish general agent competence or product demand.
