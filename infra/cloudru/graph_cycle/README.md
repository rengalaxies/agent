# Cloud.ru graph model cycle

This is an integration experiment, not acceptance of the graph core or VM/demo deployment. Owner authorization covers Foundation Models grant use and at most 40 model HTTP requests for this experiment, including diagnostics. No new resources or secret/variable settings are created.

## Pinned inputs and acceptance

- Main integration base: `08a52704269c75d8d78a8fcf4ed8b9f10cf45722` (accepted PR #30).
- Graph core: `f1c4546725e759ffc06ca0281f7103132dbcfe73` from [PR #28](https://github.com/rengalaxies/agent/pull/28), still open/draft; no independent review submission was present at inspection. Candidate-only results cannot authorize installing that core on a VM.
- Demo specification and plan: `778b7668fd78e7c9dbaa8c0e6ce07b48ce9d82e4` from [PR #29](https://github.com/rengalaxies/agent/pull/29). Neither branch is modified by this work.
- No AGENTS.md in the inspected main/core repository trees or workspace.
- `experiment.json` pins models, budgets, synthetic cases and published prices; `expectations.json` is the held-out oracle, copied and hashed before calls. The latter is read for scoring only after the model cycle ends and is not in the authorized corpus or model messages.

## Reuse and boundaries

The runner uses the candidate's `ChatModel.complete`, `investigate`, source collection/discovery, `get_evidence`, `Graph.propose`, durable budget reservations, capabilities, freshness checks and OS installation lock. `adapter-observer.patch` adds an optional callback around HTTP send/status and a whitelist of numeric usage/finish-reason metadata, plus optional operator-supplied continuation messages. Defaults are unchanged. JSON-schema validation, evidence validation, redirect behavior, deadlines, secret selection and monetary guard are preserved. Only this runner supplies continuation history, after revalidating every source quote against the exact current basis. This isolated patch is applied only to the exact temporary core checkout; its SHA256 is recorded in the report.

The required protocol is non-streaming Chat Completions with `response_format=json_schema`, finite JSON actions `read_source`, `propose`, `finish`, user messages carrying untrusted tool evidence, and validated `prompt_tokens`/`completion_tokens`. The existing core rejects native `tool_calls`; this experiment does not claim native function-calling qualification. Its reuse of JSON actions is explicitly the product's current tool protocol.

Model context starts with a source inventory, task and core gaps. It contains no prebuilt dependency map or oracle. `read_source` resolves only listed source IDs through the existing scope/line/quote checks. Model proposals remain `UNAPPROVED_CANDIDATE`; provenance acceptance is not semantic correctness. The separate scorer requires actual reads before proposing, exact expected dependency keys and both provider/callsite citations. Extra keys and the Status/Orders confusion fail quality even if the provenance validator accepted the quotes. Statements also require human review; the key-based score is not a general semantic judge.

Cases derive from the candidate's synthetic corpus:

| Case | Held-out expectation | Construction |
| --- | --- | --- |
| reporting-http | Reporting → Orders GET /orders | Existing Reporting client and Orders provider copied unchanged |
| export-E | A newly active Export → Orders dependency | Initially inactive source in an already allowed Export root; activate existing paginated Export source before model investigation, confirm same policy view and 0 → 1 static edges |
| status-decoy | Health → Status; never Health → Orders | Existing Health calls inventory.test/orders; operator address maps inventory.test to a distinct Status service. Copy the existing provider declaration into Status; Orders is present as a decoy with the same path |

The full PR #29 runnable demo corpus is not yet in the pinned core. These are documented, supported static-source adaptations, not a claim of testing a deployed A→B→D→E service demonstration. The E transition and Status identity are measured before the LLM; their expected answers are not sent to it.

## Budgets and ordering

One case at a time: Qwen Reporting first, then remaining Qwen cases, then the same three GPT cases. The first complete Qwen cycle must pass protocol, proposal/evidence quality and validator admission before the remaining series runs. Any protocol/budget failure stops the experiment without a retry. A quality failure later in the series is retained separately and does not masquerade as a protocol failure.

Per case: at most six HTTP sends/JSON-action steps, 4096 output tokens/request, 45-second request deadline and 300-second case cancellation. A single timer spans the case; the core still owns cancellation through DNS/TCP/TLS/send/headers/body. Per-installation OS lock and charged reservations remain enabled. A conservative SQLite ledger counts before send, keeps failures charged, caps the entire invocation at 40, and each model/case at six. The six-case initial series cannot exceed 36; four calls are left for separately reviewed diagnosis, not automatic retries. The core additionally caps prompts at 24000 bytes, conservatively reserves 100000 token units/run and 1000000/install, with nonzero corporate money caps. Those reserves are not actual usage.

Actions reruns (`run_attempt != 1`) are blocked. The workflow uses a unique concurrency group and never cancels an active experiment to start another. **Do not create another series run for the same authorization** without carrying forward the previous request count and reviewing the remaining allowance. The ledger is durable within the job, not an account-wide cross-run billing service. No automatic retry is dispatched. A separately diagnosed, budget-carrying continuation is documented below.

### Diagnosed continuation of the first case

[Initial run 39611545230](https://github.com/rengalaxies/agent/actions/runs/39611545230) made three Qwen sends, all HTTP 200 with observed usage (2835 input, 524 output). It read both sources, then returned a schema-valid but action-invalid proposal: non-null read fields on `propose`, source hashes in the dependency key, one typographic/inexact quote, and missing callsite citation. `investigate` returned PARTIAL/invalid_model_action before calling `Graph.propose`; **no proposal was admitted**. Estimated observed usage cost: 0.473726 RUB; actual billing unknown. Remaining cases were not run.

The initial safe evidence is retained under `lab/reports/graph-cycle-2026-10-21/initial/`, pinned in the continuation source commit and hashed in its manifest. The correction clarifies null action fields, repository/service names, two exact citations and the operator's address-to-service mapping; it does not supply a dependency answer or relax any validator. Continuation replays only the two actually performed reads after checking their source IDs, bounds, exact quotes, metadata and corpus basis through `get_evidence`. The rejected assistant action is retained with an explicit generic protocol rejection, never converted into an accepted proposal.

The diagnosed continuation is a new controlled workflow-file push, not a rerun or automatic retry. It seeds the ledger with the previous three requests, carries forward all 38063 reserved token units / 9287372 reserved micro-RUB, reduces the first case to at most three further calls, and subtracts previous active case execution time from its deadline. Manual offline diagnosis time is separate and not represented as model execution time. Thus the same Reporting case remains bounded by six requests, 100000 reserved token units and five minutes in total. The entire initial series including the carried diagnosis can still use at most 36 of the owner's 40 requests. No further continuation is scheduled automatically. Tests cover the real validated replay, snapshot mismatch rejection, inherited budgets and an entire scripted continuation before any new live send.

[Continuation 39612624655](https://github.com/rengalaxies/agent/actions/runs/39612624655) used one additional send, HTTP 200: the action fields and dependency key were corrected, but exact quote/line checks rejected the proposal with `evidence_mismatch`. Four sends total, observed 4642 input / 786 output tokens, estimate 0.758108 RUB. The safe result is in `continuation-1/` alongside the initial run.

The final diagnosed continuation preserves all four sends and all 53240 reserved token units / 12990560 micro-RUB. At most two sends remain for this case. Source-tool observations are now rendered with `numbered_lines` as well as the unchanged raw quote; the same rendering is applied to validated replayed reads. This fixes an information-presentation weakness (manual line counting and unnumbered quote text), not model output: curly quotes and wrong bounds remain invalid, no normalization or automatic citation repair is performed. The continuation includes generic evidence-mismatch feedback, not an expected dependency answer. A failed final first-case gate ends the experiment; no further first-case request is permitted by this package.

### First-case review and remaining distinct cases

[Run 39613302638](https://github.com/rengalaxies/agent/actions/runs/39613302638) used one further Qwen request (five total). Numbering fixed the client line number, but typographic quotes and missing indentation still failed exact evidence validation. No candidate was admitted. Observed cumulative usage: 6672 input / 1047 output; estimate 1.069452 RUB. Safe evidence is retained in `continuation-2/`.

The first-case inspection is now complete: HTTP/usage/structured action format are compatible, but the candidate has failed evidence quality and the existing validator correctly rejects it. The strict predeclared `protocol_passed` criterion (`COMPLETED` investigation) remains **false**, as does quality; neither the oracle nor the failed result is rewritten. A separate `transport_action_protocol_passed` field distinguishes valid HTTP/JSON/action exchange from validator rejection. `review.json` documents this assessment. This prevents conflating a protective rejection with a transport incompatibility.

The earlier orchestration required a positive quality result before continuing, which was stricter than the owner's instruction to inspect the first cycle and then compare the remaining cases. After that inspection, the remaining five distinct model/case pairs are executed once. First Qwen Reporting is frozen at five sends and is never called again. The ledger carries all five sends and 69699 reserved token units / 17006556 micro-RUB. Total maximum is now 5 + 5×6 = 35, within the original 40. Validation failures are recorded as failures of evidence quality with PARTIAL investigation, while malformed messages, transport errors or budget stops still terminate further sends. The negative result is retained rather than selecting only successful proposals.

The prompts/tool rendering changed after the first Qwen diagnosis; GPT uses the clarified version without that debugging history. This is an exploratory integration comparison, not an unbiased model benchmark or evidence of product advantage over a coding agent. Read individual statements/citations and all raw safe reports alongside scores.

## Security and reproducibility

Only the live step receives `CLOUDRU_FOUNDATION_API_KEY` via GitHub Secrets. No IAM/SSH/Workflow Studio credentials, environment dumps, SDK debug logs, arbitrary URL/ref input, `pull_request_target`, or untrusted PR checkout with secrets. The model endpoint is fixed HTTPS and the core makes no redirect or endpoint fallback. Source code is never executed; synthetic AST/quote inspection only.

Reports whitelist numeric HTTP/usage metadata and store only synthetic messages, validated actions, proposals, validator decisions, manifests, timing, budgets and scores. No raw response/headers or hidden reasoning is saved. Serialization additionally replaces any exact occurrence of the injected secret, including malicious model echoes. Only `graph-cycle-report/` is uploaded; private SQLite state/ledger is its sibling and excluded. A cancelled/invalid response may lack usage: it remains unknown, never synthesized as a complete zero-charge call. Provider usage is not billed cost.

Prices inspected on 21 October 2026 from the [official model catalog](https://cloud.ru/products/evolution-ai-factory/catalog-foundation-models): Qwen input/output 122/244 RUB per million, GPT 15.86/61 RUB per million. [Pricing documentation](https://cloud.ru/docs/foundation-models/ug/topics/pricing) directs users to tariffs/model cards. The formal tariff appendix timed out during retrieval; account-specific taxes/discounts/cache/billing are not asserted. Reported estimates use observed input/output usage at those published rates; `actual_billed_cost=NOT_MEASURED`. Core reservations conservatively use the larger input/output rate, preserving a nonzero corporate guard (24.4 RUB/Qwen run; 6.1 RUB/GPT run; 244 RUB/installation reserve ceiling). These are safety reserve ceilings, not a spending target or provider-enforced account quota.

### Local verification without credentials

```bash
git worktree add --detach ../graph-core-candidate f1c4546725e759ffc06ca0281f7103132dbcfe73
git -C ../graph-core-candidate apply ../cloudru-graph-experiment/infra/cloudru/graph_cycle/adapter-observer.patch
python3 -m venv work/venv
work/venv/bin/pip install -r infra/cloudru/graph_cycle/requirements.lock
GRAPH_CORE="$PWD/../graph-core-candidate" work/venv/bin/python -m unittest discover -s infra/cloudru/graph_cycle -v
PYTHONPATH="$PWD/../graph-core-candidate/src" work/venv/bin/python -m unittest discover -s ../graph-core-candidate/tests/graph -v
work/venv/bin/python infra/cloudru/graph_cycle/run.py --core ../graph-core-candidate --output work/prepared-cycle
```

The observation-only patch is not reapplied if already present. Core regression needs permission to bind local HTTP stub sockets, not Cloud.ru credentials. The test-only scripted replies exercise the real research tools and validator and are not live model evidence.

### Actions launch

`.github/workflows/cloudru-graph-model-cycle.yml` has a deliberate first live `push` trigger restricted to the owner-controlled `codex/cloudru-graph-model-cycle` branch and workflow-file path. This makes the initial authorized experiment runnable before default-branch dispatch registration; it is not triggered by arbitrary PRs or by source/report edits. Only push the workflow after all code/tests/oracle are committed and reviewed locally. Checkout is the exact push SHA plus the hard-pinned core SHA. This PR is **draft and must not be auto-merged**.

Dispatch (`prepare` default, `series` explicit) is also declared, but a new dispatch-only workflow may require default-branch registration. Do not promise dispatch from an unregistered branch or merge this PR merely for a button. When GitHub supports dispatch for the registered workflow:

```bash
gh workflow run cloudru-graph-model-cycle.yml --repo rengalaxies/agent --ref codex/cloudru-graph-model-cycle -f mode=prepare
# Only if this experiment has not already consumed its one initial series:
gh workflow run cloudru-graph-model-cycle.yml --repo rengalaxies/agent --ref codex/cloudru-graph-model-cycle -f mode=series
gh run list --repo rengalaxies/agent --workflow cloudru-graph-model-cycle.yml --limit 5
gh run watch RUN_ID --repo rengalaxies/agent --exit-status
gh run download RUN_ID --repo rengalaxies/agent --dir work/graph-cycle-results
```

If stopped, read safe HTTP codes, finish reasons, observed usage and the retained proposals first; diagnose and test locally before any further authorized model sends. Do not use the old model workflows or the 16-token connectivity probe as a substitute for this cycle.
