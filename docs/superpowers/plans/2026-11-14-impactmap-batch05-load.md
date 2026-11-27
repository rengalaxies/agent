# ImpactMap batch 05 — load and canonical equality implementation plan

> Execute inline with superpowers:executing-plans; TDD; one fresh final reviewer. Reuse existing managed worktree and preserve it for subsequent batches.

**Goal:** record cold application indexing, repeated analysis, resource costs, real local service queue behavior and full/event graph equality for current pilot and controlled scale profiles, including diagnosed limits.

**Architecture:** reuse tools/benchmark_impactmap.py for isolated-process stage measurements, and add tools/load_impactmap.py for graph equivalence and actual ServiceStore/Service/CoreAnalyzer/Publisher workloads. Only external connector transport is replaced by pinned local snapshots and DirectorySink. Reports and safe raw observations under experiments/impactmap_scale/results/; Git inputs and SQLite stay in ignored work/.

**Tech Stack:** existing Python, SQLite, resource, deterministic batch04 Git corpus, actual graph and service code; no new dependencies.

**Spec:** batch05 from /Users/user/Documents/ChatGPT/ВКР/ImpactMap_пачки_и_передача_контекста_2026-11-14.md and CHECKPOINT.md at input b0f5bd1398145c890bba970bbec7fc598f2ce2fc.

## Constraints and decisions

- Same Python HTTP/API profile, MODEL OFF, no external comment writes or installed runtime changes. Product limit 2MB must first yield its explicit diagnostic; named batch04 8MB test policy measured separately.
- Three independent worker repetitions per required stage profile; new SQLite/application state is cold, OS caches uncontrolled. CPU self/reaped children, process-lifetime RSS high-water marks with exact scope; no production p95 claim.
- Current author pilot stays on VM, only program sent and numeric/hash metrics returned. No source/Git/config export. If access fails, preserve diagnostic and prior baseline separately; do not invent a run.
- Incremental means existing GraphMaintainer.on_code_event into persisted state (currently rescans code); fresh full reconciliation compared at identical final complete pins. Include base→head, repeat, new consumer, removal and operation removal; cached PARTIAL separately labelled, not compared as equal to empty history.
- Queue uses real wall time and product scheduling limits, one worker, controlled local connector, no network. Run 1/5/10 independent PR burst and head-update sequential/burst. Burst may correctly coalesce heads; require latest generation, no duplicate comments, terminal valid result and complete coverage, not 10 analyses for one coalesced resource. Save per-step queue wait/analysis/publish spans and raw status/history counts. Prepared graph base indexed before queue drain, cost measured separately.
- Work limit is tested envelope, not extrapolation. Do not add 20–30 repo scope A1. Fix production code only after reproducible observed limitation, with RED→GREEN; keep defaults explicit if no safe default change follows evidence.

## Review focus

1. Empty equality is not sufficient: complete coverage, counts and expected controlled findings must gate PASS.
2. An ignored error / pending retries is not idle success: require no outstanding queues/intents, correct current generations and published versions.
3. Event sequence must use pinned input, latest fetched snapshot semantics and independent PR identity, with duplicate delivery evidence.
4. Canonical equality must compare actual full facts with persisted event path for identical sources, including removal; not timing-stripped failed results.
5. Failed runs must leave safe raw errors/counts/limit fraction and nonzero outcome rather than disappear from summary; generated paths/source/credentials excluded from public artifacts.

### Task 1: stage baseline and limits

**Files:** existing tools/benchmark_impactmap.py, run_pilot_vm_benchmark.py; reports under results/.
**Interface:** existing benchmark manifest/JSONL/spans; no format change required.
- [x] Run 3 independent process baselines on 5/50k and 10/100k using explicit preparation policy; current pilot in-place with frozen batch03 pins.
- [x] Record default-limit failure with observed progress numerator, bytes/lines expected and diagnostic. Record CPU/wall/RSS and full/partial coverage separately.

### Task 2: executable load and equality checks

**Files:** tools/load_impactmap.py; tests/performance/test_load_impactmap.py.
**Interfaces:** run_graph_equivalence(input_manifest, scenarios, output); run_queue(input_manifest, events, output, mode='burst'); all return safe JSON with status, spans, coverage and expected-vs-actual checks. CLI --corpus ROOT --output NEW --queue-size 1/5/10 --family head_updates/independent_prs --delivery burst/sequential --equivalence. Input oracles only verifier side, never analyzer.
- [x] Write failing small real-core tests for fresh-vs-persisted equality including lifecycle deletions, duplicate burst head coalescing, distinct PRs, sequential head updates and partial/failure gating. Observe RED.
- [x] Implement pinned connector / DirectorySink boundary, actual service steps, graph comparisons and safe failure artifacts; GREEN.
- [x] Execute required 1/5/10 matrix on 5/50k and 10/100k; retain failures before any correction. Add small anchor and density/axis measurements only if needed to explain observed limits.
- [x] Apply only evidence-driven corrections and relevant graph/queue/benchmark regressions.

### Task 3: report, review and handoff

**Files:** experiments/impactmap_scale/results/README.md, raw JSONL/CSV, summary/acceptance; CHECKPOINT.md.
- [x] Summarize timings/resources/errors/processed fraction, observed working envelope and limit; separate conducted vs passed.
- [x] One fresh-context branch review; one tested fix pass for important findings. Verify published hashes/links and no private input/source state.
- [x] Update CHECKPOINT and transfer copy; locally commit; next06 depends on actual humans/independent cases and cannot be fabricated.

## Ledger

Input b0f5bd1, clean existing codex/impactmap-batch-00 linked worktree. Prior authorization and complete batch specification allow inline execution without reopening design/permission dialogue. Ruling: use current architecture, keep source collection limits explicit, do not silently raise product defaults. Cost: 100k success is conditional on documented operator configuration.

Pre-flight interfaces: Task1 public span/raw format feeds Task3; Task2 uses batch04 manifest pins/streams and existing Service/Graph contracts. All raw state private; same complete pins needed for equality. No conflicting interface detected.


### Implementation ledger

Task 2: initial RED import failure observed. Real small core/queue checks implemented; 7 tests GREEN. Additional safe-error and explicit abstention replay tests RED→GREEN; 9 tests GREEN. Added VM helper transport-failure regression; combined relevant suite running.

Ruling: operation removal has exactly three expected `unmapped_call` semantic gaps while all repository sources are readable. Keep coverage PARTIAL, require those exact gaps, all sources available and exact known active fact count. Other gaps/access failures cannot pass; no weakening to equal empty graphs.

Ruling: first two local stage baselines were launched concurrently. They pass semantic controls but are preliminary contention observations only; final performance matrix reruns serially, with no simultaneous local workload. Pilot baseline used distinct host and remains separately labelled.

Task 2/3 interface: generalized `run_queue_input` accepts validated pinned manifest/events and explicit expected status/count/reason. Generated scale expects USEFUL/3; frozen real pilot change expects ABSTAINED/no_supported_delta/0. Pilot 1/5/10 queue load is controlled independent-ID replay of one frozen actual case, never 16 real PRs. No source/Git export or actual tracker writes.


Review: one P2 all-generation false-PASS accepted and fixed. Meaningful regression RED obtained by disabling just the new acceptance gate in memory; failed first document with valid correlation_id then four good documents. Fixed runner persists per-job verdicts and requires every expected result. Minor active-consumer decrement/gaps derived from recipe. Final 72 relevant tests (including 11 load tests) in 60.900s, OK. A mocked VM-helper failure prints an expected remote_load_failed after test summary; actual final pilot load PASS all four cases. Final pilot helper rerun after runner fix, no source transfer.

Task 1: current pilot stage 3 independent workers PASS with frozen batch03 pins; final pilot load/equality PASS (5 canonical facts, base/head; 1/5/10 independent IDs replaying one immutable corrected change, ABSTAINED/0). No installed service/state modifications. Local final serial matrix started after all tests completed. Preliminary concurrent baselines retained as superseded, not used for timing conclusions.


Task 1: complete — final local baseline runs serialized, 3 workers each; pilot baseline 3 in-place workers. All control semantics match. Default probe 10/100k diagnosed corpus_limit after 173 files / 1,995,087 accepted bytes (78.66%), no analysis; 5/50k collected completely.

Task 2: complete — 18 main local queue cases + 3 pilot replay cases + supplementary 10-PR 5/50k default-policy case = 22, 96 analyses, 122 unique + 122 duplicate deliveries. Every expected job result and latest publication valid, no pending/failed queue state. All 80 local executed job result snapshot maps independently checked against frozen corpus stream pins during packaging; pilot temporary state deliberately removed, explicit immutable replay pins retained. Scale full/event equality: 4 cases each; pilot base/head equal, semantic PARTIAL on operation deletion retained.

Ruling: supplement the default collector probe with a full 10-PR queue on 5/50k using every unchanged product limit. This avoids inferring successful default-policy pipeline from collector success alone. Recipe results/check_default_queue.py is a configuration of the reviewed API, executed after main matrix with no load overlap. Its outer process envelope was not separately timed; progress row explicitly uses returned run_queue_input elapsed. Main 24-case matrix and supplementary case give 25 progress rows.

Task 3: complete — report, raw spans/JSONL/queue/equality/probes, executed pins, environment/versions and summary saved under experiments/impactmap_scale/results/. Final 72-test log and meaningful review RED retained. No production source/default changes, no actual external comment writes, no source/Git export. New tooling/reports committed locally; current branch/worktree retained as previously authorized. The finishing skill's merge/push menu is unnecessary given this existing choice; project-wide unrelated tests are not rerun because production source is unchanged and the 72 relevant checks plus actual load matrix cover this batch.

Next06 requires real independent cases and experts; workloads are controlled development material, not substitute annotations. Checkpoint and transfer copy updated; final acceptance verifies JSON/pins/raw summaries/paths/checksums and source unchanged. Commit identity belongs to Git history, not a self-referential field.
