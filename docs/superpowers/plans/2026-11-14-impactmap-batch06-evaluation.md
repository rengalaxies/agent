# ImpactMap batch 06 — evaluation tooling and author diagnostics

> Execute inline with superpowers:executing-plans and TDD; one fresh final reviewer. Preserve existing managed checkout/branch.

**Goal:** executable gold-blind ImpactMap/LS1 runner, strict scorer and honest registration checks, calibrated on 40 explicitly authored development cases. Independent evaluation remains unavailable without real experts/new hidden cases.

**Spec:** research/evaluation/protocol-v1.md and annotation-guide-v1.md; batch06 in handoff; user says "пока всё делай ты" — author all controllable work, never impersonate real humans.

**Architecture:** tools/impactmap_eval contains common input/source contracts, normalized-output mapping, isolated method runner/LS1 and a separate scorer. Input schemas from02 remain authoritative. Methods receive only case/policy/snapshots, never catalogue/stratum/reference. Author development labels are draft with human attestations false; only scorer development mode accepts them. Registration stays NOT_REGISTERED until curator/expert/material/threshold requirements are satisfied.

**Tech:** existing Python, GitReader/collect, CoreAnalyzer, rg, jsonschema already present in development venv. MODEL OFF, no network or source execution. New output directories, raw outputs and source-bearing data ignored under work/.

## Decisions

- Same pinned policy inventory, provider base/head and consumer assigned head. Source hashes and exact line witnesses checked; no current-branch fallback. Packet/tree digest definitions documented before runs.
- LS1 actual rg fixed-strings JSON per neutral hint, including README/literal hits; no AST/manual gold filtering; empty hints explicit query_not_identified abstention.
- Core structured findings bound via consumer/callsite/evidence to calls relationships; no finding×delta Cartesian product. Addressed checks/affected/claims retained. Ambiguous target => deterministic UNBOUND per consumer, all refs retained. Unsupported free text requires audit, not silent success.
- Strict matching requires allowed phase/commit/path, statement containment and exact source quote hashes; wrong witness => FP+FN. Invalid output candidates never TP. Micro/identity/FAR, per-stratum/origin/provenance, O/error/abstention and paired baseline retained. No invented TN or population CI.
- First assigned attempts only; timeout/crash persists as primary error. Same wall cap proposal60s from05, not approved. Diagnostic reruns distinct/new directories; no selection of best run.
- Candidate freeze hashes source8d45b0f, tooling/core/deps/rg/config, proposed budgets; no approved human/date or registration fabricated. Separate physical curator workspace remains a human/operational requirement, not something .gitignore guarantees.
- Forty authored development cases follow20/10/4/6 planning quotas; correlated families are counted, not independent projects. They cannot later become the independent40. No output declares independent criteria met.

### Task 1: common contracts and strict scorer

**Files:** tools/impactmap_eval/common.py, scoring.py; tests/performance/test_evaluation_tooling.py.
**Interfaces:** SourceRegistry from pinned case/policy; key normalization; score_case(prediction,reference,registry,development=False), aggregate(records,catalogue), paired(method reports). Output counts/denominators and invalid/gold-audit indicators.
- [x] RED tests: correct/incorrect source witness, wrong phase/statement, dedup/UNBOUND, invalid-output FP+FN, unseen gold key audit, N/A, FAR14 not40, O/errors, primary selection, registration false-human handling.
- [x] Implement minimal helpers and scorer; GREEN.

### Task 2: gold-blind runner and normalizer

**Files:** normalizer.py, runner.py, __main__.py; same tests.
**Interfaces:** run_method(case_path,policy_path,method,output,development=False), normalize_core(raw,case,registry), LS1(case,registry,...); produce existing normalized schema plus raw artifacts and coverage/error receipt. Scorer is never imported by worker.
- [x] RED real-core tests for proper binding with multiple ops, checks without finding, malformed/ambiguous candidates, empty hints, lexical false hit, pinned input/rights/hash drift, timeout/no-overwrite.
- [x] Implement isolated bounded subprocesses, strict schemas/input hashes, raw rg and core output/publication; GREEN.

### Task 3: author calibration, freeze candidate and handoff

**Files:** author_cases.py; research/evaluation/batch06/ reports/readiness/recipes; CHECKPOINT.
- [x] Build40 new authored fixtures with draft non-human oracles; no expert names/attestations forged. Run both methods in frozen predeclared order, then score; save every error and per-key result.
- [x] Fresh review, one tested important-fix pass; all relevant regressions and prior schema contracts.
- [x] Candidate source/tool/dependency freeze and registration readiness report; method/code ready is separate from independent research DONE. Update checkpoint/transfer copy and locally commit.

## Ledger

Input8d45b0f5c22fc652c704bc38a787b88d94663d7f, clean named linked worktree. Protocol02 read;40slots are not cases, templates unsigned. Drive metadata search ImpactMap returned two old presentations only; no file contents or hidden gold accessed. User takes no curator role yet and delegates controllable work to agent. Ruling: create author diagnostics now, keep independent study NOT_REGISTERED / NOT_RUN; no further human-status question required.

Pre-flight: SourceRegistry common input contract feeds normalizer/LS1/scorer; runner has no gold/catalogue arguments; author generator writes input and oracle separately. Scorer tests use synthetic draft data only. Production src unchanged; no external communications or live publication.


Progress: common pinned Registry/schema/packet hashes, strict scorer/aggregate/paired, output normalizer and gold-blind bounded worker implemented. Scorer RED missing module→9 GREEN; normalizer RED→12 GREEN; runner RED→15 GREEN. jsonschema is not installed in application venv: reused existing /tmp/impactmap-batch02/validator4.26.0 via explicit PYTHONPATH; no application dependency mutation.

Author generator first trial had an inconsistent toy expectation (required40 while base default20). Corrected before any campaign scoring to20 required/20 base/10 head; superseded initial generation stays ignored. Final source fixtures at work/batch06/development-v1; contracts are actual hashed author files, reference lifecycle draft and both human attestation flags false. External-helper fixture imports its helper; nothing is executed. Smoke methods use only DEV0001 inputs; no reference path passed to worker. No real expert labels have been received/read/generated.


Fresh review found P1/P2 issues (no real gold accessed): resetting primary via another output path; raw/excluded-path leak blind spot; raw lost before normalization/presentation; incomplete freeze false-ready; FAILED TP credit; hash definitions not guide-compatible. All accepted in one fix pass. Review regressions first RED, then GREEN. Added a fixed-permit-path SQLite assignment/order ledger, complete raw evidence/visibility checks and curator-only prose audit gate, immediate raw payload persistence plus immutable attempt envelope, mandatory environment/seed/primary/retry/argv/date checks, no TP for technical outputs, canonical UNBOUND checks and macro/positive-case diagnostics.

Hash correction: separate deterministic TAR of permitted sources/task/policy/hints/budget; byte SHA. Full tracked curator manifests use [phase,commit,path,mode,kind,contentSHA/gitlinkOID], no symlink following. Worker recomputes full digest only where all tracked entries are permitted/available; otherwise opaque curator digest plus required custody/input-integrity attestation, never reads excluded blobs to verify it. Actual allowed bytes are compared exactly against packet. Case input does not self-hash.

Author-v1 campaign completed before code corrections; superseded, not final. Partial final generation failed because curator GitReader requires absolute root; fixed author-builder caller .resolve(), new development-v2 generated40. Final campaign work/batch06/author-run-final started against corrected packet/envelope contracts, fixed order/60s cap, all80 primary attempts before first oracle read. Production source remains frozen8d45b0f unchanged.


Technical preparation complete; independent research AC remains NOT_REGISTERED/NOT_RUN. Final authored inputs development-v2, method outputs author-run-final:80 first assigned attempts,40 cases/13 groups, all supported inputs validated and no technical S errors. Raw primary outputs unchanged after a development-only correction excluding O-only unseen alerts from S-gold audits; final source/candidate versus actually executed method component versions disclosed. Numeric TP/FP/FN/P/R/FAR unchanged. Closed-side verifiers/dependency-lock capture added after outputs, do not alter method behavior or counts.

Final tests:76 relevant regressions in40.491s OK; final evaluation suite38 in10.067s OK (with two curator tests after prior36). No production code/default changes or VM/external actions. Public artifacts keep exact Core envelopes and explicitly path-redacted lexical derivatives; original SHA/receipts retained. Requirements include observed transitive validator/core dependencies, not a mutation of application venv. Optional façade __main__ omitted in favor of tested explicit module CLIs (ruling: avoid redundant indirection).

Integration choice remains keep local branch/worktree, commit author tooling/data/checkpoint; no independent-study DONE, merge/push or archive. Missing external inputs listed concretely; next executable technical line07. No further human question after user's delegation; no expert identities or approvals invented.


Release verification: final38 tooling tests in9.088s OK, including partial timeout stdout/stderr retained (RED→GREEN). Complete author campaign repeated with all final modules in work/batch06/author-run-release, unchanged development-v2 inputs:80 receipts,40cases/13families, same TP20/FP6/FN0 vs TP20/FP8/FN0, O4/6 vs2/6. Method-run component hashes equal release candidate. Earlier versions remain superseded; replays are not added to n. Production core untouched; no independent evaluation/real expert created. Existing02 contract checker rerun with only its report write redirected, historical report byte-identical.
