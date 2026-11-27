# ImpactMap batch 03 — implementation plan

> For agentic workers: use `superpowers:executing-plans`; implement inline, TDD, one final fresh-agent review. The existing managed worktree is reused.

**Goal:** obtain reproducible, stage-separated baseline measurements on the current author pilot without changing analyzer semantics or publishing externally.

**Architecture:** one offline CLI invokes the existing `CoreAnalyzer`, `GraphStore` and `DirectorySink` in fresh scratch state. Scoped wrappers measure collection, extraction, persistent graph sync, analysis, rendering and local publication; they restore the wrapped functions on exit. An uninstrumented run on the same pins checks semantic equality and canonical graph facts. Each repetition uses a new Python process; raw nested spans report inclusive/exclusive wall and self/reaped-child CPU separately, process-lifetime RSS high-water marks explicitly labelled.

**Tech Stack:** existing Python >=3.12, standard-library resource/time/subprocess/CSV plus the existing pydantic service dependencies. No new runtime package or model.

**Spec:** batch 03 in `/Users/user/Documents/ChatGPT/ВКР/ImpactMap_пачки_и_передача_контекста_2026-11-14.md`; `research/evaluation/protocol-v1.md` coverage/resource definitions and `docs/product/roadmap-2026-11-14/AS-IS.md`.

## Constraints and rulings

- No changes to installed VM processes, live queue or external tracker comments. The pilot source snapshot is acquired read-only, outside measured analysis; network/polling/live publication are NOT_RUN in the offline CLI, not fabricated zero-latency measurements.
- Baseline = current Bitbucket Orders/Reporting author pilot, pinned from the VM's stored PR4 and mirrors. Its corrected PR may have no supported delta; retain that result. The deterministic existing five-repository Orders/Reporting stand is an additional reproducible development smoke, not the future 5/50k scale profile.
- Only benchmark tooling/tests/docs change; existing core source stays unmodified. No old `bench/core` shim, no forced OS cache flush, no source execution, no credentials in artifacts. New SQLite/output state only in fresh directories.
- "Cold" means fresh application state/process, not proven cold OS disk cache. A warm repeat reuses application state; neither three repetitions nor warm runs establish p95.
- RAM is ru_maxrss for the Python process and reaped-child high-water mark, not summed process-tree RSS or a stage-local peak. CPU children counts only reaped descendants. Record units, platform and limitations.
- Ruling: fulfill the already-authorized batch via an isolated offline harness rather than adding production-wide telemetry. Cost: no claim about live network, polling, full queue overhead or installed-release latency; those are separate measurements.
- Ruling: external buyer interviews do not block resource instrumentation. Quality thresholds remain proposed; this batch produces performance observations, not precision/recall.

## Review focus

1. Nested spans must not double-count exclusive wall/CPU, and restoration must survive exceptions.
2. Timing must preserve returned documents and canonical facts, allowing only explicitly listed volatile metadata in comparisons.
3. Errors, sensitive sources and untrusted policy fields must not leak content or environment in exported artifacts.
4. Cold/warm, self/children CPU and cumulative memory peaks must be labelled honestly; unavailable measurements stay null/NOT_RUN.
5. Partial source access and truncated coverage must remain visible with configured and available repository/file denominators.

## Task 1: measurement and test contract

**Files:** `tools/benchmark_impactmap.py`, `tests/performance/__init__.py`, `tests/performance/test_benchmark_impactmap.py`.

**Interfaces:** `SpanRecorder(clock, usage).span(stage)` yields without modifying return values; spans carry parent/depth and inclusive/exclusive clocks. `run_case(manifest, state_root, instrumented=True)` returns redacted observations and semantic/fact digests. Manifest holds validated policy and explicit base/head maps.

- [x] Write tests for nested clocks, exception sanitization/restoration, cold/warm extraction/graph/publication spans, counts, semantic equality and partial access.
- [x] Run `PYTHONPATH=src:. <venv-python> -m unittest tests.performance.test_benchmark_impactmap -v`; expect missing implementation failure first.
- [x] Implement scoped wrappers, standard-library resources, offline analyzer/render/local sink path, counts and allowlisted artifacts.
- [x] Run the same tests; expect all pass, inspect failures before modifying behavior.

## Task 2: reproducible CLI and isolated processes

**Interfaces:** `python -m tools.benchmark_impactmap --output NEW_DIR [--manifest PATH] [--repeats N]`; omitted manifest builds the existing deterministic author stand in private state. Parent writes manifest/JSONL/CSV/summary; workers never inherit tokens. Output exists => fail safely; failures emit stable codes without source/policy/exception contents.

- [x] Add CLI tests for fresh output/no overwrite, JSONL/CSV consistency, model refusal and no leaked exception messages.
- [x] Implement new-process repetitions and uninstrumented semantic reference for each sample; preserve first failures.
- [x] Run CLI/targeted graph-service regressions once; record actual commands/results.

## Task 3: baseline, evidence and handoff

- [x] Measure current pilot in place via read-only access to its mirrors and independent temporary state; export only numerical measurements/SHA. Record SSH roundtrip separately from core spans and preserve all pins/hashes.
- [x] Run three fresh-process pilot repetitions with warm repeats and the existing deterministic author stand smoke; preserve raw spans, inventory counts, CPU/RSS, metadata, semantic checks.
- [x] Have one fresh reviewer inspect tooling/tests and evidence against the review focus; address important findings in one tested fix pass.
- [x] Write baseline README with raw numbers and limitations; update CHECKPOINT to 03 with next step 04. Verify JSON/CSV, source unchanged, no raw source or credentials in reports; commit locally.

## Execution ledger

Input commit: `48cd1fba1365fe6e2e4c34e3cb9a185b47d0e5dd`. Initial worktree clean. Pre-flight: Task 1 produces the same manifest/observation shape consumed by Task 2; Task 3 uses the CLI and preserves all rows. No conflicting existing benchmark implementation was found; historical scripts target an old exported core.

Task 1: complete — missing-module test observed RED; core recorder/pipeline tests GREEN. Task 2: complete — CLI privacy/no-overwrite/failure retention verified. Task 3: complete — 3 final VM processes, 1 frozen-pins reproduction, local author fixture smoke, raw artifacts and handoff.

Validation: 51 focused graph/service/benchmark tests PASS after allowing loopback HTTP; final 14 benchmark tests PASS after review fixes. No production src changes. Final VM tool SHA256 and wrapper SHA256 recorded in baseline-summary.json.

Ruling: automatic approval review rejected source/Git-object export as sensitive egress. No export was performed. The safer in-place benchmark transfers instrument code in and numeric/hash reports out, with temporary state cleaned after each successful worker. Cost: exact repeat requires access to the existing mirrors on that host; no client-side copy of the source corpus is supplied.

Final review: two P2 findings reproduced and fixed in one pass — provenance allowlist and durable per-attempt timeout/launch/JSON failure records. Additional frozen-pin forwarding tested RED→GREEN; explicit include/allowed_refs preserved. Final 14 benchmark tests green; no second reviewer dispatch. Minor limitation retained: loaded runtime SHA is a process record; only core identity is checked afresh, not a complete independent hash of all service files. Cost: no claim of full installed-package integrity beyond the stated metadata.
