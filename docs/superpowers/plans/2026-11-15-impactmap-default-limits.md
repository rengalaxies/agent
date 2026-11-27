# ImpactMap working defaults Implementation Plan

> Execute inline with executing-plans/TDD in existing codex/impactmap-batch-00 worktree; one fresh final reviewer if available. Owner already approved scope/approach; no repeated approval pause.

**Goal:**8MB/2048files/60s are real defaults and resource refusals are explicit to operators/users.
**Architecture:** existing Limits defaults + whitelist resource failure handling using existing FAILED/budget_exhausted + existing short presenter. Operator overrides and per-file gaps preserved.
**Tech Stack:** Python/Pydantic/unittest, existing offline benchmark/load/CoreAnalyzer/local sink.
**Spec:** docs/superpowers/specs/2026-11-15-impactmap-default-limits-design.md

## Global Constraints

- Baseca81bfb. Keep managed worktree, MODEL OFF; no push/merge/deploy/network/API/key access/dependency changes.
- Defaults8_000_000bytes/2048files/60s; perfile65536 and hard bounds unchanged. Explicit overrides untouched.
- Output2.2/static profile9 unchanged; no classification/normalizer/scorer changes or independent06 claims.
- Original measurement/corpus/evaluation reports immutable; new outputs only, no blind retries replacing failures.
- Sequential timing:one5/50k worker,three10/100k workers; reference comparison each; OS caches uncontrolled. Queue diagnostic times separate.

## Review Focus

- Explicit2MB configs must not silently become8MB; omitted/partial limits must materialize defaults consistently at service entry.
- Per-file oversize and revoked/unavailable sources must stay visible, never be relabelled complete.
- Corpus/file/time abort must not save a partial context or claim no impact; stable configured-limit message only, no source/path/exception leaks.
- The Russian short-comment renderer must preserve budget failure diagnosis without changing unrelated statuses or transient retry behavior.
- New measurements must truly use omitted limits rather than retain old manifest's explicit test settings; all completed queue generations counted; old raw unchanged.

### Task 1: Defaults, failure diagnosis and regression checks

Files: src/agent_graph/contracts.py/results.py; src/agent_service/core_analyzer.py/jira_presentation.py; new tests/graph/test_working_limits.py and tests/service/test_resource_limits.py; intentional live expectation in tests/performance/test_scale_corpora.py; new docs/operations/analysis-limits.md.
Interfaces: Policy limits omitted/partial/explicit; failed_result optional summary; existing AnalysisResult2.2 reason budget_exhausted; presenter displays that failure summary.

- [x] Write behavior tests for >2MB and >256 selected files, explicit overrides/atomic abort and pinned Git limit; real CoreAnalyzer error→public result and short renderer, unknown error redaction. Run RED.
- [x] Apply new defaults; map only known collector budgets; preserve model/source/other failures, schema/profile and per-file behavior. Write operator profile/migration documentation.
- [x] Run graph/service/performance relevant suites; record exact failures/skips, no all-green global claim. Expected affected suites GREEN. Local commit.

### Task 2: Default-path acceptance and handoff

Files: experiments/impactmap_scale/defaults-2026-11-15 report/receipts/recipes; CHECKPOINT and roadmap/mirror.
Interfaces: existing pinned corpus inputs, actual policy with limits omitted, baseline/current source hashes, real queue with local sink.

- [x] Verify old pinned inputs/defaults metadata remain untouched; materialize new input manifests with limits omitted and assert actual CoreAnalyzer policy equals new defaults.
- [x] Run sequential stage workers1×5/50k and3×10/100k with reference semantic/fact equality, counts/wall/CPU/RSS/source/environment. Expected complete coverage8ops/3calls; no external transport.
- [x] Run bounded default queue/replay/reopen and partial-access/per-file/explicit-budget controls; verify all executed result generations, not just latest. Expected positive complete and negative refusal/gaps retained.
- [x] One whole-batch review; fix substantive findings in one RED→GREEN pass and repeat affected checks if sources change. If model unavailable, preserve failure, author audit and completed-review gate for10.
- [x] Preserve historical hashes; verify new portable artifacts/source and update CHECKPOINT/roadmap/mirror. Local commits only; worktree retained.

Evidence: experiments/impactmap_scale/defaults-2026-11-15/README.md. Sourcefd3dbc3; one fresh review With fixes, I1/I2 +M1 regraded by effect fixed; metadata controls RED→GREEN; core timing/source unchanged.
