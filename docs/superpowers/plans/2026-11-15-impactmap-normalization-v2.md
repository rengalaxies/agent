# ImpactMap normalization v2 Implementation Plan

> Execute inline with executing-plans/TDD, existing managed codex/impactmap-batch-00 worktree. Scope/approach already authorised; no repeated design approval pause. One fresh final reviewer.

**Goal:** Bind warnings to the changed operation with localised witnesses or retain UNBOUND, and version/repeat the author diagnostic transparently.
**Architecture:** focused binding index consumed by existing normalizer; preserve aggregation/scorer/schema; new protocol-v2 and explicit normalizer component identity. No product core changes.
**Tech Stack:** existing Python/unittest/Registry/pinned Graph outputs/jsonschema/calibrator.
**Spec:** docs/superpowers/specs/2026-11-15-impactmap-normalization-v2-design.md

## Global Constraints

- Base0841a90; reuse managed worktree, MODEL OFF. No push/merge/deploy/external API/key/new dependencies.
- Core source/profile9/output2.2/defaults8MB untouched; scorer/oracles/inputs/seed20261114/cap60s/formulas unchanged.
- Old protocol-v1/schemas/report/raw immutable; new protocol2 and normalizer version/config identity for new runs only.
- Every addressed candidate retained, including malformed/PARTIAL/non-risk/recheck. Ambiguous target→canonical UNBOUND, no cartesian product or borrowed witness.
- Author40 remains development;0 new independent cases/experts; no numeric improvement promised.

## Review Focus

- Replacement calls→new route must not overwrite the old changed warning target; mismatched explicit subject must not be rescued by a different convenient delta.
- Same consumer with several calls/operations or merged calls edge must not mix witness lines/commits; same-line ambiguity stays explicit.
- Typed subject requires real scoped delta/provider support, not output text or evaluator expectations; cross-consumer/service/method/scope matching forbidden.
- Findings/checks/claims/affected-only and malformed-first entries must retain addressed load; no empty/invalid evidence upgraded to TP.
- Protocol/config/freeze/source identities and old raw immutable; re-normalization of identical outputs distinguished from fresh assigned attempts.

### Task 1: Versioned bindings and regression gates

Files: tools/impactmap_eval/normalizer.py; new operation_binding.py; registration.py/runner.py/calibrate.py; new research/evaluation/protocol-v2.md; new tests/performance/test_normalization_binding.py and fixture helper.
Interfaces: resolve(consumer,refs,callsite/direct-claim-IDs/relationship-IDs)→operation-or-UNBOUND plus supporting refs; normalized JSON1.0 unchanged; components normalizer version/protocol SHA.

- [x] Write actual pinned-output and targeted structural regression cases; run RED, retain exact failures.
- [x] Implement delta-aware explicit-subject/call binding, witness isolation, conservative UNBOUND and preserved audits; add version2 protocol/identity before outputs.
- [x] Run affected evaluator/performance/registration/packet/core-output suites GREEN; preserve observed failures. Local commit.

### Task 2: Replay, assigned author repetition and handoff

Files: research/evaluation/normalization-v2-2026-11-15 report/recipes/raw-index/hash receipts; CHECKPOINT/roadmap/mirror.
Interfaces: existing Registry inputs/author raw envelopes/oracles, unchanged scorer, v1-from-Git and new v2.

- [x] Compare identical frozen replacement/author core payloads through v1 and v2, retain both normalizations and all old bytes; never alter original40 membership.
- [x] New80 assigned author attempts (same inputs/order/seed/cap, post-tuning) after source/tooling freeze; preserve failures/no opportunistic retries. Compare per-case outcomes and LS1 search behavior.
- [x] One final whole-batch review; one substantive RED→GREEN pass if required and repeat only affected evidence. No second reviewer.
- [x] Verify portable hashes/source identities and private rescoring; update CHECKPOINT/roadmap/mirror; local commits, worktree retained. Independent06 remains NOT_REGISTERED/NOT_RUN.
