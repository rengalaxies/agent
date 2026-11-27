# Whole-batch review and fix pass

Baseca81bfb → sourcefd3dbc3, static profile9/schema2.2. One fresh read-only reviewer on gpt-6.1-terra; Astra was unavailable by a previously observed account usage limit. No second reviewer or re-review seat. Reviewer independently ran verifier --current-core --private PASS on the initial41 artifacts/737 historical hashes, inspected raw4 workers/reference/prior comparisons and actual5+1 queue verdicts. It did not rerun source suites. Verdict: With fixes; no Critical source issues.

## Findings and one fix pass

- I1 Important: unit log alone did not retain actual per-file omission. Added real WORKTREE and pinned-Git context receipts on65 537-byte file: PARTIAL/file_limit, oversize omitted, other sources/graph present. Safe metadata and reproducible recipe retained; verifier checks both modes/default values. Production code unchanged.
- I2 Important: all([]) could bless missing queue verdicts; duplicated generation could replace another result. Two mutation controls on copies rebuild the changed raw hash so a checksum error cannot masquerade as a semantic check. Both tests failed on the original verifier and passed after checking len==analyzed_jobs==expected plus unique(resource_id,generation), actual statuses/counts and no gaps. Positive full verifier also passes. Original raw results unchanged.
- M1 reviewer Minor, executor regraded Important: the documented new-root recipe could not start, and could write input before noticing an existing benchmark output. This blocks reproducibility rather than polish. Added mkdir plus upfront reserved-output checks to the recorded recipe. Actual original prefix fails two bootstrap controls; new prefix passes fresh-root creation and refusal with retained sentinel. Benchmark commands/measurement logic unchanged; no timing rerun necessary.
- Operator counter documentation corrected before verdict: GitReader omissions can be outside inventory/max_files; some skipped blob sizes still spend byte budget. No collection mechanics changed.

No unresolved Critical/Important from this review; no deferred Minor after M1 effect-based regrade. Fixes verified by executor rather than second review. Source suites remain graph302/performance75/service104 and focused12 GREEN; metadata/bootstrap controls2+2 GREEN and complete artifact/source/private-input verification PASS. Tests overlap and counts are not independent research evidence.

## Rulings on the reviewer's Declined to judge list

1. Independent06 not run; this package's authored resource fixtures are not independent cases. Cost: real quality remains unknown until new hidden cases/humans.
2. No arbitrary8MB capacity/production p95/steady-state claim from bounded sparse corpora and uncontrolled caches. Cost: real dense workloads and target-stend budgets still need study.
3. No external tracker/network/VM/deploy acceptance here. Defaults are local source; explicit old policy and installed runtime retain their values. Cost: deployment/live behavior must be verified in10.
4. Replacement binding/normalizer, Yandex09, general CI and release10 remain separate open work. Cost: independent06 and overall release cannot be marked complete by this package.
5. Existing Git gap/inventory counting preserved and documented. Cost: max_files is not a cap on every omission; separate traversal/time budgets remain relevant on dense unsupported trees.
6. MODEL OFF; no new claim about model qualifications for different code/policy. Cost: qualification must be checked before later model enablement.

## Evidence boundaries

All stage timing completed before queue/negative capture/review mutation controls; sourcefd3 frozen throughout. Actual input Policy omitted limits, shared validator and CoreAnalyzer used new defaults. Prior immutable8MB positive semantic hashes and canonical facts match exactly; refusals intentionally changed to explicit budget_exhausted. Source grammar/profile/normalizer/scorer/dependencies unchanged. Historical737 report files and original private corpus manifests/oracles protected by hashes.

Initial RED/import/worktree-pinning fixture mistakes and corrected baseline-CoreAnalyzer RED are retained. The source checkout was never reset. Global project CI was not repeated; previously documented graph_demo CLI deadline issue remains open. No performance acceleration, independent-quality improvement or deployment is inferred.
