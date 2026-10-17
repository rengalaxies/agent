# S1 commit before controller confirmation - verified CI scenario

**PASS in the specified coverage.** Expectations were committed before implementation in `130257d42d584cd86c00bf0453044ef3a37c889b`: `lab/evaluator/commit-gap-expectations.json`, SHA256 `778920a9d753715414090553a11520943ddc003d32ae9298f4c5ea18591880d2`. The independent controller verifies its freeze before every run; expectations were not changed after observing results.

Successful source commit: `ce6fa97dde09e4bcea72b701d203430395d9e2d5`. [Actions run 39067222291](https://github.com/rengalaxies/agent/actions/runs/39067222291), all steps PASS including 15 existing/new authorization and reconciliation tests. Full original artifacts are committed in `commit-gap-ci-39067222291/` with immutable dependency image digests, application image ID, process exit codes, journal and before/crash/recovery/final independent snapshots. No LLM calls, VM actions or main changes. Automatic application remains BLOCKED.

## Frozen fault and expected response

Step **S0 -> S1** backfills integer minor units in PostgreSQL. The controller writes/fsyncs INTENDED, calls the same trusted effect/journal boundary used by the dispatcher, and exits via `os._exit(81)` immediately after `service.transition('S1')` returns durably committed. It never reaches after-snapshot or CONFIRMED. This is a hard process death, not a caught exception that can write UNKNOWN.

A new container process mounts the same persisted journal while PostgreSQL/RabbitMQ retain their volumes. `reconcile_unknown` validates the hash chain and artifact binding, reads actual source and Billing through the SELECT-only roles, and verifies S1 plus the matching durable transition-log entry. It appends **RECONCILED_COMMITTED_STOP** with reason **S1_COMMITTED_WITHOUT_CONTROLLER_CONFIRMATION_REQUIRES_FRESH_OPERATOR_DECISION**. It neither repeats S1 nor proceeds to S2. An explicit attempted retry of the same action/context is denied before the effect callback. A contradictory durable state or corrupted journal also blocks, covered by separate unit negative controls.

The private CI fixture invokes the post-authorization effect boundary directly: no production execution grant is issued and the public dispatcher's financial-only admission block is not bypassed or removed. This proves the effect/journal crash window, not the entire deployment authorization path. The recovery function only observes business state and writes the controller journal.

## Independent observed results

| Property | Observed |
|---|---|
| Order input | 0, 1, 7, 125, 19 integer RUB |
| After crash | Durable source S1, one S1 transition log entry; controller journal only INTENDED |
| After controller restart | Source/Billing snapshot unchanged by reconciliation and denied retry |
| Transition function invocations | Exactly 1, independently counted by persistent fixture instrumentation |
| Actual orders UPDATE effects | Exactly 5, one per order, independently captured by a database trigger |
| Money | Every source order equals its fixed expected minor amount; Billing matches all five IDs and values; total 15200 minor |
| Pending processing | Four orders delivered before failure; the fifth published but not consumed; trusted test fixture drains that remaining message after controller safe-stop |
| Completeness | Five ledger rows, five unique processed events, five published outbox rows with one publication attempt each; next consume handles 0; ready queue 0 |
| Journal | Valid hash chain; INTENDED -> RECONCILED_COMMITTED_STOP; recovered observation exactly equals the independent post-crash snapshot; no fabricated CONFIRMED |
| Cleanup | Disposable CI Compose project and volumes removed |

The database trigger detects repeated UPDATE effects even if values would remain identical. The separate invocation counter also detects a second transition call that an idempotency guard might otherwise hide. Draining the ordinary pending Billing message is a trusted test-fixture action after controller safe-stop, not an automatically resumed migration step.

## Preserved failed run

[39067052028](https://github.com/rengalaxies/agent/actions/runs/39067052028), source `dd6b33aadcb0568089bdd62b5ba7ef17439f6e53`, ended FAIL. Fault, recovery, retry denial and business checks executed, but the final journal/snapshot equality assertion rejected two textual timestamp encodings (ISO `T` versus space) of the same instants. All evidence remains in `commit-gap-ci-39067052028/`. The subsequent implementation uses the same canonical datetime serializer for independent snapshots and audit records. Expected values and the equality check were retained; a new fresh run passed.

## T13/T14 scope and next step

- **T13 PARTIAL_PASS:** one failure after durable S1 completion stops subsequent migration steps and records the observed partial transition. No S4 broker-binding partial-cutover failure, rollback or automatic continuation was tested.
- **T14 PARTIAL_PASS:** one hard-death window leaves an unresolved intent; a restarted controller reconciles actual committed S1, records safe-stop, and denies blind retry. No general recovery for every step or failure window is claimed.
- T19 independent operator restore remains NOT_RUN. No status in frozen expectations is rewritten; the actual coverage is recorded in lab/status.md and this report.

Next work returns to authenticated delivery to the existing Cloud.ru VM, guest capacity measurement and pinned installation. This CI result does not authorize VM modification or automatic application.
