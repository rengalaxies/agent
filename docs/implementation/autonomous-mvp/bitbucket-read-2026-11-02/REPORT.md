# Bitbucket read foundation — 2026-11-02

Status: standalone implementation verified with synthetic HTTP. Runtime integration and real Bitbucket acceptance remain NOT_RUN.

## Delivered

The new `agent_service.connectors.bitbucket_read` module reads repository metadata, default or named branch heads, individual PRs and complete open-PR listings using REST Basic email/API-token authentication. No token lookup is performed. All requests are GET.

Configured workspace UUID and repository names bound discovery. Subsequent requests use the resolved repository UUID; unresolved or substituted DTOs are refused, and reusing an old slug with a different UUID requires explicit caller reconfiguration. PR identity includes provider/workspace UUID/repository UUID/number. Semantic versions include title, description, source repository, branch names, head/base SHA, state and draft; timestamps and comment counts cannot create a new version by themselves.

Pagination buffers results until completion, follows provider query cursors, and refuses off-origin/path links, userinfo, fragments, duplicate query keys, invalid encoding, cycles, conflicting duplicates, malformed records and partial HTTP failures. A terminal twentieth page is accepted; a required twenty-first page is an explicit incomplete result. Empty repositories with absent/null mainbranch are valid metadata.

Existing GitHub/Jira runtime, provider schema, configuration, queues, publisher and deployment code are unchanged. No real Bitbucket credentials/API, repositories, Pipelines, paid resources, VM or deployment pin were touched in this batch.

## Verification

Local environment: macOS, Python 3.13.9. CI targets Linux/Python 3.12 and remains a separate gate.

| Check | Actual result |
| --- | --- |
| Test-first initial implementation | 18 expected failures before module; then 18 PASS |
| UUID/empty-repository regression | RED, then 20 PASS |
| Review hardening | RED (23 cases, 1 failure/2 errors), then 23 PASS |
| Final Bitbucket + existing connection suite | **28/28 PASS** (23 new + 5 existing), real local HTTP server |
| Independent review | No critical/important findings; reviewer independently reran final 23 tests: PASS |
| Ruff F401/F811/F841 over workflow source directories | PASS |
| Whole Core discovery | **INCOMPLETE**: interrupted after about seven minutes while executing autonomous model protocol/GitReader regression; no full-suite success claimed |
| Existing box tests | 73 executed: 70 passed, 3 errors on this local platform; **not PASS** |
| Real Bitbucket / PR / Jira panel / agent publication | **NOT_RUN** |

Box errors are outside changed code: staging requires missing Python 3.12, and two Linux guard lifecycle tests see no SQLite ticks table because `run_preflight` explicitly rejects non-Linux (`guarded_recovery_requires_linux`). Box sources were not modified. Linux CI must establish its own result; this local run is not deployment acceptance.

See [HTTP evidence](evidence/http-tests.log), [box errors](evidence/box-platform-errors.log), and [Core interruption](evidence/core-interrupted.txt). A mistyped connection test module name initially produced an import error; the corrected final command below passed.

```sh
PYTHONPATH=src:. python -m unittest tests.service.test_bitbucket_read tests.service.test_connection -v
python -m ruff check src services tools stand lab/app lab/product lab/runtime --select F401,F811,F841
```

## Limits and next bounded step

This reader is not registered with `EventEnvelope`, reconciliation, analysis or publication. It must not be described as a working agent Bitbucket connector. Destination `base_sha` is the API destination branch tip, not a computed Git merge-base. Deleted fork source repositories are refused. Slug validation currently accepts the pilot naming subset, not every possible Bitbucket slug. UUID pagination paths need qualification against real Bitbucket; unexpected provider canonicalization fails closed.

The next batch should add explicit Bitbucket configuration/identity wiring and test its interaction with existing GitHub resource IDs, reconciliation and core PR contracts. Git credential delivery, fetching pinned refs and computing the actual analysis base need separate coverage. Only after these gates should a narrowly scoped read token and a real pilot PR be used for acceptance. No VM access is needed for that code batch.

## Rollback

No deployed state changed. Discard or revert this additive branch before integration; the current Cloud.ru service remains on its existing immutable release. No service restart, state restore or credential revocation is needed for this code-only batch.

## Primary references

- [Bitbucket REST introduction: pagination and UUID references](https://developer.atlassian.com/cloud/bitbucket/rest/intro/)
- [Bitbucket pull requests REST API](https://developer.atlassian.com/cloud/bitbucket/rest/api-group-pullrequests/)
- [Bitbucket API-token authentication](https://support.atlassian.com/bitbucket-cloud/docs/using-api-tokens/)
