# ImpactMap batch 04 — scale corpus preparation

> Execute inline with superpowers:executing-plans and TDD; one final fresh-agent review. Reuse the current managed worktree. No VM actions or external data transfer.

**Goal:** reproducible controlled Git corpora 5 repos/50,000 and 10 repos/100,000 analyzed nonblank noncomment Python lines, separate growth axes with recorded file-count confound, known dependencies and explicit lifecycle/access cases.

**Architecture:** `tools/prepare_impactmap_corpora.py` reuses existing deterministic Git plumbing from `examples/orders_reporting/stand.py`. Generated sources/objects and absolute benchmark inputs stay in ignored work/. Portable manifests/oracles and preparation evidence are committed under experiments/impactmap_scale/corpora/. A separate verifier reads actual pinned Git sources through the existing core and compares controlled facts; it is not an independent quality experiment or a load runner.

**Tech Stack:** Python standard library, existing Policy/Graph/GitReader and stand helpers. No new dependency; production src unchanged.

**Spec:** batch 04 in `/Users/user/Documents/ChatGPT/ВКР/ImpactMap_пачки_и_передача_контекста_2026-11-14.md`; research/evaluation/protocol-v1.md; current CHECKPOINT and batch-03 benchmark contracts.

## Decisions and constraints

- Generation v1, seed 20261114. Source snapshots, commit author/date/messages and PR sequences deterministic and independent of output path. Existing output refused.
- Same closed Python HTTP/API grammar: eight FastAPI operations, explicit requests calls, one provider and up to three active consumer services. Last repository starts unrelated to operation 0 and becomes its new consumer in a named variant. Noise is valid ordinary arithmetic Python, counted from bytes, not blank/comment padding.
- Fixed scale-preparation policy: max_files=2048, max_file_bytes=65536, max_corpus_bytes=8000000, scan_seconds=60. Product defaults remain unchanged and are recorded alongside these explicit test limits. Raising test limits is not proof of current default capacity.
- Six profiles: 5/50k and 10/100k mandatory; 10/50k separates repo count, 5/100k separates size, 5/50k with eight operations per active consumer varies graph density, 5/1k is the noise-invariance anchor. Same topology for repo/size axes; no new languages.
- Variants: main/base, provider page-default changes (10 sequential heads and 10 independent PRs), new consumer in a formerly irrelevant file, removed consumer call, removed operation, unavailable source via absent configured root. Access fault is not a claim of real credential revocation.
- Streams of 1/5/10 changes specify both updates to one PR and independent PR IDs; preparation does not claim queue throughput, tested in 05.
- Ruling: generated corpora/oracles are controlled development/performance material, not new independent cases for 06. Cost: no inference about real-project quality or demand.
- Ruling: hold active consumers/topology fixed across repo/size axes. Cost: large low-density corpora are deliberate one-axis stressors; denser variant is separate.

## Review focus

1. Claimed LOC and bytes must equal actual pinned source content; comments/blanks are reported separately.
2. Same seed/config produces identical trees/commits/manifests in different directories; generated output never overwrites existing data.
3. Known dependency/callsite maps come from generation records, not copied from extractor output; noise must not change located findings.
4. A new consumer must be found after a prior negative snapshot, removed calls retract, missing access remains PARTIAL and preserves scope honesty.
5. Scenario pins, stream ordering/IDs and portable paths must be usable by the existing benchmark without leaking oracle into analyzer input; effective limits and provenance remain explicit.

## Task 1 — generator and manifests

**Files:** tools/prepare_impactmap_corpora.py; tests/performance/test_scale_corpora.py.

**Interface:** `generate_corpus(output, repositories, python_lines, seed=20261114, calls_per_consumer=1)` writes new Git repositories, portable corpus-manifest.json/oracle.json and benchmark-input.json. `load_benchmark_input(corpus_root, scenario='baseline')` resolves only generated relative roots and explicit scenario pins to the batch-03 input contract. `suite_specs()` defines the six profiles; CLI `--suite --output NEW_DIR`.

- [x] Write failing tests for reproducibility/path independence, exact actual counts, safe no-overwrite, oracle edges and benchmark input/stream pins.
- [x] Observe missing implementation failure, implement minimal deterministic generator using the existing Git plumbing.
- [x] Verify seeds affect generated content; file sizes/counts fit declared limits; no sources executed and no package installation.

## Task 2 — lifecycle/noise/access verifier

**Interface:** `verify_corpus(corpus_root, state_root)` reads actual main/base/head through Graph/GraphStore, returns counts, topology checks, new-consumer and removed-call observations, explicit partial-access observation and portable evidence only. `finding_projection` compares semantic keys/witness locations without pretending different commit receipts are equal. `verify_noise_pair(anchor, large, state_root)` compares located findings for equal topology.

- [x] Add tests for new consumer after base negative, removed call and missing source; expect real core behavior, never stub extractor answers.
- [x] Add noise invariance test against actual findings and evidence locations with explicit version-metadata exclusion.
- [x] Implement verification and run targeted tests plus existing graph and benchmark regressions.

## Task 3 — prepare and verify actual scale profiles

- [x] Generate all six profiles; derive per-file/repository counts and commit/tree SHA from actual Git objects; save portable recipes/manifests/oracles and JSON preparation evidence.
- [x] Verify the 5/50k and 10/100k corpora against their known graph facts; verify lifecycle/access and noise anchor checks. No cold/warm load/queue acceptance or fixes claimed in 04.
- [x] Run one fresh-agent review, address important issues in one tested pass; retain any measured limitation explicitly.
- [x] Update corpus README and CHECKPOINT with actual counts/versions and next step 05; verify artifacts/paths/checksums and commit locally.

## Ledger

Input commit `484b00129922668271fe3a1a785129121becfba2`, worktree clean. Task 1 produces the exact batch-03 input shape consumed by Task 2 and 05; source default limits are preserved, test limits named separately. Existing stand helper already supplies deterministic Git identity and no-checkout object construction.


### Execution and final evidence

- Followed TDD for generator and lifecycle checks; twelve new tests use real pinned Git/core. Path independence, seed effect, actual source counts/hashes, no overwrite, input/oracle separation, traversal, mutable-limit isolation and stream pins covered.
- One final review exposed incomplete findings acceptance; reproduced RED, added full expected baseline/new-consumer findings and head edge equality. Noise now checks witness locations/quote hashes; operation removal now analyzed.
- Strict dense preparation exposed stale oracle line positions after deleting the first client function. Added dense lifecycle RED; captured regenerated head positions; GREEN. No product behavior change and no weaker line comparison.
- Final generation command: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m tools.prepare_impactmap_corpora --suite --verify --output work/batch04/corpora-v1 --seed 20261114`. All six profiles PASS. Four large sparse profiles equal the 1k anchor on all three located findings including checked witnesses; both full verifications gate the comparison.
- Final tests: `python -m unittest tests.performance.test_scale_corpora tests.performance.test_benchmark_impactmap tests.performance.test_benchmark_vm tests.graph.test_graph_store tests.graph.test_git_sources -v`, same PYTHONPATH/venv: 54 tests in 56.381s, OK. Log committed with preparation evidence.
- Default-limit probe rerun against final corpus-v1 pins: 5/50k readable; 10/100k throws `corpus_limit` (2,536,458 bytes > default 2,000,000). Explicit test limit 8MB recorded, product defaults unchanged. No VM actions, source execution or external transfer.
- Portable artifacts at `experiments/impactmap_scale/corpora/`; generated source/Git/SQLite/absolute inputs remain ignored under work/. Superseded weak-verifier and dense-failure series distinguished from acceptance.
- `CHECKPOINT.md` updated for next batch 05; preserve current worktree and branch. Local commit only, no merge/push or archive requested. Final artifact checks and commit recorded by Git history rather than a self-referential SHA.
