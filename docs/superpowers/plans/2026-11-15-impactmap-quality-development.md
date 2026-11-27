# ImpactMap quality development implementation plan

> Execute inline with superpowers:executing-plans. One final fresh reviewer, one substantive fix pass; reuse current managed worktree.

**Goal:** fix six explicit-size false warnings and make opaque provider changes explicit, preserving breaking findings and unavailable-source failures.
**Architecture:** source-backed exemption for default-only delta, independent explicit-size metadata and AST comparison of remaining provider basis; existing result schema, versioned static profile. Offline author comparison on identical pinned inputs and unchanged scoring.
**Tech Stack:** existing Python/AST, Graph/CoreAnalyzer, unittest, existing evaluation runner/LS1; MODEL OFF.
**Spec:** docs/superpowers/specs/2026-11-15-impactmap-quality-development-design.md

## Global constraints

- Base49cd917, current codex/impactmap-batch-00 checkout, preserve private work and historical research/evaluation/batch06 files byte-for-byte.
- No new dependencies, deployment, network/publication, made-up independent cases/experts, scorer or oracle tuning.
- Existing FAILED/commit_unavailable remains failure. Interpret the remaining O-case honestly.
- User delegates routine choices; inline execution continues without per-task approval.

## Review Focus

- Explicit parameter lost in loop, None/empty/dynamic values or unrelated JSON/body size must not incorrectly exempt a call.
- A default edit combined with body/contract/import/helper changes must retain semantic uncertainty and checks.
- Dependencies remain discoverable even when this delta warrants no consumer alert; do not imply no consumers/general compatibility.
- Old contexts/knowledge must invalidate after extraction/classification semantics change.
- Original negatives/raw/inputs/scorer remain unchanged; post-tuning rerun is development, never an independent success.

### Task 1: guarded default override and opaque semantic boundary

**Files:** change_scope.py, discovery.py, engine.py, results.py, __init__.py under src/agent_graph; new tests/graph/test_default_change_scope.py; relevant existing regression expectations.
**Interfaces:** internal dependency explicit_page_size metadata, provider non_default_basis/opaque basis; existing Graph.analyze_change and change_result output, existing unknown/reason codes.

- [x] Create real Graph/AnalysisResult regression fixtures for explicit dict/query/positional/loop overrides; assert no finding/check/affected alert for pure default change, retained graph dependency and delta.
- [x] Run tests RED; include neighbour risk assertions for omitted/None/dynamic/ambiguous params, mixed default+body, operation removal and opacity. Save failure log.
- [x] Implement strict source-backed metadata/comparison and exemption; record only semantic uncertainty outside known declarations. Use existing schema codes and PROFILE increment.
- [x] Verify final graph269/evaluator+qualification39 GREEN; service399OK/4Linux skips plus obsolete pilot assertion corrected/rechecked3/3. Preserve broader failures by name and original golden artifacts.
- [x] Commit core/tests/spec with test evidence. Expected: no unexpected failures.

### Task 2: same-input post-tuning development comparison and handoff

**Files:** new research/evaluation/development-2026-11-15 report/receipts/summaries, CHECKPOINT and remaining map. Runner/normalizer/scorer unchanged. Calibrate adds truthful --post-tuning disclosure and before/after core identity checking.
**Interfaces:** original work/batch06/development-v2 inputs and first historical author-run-release observations; new output directory only.

- [x] Run both methods on the same40 inputs/80 assigned attempts, same seed/budget; capture raw before scoring. Expected:20 TP,0 FN, six former compatible FP absent, provider-unavailable FAILED preserved; inspect any different result rather than force target counts.
- [x] Save safe artifacts, before/after paired tables, original hashes and negative outcomes; verify LS1 unchanged semantically and original files unchanged.
- [x] Run project unittest command and exact evidence validation. Report every failure/skip by name. Fresh final review of this batch only, then one RED→GREEN fix pass if needed.
- [x] Update CHECKPOINT/remaining work, mirror checkpoint, local commit only. No deploy/push/merge/archive.

## Ledger

Decision: scope is development completion, not formal independent06. O-provider failure stays FAILED; deployment and05 removal gap are outside this change. Cost: boundary score may remain5/6 and broader semantics remain unclassified.

Final15.11: core04fcbec, one review fix pass6bc5ca2;17 scope regressions. Authorv1 superseded after7 reproduced review bugs; authorv2 repeats same40/80,20/0/0 O5/6; LS1 unchanged. Original225 hashes/scorer/normalizer/oracle intact. DEV0039 FAILED retained. All private rescoring reproduces final summary. Full project1190 is explicitly NOT green (46fail/40error/4skip); final source affected checks/dispositions are in research/evaluation/development-2026-11-15/tests.json. No deployment or source/secret transfer.
