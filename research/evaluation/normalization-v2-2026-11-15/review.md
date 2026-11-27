# Whole-batch review and rulings

Reviewer: fresh-context `review_normalization_v2_final`, gpt-6.1-terra/high, read-only; source range0841a90..1954f49 plus new report artifacts. One reviewer, no implementer delegation or second review seat. This is engineering review by a model, not a human quality expert or independent research06.

## One substantive RED→GREEN pass

| Finding | Severity/regrade | Decision and evidence |
|---|---|---|
| I1 caller blob contradiction could retain a scoring witness | Important, accepted | Shared evidence validator applied before caller witnesses. Wrong-blob control gives no witnesses and synthetic strictTP0; it is a regression fixture, not a new author/independent case. |
| I2 two direct typed subjects could credit the same ambiguous anchor | Important, accepted | Resolve per anchor; conflict retains UNBOUND. A separate unambiguous caller anchor remains usable for its target. |
| I3 affected row with missing/empty/non-string refs could disappear | Important, accepted | Named warning retained as UNBOUND with `/affected/0` raw pointer. |
| I4 malformed evidence.repository list/dict could crash normalization | Important, accepted | Type guards in audit/consumer/provider lookup; output invalid, later addressed warnings remain visible, no process crash. |

[review-red.log](tests/review-red.log):27 tests,6 failures and6 errors. [review-green.log](tests/review-green.log):27/27 OK. Broader final suites102/102 and58/58. Source fixes complete before source1954f49/replay/new80, with no source changes during either series.

## Rulings

- Preserve protocol-v1/schemas/scorer/gold/input membership/historical raw; new protocol2 and config identity are explicit. New version does not make an unsigned author freeze registered.
- Same-service caller/provider requires callsite role; otherwise retain UNBOUND. An off-delta alternative counts as ambiguity rather than being silently pruned.
- Invalid caller citations never yield witnesses; independent valid evidence for the same key may still count under the unchanged aggregation/scorer rules. No blanket label-based filtering or scorer change.
- Preserve old replacement diagnostic exactly, including its `schema_id` serialization defect; both versions output-invalid/no TP credit. New valid controls establish the binding defect separately. The initial recipe's wrong `schema_` assertion failed before this disclosure; preserve log, correct recipe only, finish historical substep separately. No product/campaign retry.
- Keep old CLI0.4s failure as a10 task: relevant suites pass, full project CI not asserted. Preserve branch/worktree/local commits; no merge/push/deploy menu needed because existing task scope already selects local handoff.
- The task-done helper copied expected negative CLI stdout into its one-line ledger result. Actual unittest verdict102/102 OK and process exit0 are retained; the stdout string is not a suite failure.
- Only this plan's temporary skill workspace is cleaned after evidence is copied; report/work/corpora/worktree are retained.

## Final artifact verdict

Observed verdict: **готово с принятыми исправлениями**. Same reviewer checked README/review/recipes/source identity and the replay/fresh distinction, then independently ran portable verifier: PASS342 artifacts/922 protected files/80 assigned receipts/40 replay outputs. No additional Critical/Important found. Review was completed after the four accepted source fixes; no second reviewer/re-review cycle.

Declined to judge, exhaustively: (1) full project CI/CLI deadline, open10; (2) quality on independent real cases and threshold approval, absent data/registration; (3) independence/authenticity of future human labels, absent humans in this series; (4) installed worker/product operations/integrations, not deployed in scope; (5) private inputs/private rescoring not independently executed by reviewer. Private verifier PASS is the implementer's observed check, not a second execution by the reviewer. These limitations remain open in the handoff.
