# Review and execution decisions

Base0582cd8 → candidate21c9bbf/profile8 → final2d13227/profile9. Native inline execution in the existing worktree; no push/merge/deploy/API/key access.

One fresh reviewer was dispatched with the whole code range/spec/plan, focused questions and staged evidence. It reported the following before its turn failed with a model usage-limit message. It did not deliver a complete verdict, Declined-to-judge list, or review final report. No substitute reviewer was dispatched. Author completed source/evidence checks; do not describe this as a completed independent review.

## Substantive findings and one fix pass

1. `_Builder.calls` overwrote the consumer+operation edge using dependency iteration order. Mixed CURRENT/STALE calls could mark a live service edge stale or lose live witnesses. Reproduced by `test_mixed_current_and_stale_calls_keep_live_edge_and_separate_witnesses` and `test_multiple_current_calls_aggregate_all_live_relationship_witnesses`. ACTIVE now aggregates only current witnesses; historical call witnesses remain in their own STALE findings. Result is checked in both iteration orders.
2. Removal proof considered only the repository of the old witness and only head gaps. Same-service second repository could be unavailable/unsupported; incomplete base catalogue could falsely uniquely bind a template. Reproduced by missing/unsupported same-service and incomplete-base tests. Proof now checks collection/provider gaps on both phases across all authorised repositories of the service.
3. Imperative registration `app.add_api_route` was not a provider gap. New/unchanged opaque registration could masquerade as removal. Reproduced by dynamic-head/unchanged-base tests. Known imperative registration stays `provider_route_unsupported`; added/modified opaque head bases also prevent proven removal. Pure deletion of a complete provider file remains supported by a control test.
4. Replacement product output used a current relationship to the actual new head operation, but the old changed operation was not explicit enough in the risk. `test_replacement_hypothesis_explicitly_names_old_changed_operation` failed, then passed with old method/route in condition and typed risk.subject. Current calls targets the actual replacement. It remains an UNCLASSIFIED recheck, not a proven break.

Eight assertions failed in the27-test review run; all27 passed after the single source fix pass. Final graph296/performance75/service56 passed. Full original graph run284 was candidate8 with15 new tests loaded; later final graph296 includes all27. Counts overlap across focused/full runs and must not be added as independent evidence.

## Decisions and their costs

- Preserve raw head-only PARTIAL/unmapped and target_not_declared history. Only comparison with a known base can resolve the historical target. Cost: standalone undeclared-endpoint support remains unfinished.
- Preserve inherited macOS/legacy project failures; use fail-fast project run and relevant complete suites without relaxing safety limits. Cost: no all-green global CI/release claim. Candidate global run stopped after305 tests on previously documented graph_demo CLI deadline mismatch; final9 has relevant full suites, no new full project pass.
- Keep scorer/normalizer unchanged during this measurement/author repetition. Replacement product output explicitly distinguishes old changed vs current routed operation, but the evaluator still keys it by current target rather than delta. An exact pinned diagnostic reproduces this limitation. Cost: replacement normalization is not quality-verified by author40 and requires a versioned fix before independent06; no denominator/output filtering was used to improve metrics.
- Fresh reviewer was interrupted by usage limit. Finish artifact verification and source checks as author, preserve findings, no clean-review verdict or second seat. Cost: final fixes/report still require completed review before release10.

No complete Minor/Declined-to-judge list was delivered; absence of such a list is not evidence of no remaining issues. Known method limitation above is explicit, not silently waived.

## Evidence preservation

Before-profile7 timing finished before source changes. Candidate profile8 timing5/50k finished,10/100k interrupted by SIGINT after known review defect. All available records/interruption logs remain under superseded; no candidate8 number enters final timing comparison. Final9 stage timing has no overlap with verification suites or acceptance/quality jobs; those diagnostic jobs run in parallel only after timing ends.

Initial sandbox graph run was interrupted because local sockets/child processes were restricted; native suite passed. Initial75 performance run compared different generator source hashes because the generator changed while the run was active. Its single determinism failure is retained; a stable75 passed on candidate8 and final9. These earlier failures are not rewritten as successful runs.

Author inputs/order/seed/cap/oracles/scorer/normalizer remain unchanged. The27 tests and replacement diagnostic are development checks, not additional independent cases or humans. Runtime a02ffa7 was not newly inspected or replaced in this package.

Decision: accept baseline10/100k dirty=true with explicit untracked test/spec/plan disclosure and code fingerprints matched to Git0582cd8; final9 manifests are clean. Cost: baseline has author/fingerprint evidence rather than a clean/signed historical whole-tree snapshot. No raw metadata was changed.
