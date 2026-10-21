# Foundation Models: GitHub configuration audit and bounded qualification

Audited `main` at `5c8daf78d34d510d48ecd9b1e194678bb13ed00c` and the description/implementation plan of [demo PR #29](https://github.com/rengalaxies/agent/pull/29), plan commit `778b7668fd78e7c9dbaa8c0e6ce07b48ce9d82e4`. This PR prepares model qualification only; it does not execute the VM/demo implementation plan.

## Found configuration references

All 50 existing `.github/workflows` files were inspected for secret/variable references and environment declarations. References establish intended use, not current existence, scope or entitlement.

| Purpose | Referenced names | Evidence |
| --- | --- | --- |
| Infrastructure IAM | Secrets `CLOUDRU_KEY_ID`, `CLOUDRU_SECRET` | `cloudru-discovery.yml`, `cloudru-access-audit.yml`, protected apply; IAM token exchange and scoped compute/container reads |
| Encrypted Terraform/S3 state | Secrets `CLOUDRU_STATE_SSE_CUSTOMER_KEY`, `CLOUDRU_STATE_ACCESS_KEY_ID`, `CLOUDRU_STATE_SECRET_ACCESS_KEY` | State/preflight workflows; some code derives S3 credentials from IAM credentials when dedicated state credentials are absent |
| Infrastructure configuration | Vars `CLOUDRU_TENANT_ID`, `CLOUDRU_STATE_BUCKET`, `CLOUDRU_STATE_S3_ENDPOINT`, `CLOUDRU_STATE_REGION`, `CLOUDRU_ADMIN_CIDR` | Protected apply, state and credential preflight |
| SSH | Secrets `CLOUDRU_SSH_PUBLIC_KEY`, `CLOUDRU_LAB_SSH_PRIVATE_KEY`, `CLOUDRU_LAB_SSH_KNOWN_HOSTS` | `lab-preflight.yml`; scoped SSH/source delivery also uses encrypted recovery credential and independently pinned host key |
| UI authentication | Secret `CLOUDRU_UI_BASIC_AUTH_HASH` | Protected apply/recovery and lab preflight; unrelated to model authentication |
| Workflow Studio | Secret `CLOUDRU_WORKFLOW_API_KEY` | Workflow diagnosis and access audit; not a Foundation Models credential |
| Foundation Models | Secret `CLOUDRU_FOUNDATION_API_KEY` | `lab-agent-ci.yml`, `lab-product-ci.yml`, `lab-preflight.yml`, old model probe |
| Other LLM configuration | Secret `CLOUDRU_LLM_API_KEY`; vars `CLOUDRU_LLM_BASE_URL`, `CLOUDRU_LLM_MODEL` | Lab preflight. Real-agent workflows default to `openai/gpt-oss-120b` if the model variable is empty |

`cloudru-apply-protected.yml` and `cloudru-recovery.yml` explicitly target Environment `cloudru-p1-production`. Existing model jobs do **not** select an Environment. This establishes workflow lookup context, not where each secret is stored. New qualification also does not select/create an Environment: it can resolve repository secrets or organization secrets made available to this repository. An Environment-only key would remain unavailable to it until a reviewed change selects the actual Environment.

## Metadata access limits

The connected GitHub tools confirm authenticated repository access, but expose no list-secrets/list-variables/list-environments capability. Their generic GET tool explicitly excludes secrets APIs and unlisted endpoint families. No attempt was made to bypass this with a runner token or to copy credentials into Codex. Current secret names, existence, precedence, organization visibility and Environment policies therefore remain **UNVERIFIED**, not absent. Repository owner `rengalaxies` is a GitHub User, not an organization; no organization ownership is inferred. The reference table is not a secret inventory. Variable values were not retrieved.

## Historical evidence versus current verification

- [Saved preflight, 18 October](../lab/reports/interview/preflight-39070289449-attempt2.json) reports Foundation key present; LLM alternate key, dedicated S3 pair, SSH private/known-host secrets and LLM vars absent in that run. Infrastructure IAM and encrypted state reads passed. Its `llm` status is `NOT_TESTED`.
- [Old model probe](../lab/reports/model-probe-39061894797.json) reports Foundation key missing in an earlier run and Workflow key HTTP 403. This is historical evidence against treating Workflow credentials as a substitute, not today's key state.
- [Later live agent report](../lab/reports/agent-ci-39066354050/agent-evidence/model-attempt-1/report.json) and its [audit](../lab/reports/agent-ci-39066354050/agent-evidence/model-attempt-1/audit.jsonl) record two real responses from `openai/gpt-oss-120b`, with usage and unmeasured cost. The real-agent workflow binds the Foundation secret. These committed records support historical model use; they do not prove current validity, Qwen entitlement, grant coverage or price.
- [18 October access report](../lab/reports/access-2026-10-18/REPORT.md) records successful pinned SSH/SFTP to the existing UI VM and cleanup of temporary runner `/32` access. This session did not repeat SSH, touch the VM or change networking.
- [Existing service review](lab-cloudru-tools-2026-10-17.md) identifies the Foundation Models base URL, service-specific authentication and public model ID `Qwen/Qwen3-Coder-Next`. That public documentation review is not an authenticated catalog check. Infrastructure IAM credentials are not reused for this API.

**Actually verified in this session:** GitHub repository/document access, static workflow references, historical reports and offline adapter safety tests. **Not verified:** live Cloud.ru access, current secret metadata, Qwen availability, generation, model parameter compatibility, current tariffs/quotas, or grant/budget coverage. No real API requests or Actions dispatches were performed.

## New workflow and adapter

`.github/workflows/cloudru-foundation-models.yml` is dispatch-only, runs solely on `refs/heads/main` after review/merge, and checks out its exact event SHA with credential persistence disabled. No `pull_request_target`, PR checkout, arbitrary command/ref input, deployment or infrastructure credentials. Checkout is pinned by commit. Offline tests receive no model secret. No artifacts are uploaded.

Only the qualification step receives `secrets.CLOUDRU_FOUNDATION_API_KEY` through its process environment. There is no fallback to IAM, Workflow or generic LLM keys. The HTTPS origin is fixed to `foundation-models.api.cloud.ru`; redirects are rejected. Each endpoint gets one attempt, no retries, a 20-second socket timeout and 256 KiB response limit. The job has a three-minute hard ceiling (socket timeout alone is not a whole-request deadline).

Dispatch modes:

1. `preflight` (default): checks only key presence, makes no network calls, explicitly reports access untested. Missing key fails closed.
2. `catalog`: one `GET /v1/models`; reports independent availability flags for exact IDs `Qwen/Qwen3-Coder-Next` and `openai/gpt-oss-120b` in `catalog.models_available`. Reports HTTP status without echoing arbitrary API fields. Listing does not prove inference or billing eligibility. A missing Qwen target, malformed response, 401/403, 429, redirect or network error blocks qualification; no automatic retries or pagination/fallback guessing. GPT availability remains visible even when Qwen is absent. This mode never generates, including when approval vars are already set.
3. `generate`: requires explicit selection **and** both repository/org vars `CLOUDRU_FM_BUDGET_APPROVED=true` and `CLOUDRU_FM_GRANT_CONFIRMED=true`. Without both, it stops before any network call. After a successful target catalog check, sends exactly one synthetic `Reply OK.` request, `stream=false`, `max_completion_tokens=16`. No source code is sent. It checks nonempty choices and exact returned model ID; token truncation may make this a connectivity check rather than a semantic quality test.

The approval vars are proposed settings, not settings created by this PR. Do not set them or select generation until an owner has independently confirmed applicable grant terms and budget. This PR does not establish a numerical monetary cap: tariff and quota data must first be obtained from the project's billing/service panel or provider. No catalog endpoint is assumed to return grant eligibility or authoritative pricing.

The JSON report and Actions summary include fixed status fields, HTTP codes and the fixed target ID only; no authorization headers, raw bodies, generated text, exception messages, secrets or arbitrary model IDs. A failed job retains a safe summary where a report exists. HTTP 401/403 is not diagnosed as a grant failure; 429 is not treated as a verified quota amount.

## Remaining gaps and next steps

1. Establish the current name/scope of the service-specific Foundation key using authorized GitHub settings metadata. Do not paste its value into chat. If the key exists only in an Environment, review the exact Environment selection and protection policy before changing this workflow.
2. Review/merge this draft, then separately authorize a `preflight`/`catalog` dispatch; no automatic execution is included here.
3. Confirm Qwen's actual catalog result, model card/token parameter support, current input/output rates, quotas and project grant coverage before enabling the generation gate. Grant terms/budget remain unknown despite historical successful inference.
4. Old `lab-model-probe.yml`, `lab-agent-ci.yml` and `lab-product-ci.yml` retain their prior real-call behavior. They were inspected, not dispatched or edited; do not use them to bypass the new budget gate.

Offline validation: `python3 -m unittest discover -s infra/cloudru/foundation_models -p 'test_*.py' -v`. Mocks test missing credentials, no fallback, both generation gates, catalog-only behavior, missing/malformed catalogs, bounded generation, output filtering, HTTP failures without retries, redirect rejection and response limits. Passing tests do not establish live API availability.

## Dispatch readiness recheck

The current GitHub connector exposes no workflow-dispatch action. Its generic GET rejects the workflow registration endpoint as unsupported; that connector rejection is not an HTTP response from Cloud.ru. A successful directory read confirms this workflow is absent from `main`; the draft branch contains it and its job explicitly permits only `refs/heads/main`. Existing branch run [39605322193](https://github.com/rengalaxies/agent/actions/runs/39605322193) is P1 regression, not Foundation Models qualification. No qualifying run or live secret/catalog result exists from this work.

Workflow page: https://github.com/rengalaxies/agent/actions/workflows/cloudru-foundation-models.yml . Once this workflow has reached the default branch through the normal reviewed process, manual actions are **Run workflow → branch main → mode preflight → Run workflow**, then **mode catalog**. The catalog run also reports secret presence. These steps are not currently executable for this unmerged workflow; selecting the draft branch would skip its job. Do not merge solely to enable dispatch, rerun unrelated inference workflows, or choose `generate` for this check. No change to secrets, VM, triggers or branch restrictions was made for this recheck.

Follow-up offline validation: 10 tests pass, including all four combinations of availability of the two requested models and absence of generation in catalog mode even with both approval vars set. Secret presence, HTTP status and current model availability remain untested until a real qualification run completes.

## Independent review of PR #30

Reviewed the complete diff and credential-bearing execution path at
`c6353fb21929b4cb20f1a2aed4ee51a0ccf4a410`, against main
`5c8daf78d34d510d48ecd9b1e194678bb13ed00c`. No blocking defect was found in
the probe or workflow. The missing regression coverage was corrected without
changing their behavior or weakening dispatch restrictions:

- The existing 10 adapter tests did not cover the CLI's actual stdout/stderr,
  report file and exit status, or redirects through the configured opener.
  There are now 13 tests, including CLI execution with synthetic credentials,
  malformed responses, credential-bearing transport exceptions, and all five
  redirect statuses through the real opener with HTTPS I/O replaced offline.
- Workflow security assumptions previously had no committed regression test,
  and the adapter suite ran only during post-merge qualification. Four tests in
  `tests/test_foundation_models_workflow.py` now cover the dispatch/main gate,
  exact event-SHA checkout, pinned action, credential scoping and absence of
  infrastructure keys or artifact actions. They also run the adapter suite.
  Adding this file activates the existing `core-tests.yml` PR path filter;
  these tests receive no model credentials and need no new workflow trigger.
- Offline mutation checks rejected a PR trigger, a mutable checkout ref,
  infrastructure credential injection and redirect following.

Validation: 13 adapter tests and 4 workflow tests PASS; actionlint 1.7.12 PASS
for `.github/workflows/cloudru-foundation-models.yml`; `git diff --check` PASS.
The full core suite on Windows/Python 3.14 ran 323 tests with 33 failures and
80 errors. A separate checkout of the unchanged main ran 319 tests with the
same 33 failures and 80 errors, with identical failing test names and no new
failures. Examples include POSIX-only `os.O_DIRECTORY`/`os.O_NOFOLLOW`, Unix
permission expectations and fixture verification failures. This comparison
does not claim a passing full suite; Linux GitHub CI remains the platform check.

Existing main workflows cannot perform this isolated check: `lab-model-probe`,
`lab-agent-ci` and `lab-product-ci` perform inference; `lab-preflight` binds
infrastructure credentials and reads infrastructure/VM state. None provides a
catalog-only input. Do not dispatch them for this task. The new workflow is
absent from main until merge, and its main-only guard intentionally prevents a
PR-branch dispatch. No alternate trigger, ref override or protection bypass was
added.

After normal reviewed merge, dispatch preflight explicitly on main:

```sh
gh workflow run cloudru-foundation-models.yml --repo rengalaxies/agent --ref main -f mode=preflight
gh run list --repo rengalaxies/agent --workflow cloudru-foundation-models.yml --branch main --event workflow_dispatch --limit 5
```

Inspect the corresponding run (replace `RUN_ID` with its numeric ID):

```sh
gh run watch RUN_ID --repo rengalaxies/agent --exit-status
gh run view RUN_ID --repo rengalaxies/agent --json headSha,conclusion,jobs
```

Verify the `qualify` job actually succeeded, its SHA includes the reviewed
change, and its report says `CONFIG_PRESENT_ACCESS_UNTESTED`. A skipped job
does not establish secret presence. Only then dispatch catalog:

```sh
gh workflow run cloudru-foundation-models.yml --repo rengalaxies/agent --ref main -f mode=catalog
```

Inspect that run the same way. `TARGET_LISTED_INFERENCE_UNTESTED` plus the two
`catalog.models_available` flags establishes the catalog result only, not
inference, grant coverage or pricing. Neither command selects `generate` or
requires changing approval vars. An Environment-only secret is unavailable to
this workflow; a missing-key result must be resolved through the normal
reviewed configuration process. This independent review performed no Actions
dispatch, live Cloud.ru request, generation, VM change or merge.
