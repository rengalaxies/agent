# ImpactMap05 removal mapping and measurements plan

> Execute inline with executing-plans/TDD, one fresh final reviewer and one fix pass. Reuse current codex/impactmap-batch-00 worktree.

**Goal:** report current consumers of a removed operation with verified head evidence and repeat controlled measurements after profile9.
**Architecture:** one comparative remapping pass using the full base catalogue cross-checked against current mappings; exact-position gap resolution, conservative historical fallback, immutable contexts. Standalone graph semantics remain honest.
**Tech:** existing Python/AST/Git/CoreAnalyzer/queue, unittest, existing benchmark/evaluation tooling, no dependencies.
**Spec:** docs/superpowers/specs/2026-11-15-impactmap-removal-mapping-design.md

## Global constraints

- Base0582cd8; no push/merge/deployment/API writes/credential transfer; original reports and private state preserved.
- Native execution; owner already delegates routine implementation choices. MODEL OFF, existing Python HTTP/API grammar.
- No blanket gap removal, fake head declaration, independent experts/quality or performance SLO claims.
- Keep head-only PARTIAL/unmapped diagnostics, access/ambiguity protections, historical target_not_declared history.
- Named test limits8MB/60s; defaults256files/65536bytes-file/2MB/15s unchanged. Sequential timing,3 independent processes/profile, OS caches not reset.

## Review Focus

- Same-line call positions must not clear another unresolved gap.
- Missing provider declaration is not proof of removal when access/grammar is incomplete; wrong method/host/ambiguity must not force mapping.
- A removed/moved caller differs from an opaque/unavailable caller; preserve uncertainty without presenting historical source as current.
- Template matching/current declarations and new callers must use authorised head evidence, not cached historical source/rows.
- No measurement or scoring success may hide earlier failures, changed inputs, partial source coverage or changed publication states.

### Task 1: removal remapping and evidence

Files: new src/agent_graph/removal_mapping.py; engine.py/discovery.py/results.py/__init__.py; tools/prepare_impactmap_corpora.py projection/expected freshness; focused graph/core tests.
Interfaces: comparative removed_dependencies/resolved_removed_calls metadata in analysis, exact call_column, existing AnalysisResult2.2 fields. No persistent graph migration.

- [x] Write real Graph/result regression tests: unchanged/new/moved/removed callers, inaccessible/opaque caller, template/selected scope, unknown host/method/ambiguous policy, two calls on one line and immutable contexts. Run RED.
- [x] Implement one current-source remap with proven base targets; exact-position gap reconciliation, conservative STALE fallback. Head-only graph remains unchanged; public result cites correct phases. Bump PROFILE9.
- [x] Update only intentional current-call freshness expectations and benchmark projections; run graph/core/publisher/quality regressions GREEN, preserve historical artifacts.
- [x] Local commit. Expected: no new unresolved functional failures.

### Task 2: controlled repetition, review and handoff

Files: new experiments/impactmap_scale/removal-2026-11-15 report/receipts, CHECKPOINT and remaining roadmap.
Interfaces: existing pinned batch04 corpora and benchmark/load/calibrate tools. New outputs only.

- [x] Before source changes, stage measurements profile7:5/50k and10/100k,3 independent processes each, named existing test limits. Save core hash and sequential campaign ledger.
- [x] After stable profile9, repeat exact manifests sequentially, same3-process protocol. Compare counts/pins/facts/semantic reference and wall/CPU/RSS without p95/causal speed claims.
- [x] Verify default probes and full/event equality including deletion, call removal and incomplete access. Run bounded real queue/replay using controlled local transport, not external API.
- [x] Repeat original author40/80 after tuning with unchanged scorer/oracle; preserve FAILED/unregistered cases and historical reports.
- [ ] Completed fresh final verdict remains a release10 gate: reviewer delivered findings then hit usage limit. One RED→GREEN fix pass and author verification complete; repeat affected checks/measurements only if source changed. Project check uses fail-fast because known legacy/macOS CI is already red; report every observed failure/skip by name.
- [x] Exact artifact hashes and source checks, report, CHECKPOINT mirror, local commits only. Keep managed worktree.

## Rulings

Standalone head graph retains genuine unmapped/PARTIAL state — it has no baseline proof of deletion. This batch fixes comparative PR mapping rather than inventing provider declarations; cost: standalone undeclared-endpoint support remains future work. Whole-project CI inherited macOS/legacy failures are preserved; no unrelated limit weakening.

Final profile9 supersedes the interrupted preliminary profile8 after one review fix pass. Provider proof covers all authorised repositories of the service on both phases; unsupported imperative registration stays a visible gap. Mixed current/historical calls aggregate only live evidence into ACTIVE service edges, while STALE findings retain their own witnesses. Replacement risk names the old operation explicitly; unchanged evaluation normalizer target-key mismatch is a disclosed limitation, not quality-verified by author40. Fresh reviewer stopped after substantive findings due model usage limit; author completes final evidence checks with no completed-review claim.

Execution evidence: experiments/impactmap_scale/removal-2026-11-15/README.md. Final core2d13227; graph296/performance75/service56 GREEN,12 stage workers/reference-equal,8 acceptance checks PASS,author40/80 repeated,383 historical hashes preserved,private rescoring PASS. Fresh whole-batch reviewer did not complete; report states the limit explicitly. Normalizer replacement binding remains separately versioned next work.
