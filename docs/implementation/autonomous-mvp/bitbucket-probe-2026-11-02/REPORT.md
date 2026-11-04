# Bitbucket source probe — implementation evidence

Dependency/base: read foundation PR #93, `3eba3e784a8b8deb594c3cab2c6998bdef1cb300`. This short batch adds strict configuration and read-only source qualification, not runtime PR analysis.

## Changes

- Optional Bitbucket config pins workspace UUID and slug→repository UUID/graph ID. Secret values are referenced only through environment variable names. Identity duplicates, GitHub graph-ID collisions, unsafe origins and extra fields are refused.
- `bitbucket-probe` returns a complete repository/default-ref/open-PR report through the existing GET-only reader. Private pilot scope is enforced. Errors cannot return partial readiness; destination tips are not mislabeled as merge-bases.
- CLI dispatch precedes state, analyzer and other-provider credential construction. Normal runtime explicitly refuses Bitbucket configuration before state/credentials rather than silently ignoring it. Existing installations without Bitbucket are unaffected.
- Review found malformed YAML could leak input via traceback. A real subprocess regression reproduced it RED; loader now normalizes YAML parser errors without exception chaining; safe JSON/nonzero behavior is GREEN.

## Verification

Local: macOS/Python 3.13.9; CI targets Linux/Python 3.12.

| Check | Result |
| --- | --- |
| Initial missing-feature tests | RED: 15 cases, 8 failures/3 errors from missing probe/config/CLI |
| First config/probe/reader/connection run | 43/43 PASS |
| Additional refusal/redaction cases | 46/46 PASS |
| Reviewed malformed-YAML subprocess case | RED then GREEN |
| Final probe + reader + connection + core contracts | **68/68 PASS**: 19 + 23 + 5 + 21 |
| Independent final review | P2 YAML issue resolved, no outstanding critical/important findings; reviewer reran all 19 probe cases: PASS |
| Workflow Ruff F401/F811/F841 | PASS |
| Whole local Core discovery | Not a full PASS: unrelated product verifier failures observed; see platform evidence below |
| This branch CI | Separate gate; do not infer success from dependency CI |
| Real Bitbucket/API token/runtime/VM | NOT_RUN |

Whole Core was attempted with the repository workflow discovery command. An independently isolated product test fails with `verification_stop` / `VERIFIER_WORKER_FAILED`. Running the unchanged `verification_worker.py` before supplying any input reproduces `ValueError: current limit exceeds maximum limit` at `resource.setrlimit(resource.RLIMIT_AS, ...)` on this Mac. No product/verifier code was modified. Do not reinterpret this local broad run as a green suite or as Cloud.ru installation acceptance. The exact observed failing test names and completion/interruption state are saved in evidence.

Final targeted command:

```sh
PYTHONPATH=src:. python -m unittest tests.service.test_bitbucket_probe tests.service.test_bitbucket_read tests.service.test_connection tests.graph.test_output_contracts -v
python -m ruff check src services tools stand lab/app lab/product lab/runtime --select F401,F811,F841
```

See [final targeted output](evidence/final-tests.log), [Core local status](evidence/core-local.txt) and [isolated worker startup error](evidence/worker-stderr.log). The example and operational limitations are in [README.md](README.md).

## Handoff and rollback

The separate probe configuration can be used once the real pilot UUIDs and read credentials are independently available. No token is requested in chat. Runtime queue/core/provider-schema/Git fetching and comments remain subsequent work. No resources were added in Bitbucket, no Pipelines used, and the existing Cloud.ru release/pin/service were untouched.

Discard/revert this additive branch to roll back; no deployed state or credential operation is involved. The PR must remain a draft until its own checks are evaluated, and depends on #93.
