# M1: model verdict and publication path — 28.10.2026

## Decision

Continue the MVP with the model **OFF**. No model qualified in program `2b-r1`.
The transport prerequisite failed for every model, so development, evaluation
and model-enabled readiness were **NOT_RUN**. There was no rerun, extra dispatch,
threshold change or new cloud resource. This is an engineering scope decision,
not evidence of customer usefulness or a general ranking of these models.

The existing [Actions run 40566128227](https://github.com/rengalaxies/agent/actions/runs/40566128227)
was approved and completed at exactly
`f4e6ab7906fe5db5fbce9700bcad6547757bb63e`, attempt 1.
Its three transport jobs and report job succeeded as executions; that does not
mean model qualification succeeded. The report gives all three `DISABLED`,
`profile: null`, `evaluation_not_run`.

Program manifest:
`8d1c1afcb2a1247d5bba64a39e03772e99c30aec2a5d7eeaa6db0cae3f299222`.
The program requires **at least two error-free full transport cycles** per model
before development (`runner.requirement_met`). A later successful finish does
not erase earlier invalid actions in the same case.

| Model | Requests | HTTP 200 | Valid actions / parsed actions | Error-free full cycles | Development |
|---|---:|---:|---:|---:|---|
| openai/gpt-oss-120b | 11 | 8 | 8 / 8 | 0 / 3 | blocked |
| Qwen/Qwen3-Coder-Next | 16 | 16 | 7 / 16 | 0 / 3 | blocked |
| Qwen/Qwen3.6-35B-A3B | 24 | 24 | 20 / 24 | 1 / 3 | blocked |

GPT OSS received HTTP 500 three times; the provider's underlying cause is not
established. Qwen Coder queried nonexistent graph relationship IDs and exhausted
invalid-action allowances. Qwen 3.6 also queried nonexistent IDs; another case
contained an invalid evidence range. One of its cases finished without such
errors; another eventual abstention followed a rejected action and therefore
does not count as an error-free full cycle. No validator was relaxed.

## Accounting and original evidence

**51 new requests**, 48 HTTP 200, 3 HTTP 500. Known usage corresponds to
**26,395201 RUB** by the frozen program's prices. Three GPT requests have unknown
usage. With their per-request worst-case charges, the ledger accounts for
**30,287335 RUB**. These are estimates/accounting charges; actual billing is
**NOT_MEASURED**. All reservations are closed; unknown usage is not replaced by
zero. The older 44-request program is separate and is not included in these 51.

The JSON ledgers and `report.json` / `report.md` here are byte-for-byte copies
of Actions artifacts, not a rescored success report. `transport-summary.json`
was calculated from those ledgers with `runner.phase_basic` and
`runner.requirement_met('development', state)` from the unchanged phase rules.

| Artifact | Actions artifact ID | SHA-256 of saved file |
|---|---:|---|
| GPT transport | 12805686650 | `0dfb9209efd4323670e4ddb483ee81b3bca24fde3e1b47f888f5229391984f6a` |
| Qwen Coder transport | 12805866138 | `3f5aca6d27af7eb80881f462ef1a7092c3ab76483c735f4005402231f0639b41` |
| Qwen 3.6 transport | 12806056467 | `55a417dcef32998b2bc7b9b24f6c8cf8052eed981543db6a1f1c7360b24701b8` |
| report.json | 12805287699 | `f576e2d1a109dcaaf6849064f249a6c0307e6bd0ebe2dba4fe791a462c44e44d` |
| report.md | 12805287699 | `5b57e8a97bf4c1ffeb3e8f2eca6f1a83e337c6b931790379883e900506a80609` |

## Publication fixes, separate from the live series

The Jira builder previously recorded model use/cost but omitted admitted model
hypotheses. PR publication used raw proposal history without the same context,
scope, freshness and supersession filters. Both now use one bounded enrichment
path: only the investigation's current, authorized, model-origin, unapproved
hypotheses are rendered, with authentic supporting source references. They stay
HIGH-uncertainty, NOT_ASSESSED hypotheses. They do not change deterministic
status, intent, affected services, relationships or findings; an abstained result
is not promoted by a model candidate.

Partial token metadata previously caused a PR/Jira `KeyError`; a transport-only
failure could display zero tokens. Token fields are now counted independently,
and a request with unknown usage keeps totals unknown. Supporting references
are validated at the output-contract boundary. Each optional model addition is
validated atomically, so exhausted claim/evidence/unknown capacity leaves the
valid deterministic result intact.

These fixes were tested with explicitly **SCRIPTED** investigations through the
real graph, service queue, local HTTP publishers and renderer. They were **not
tested on a qualified live model**; none exists. The model-OFF comment explicitly says that the model was not used and the
analysis is deterministic. Production qualification checks and model configuration
are unchanged. No VM installation, release or pin was
changed by M1.

## Verification and frozen revisions

Regression tests reproduced missing Jira hypotheses, partial-usage exceptions,
unknown usage shown as zero, wrong-context PR publication, capacity exhaustion
and missing supporting-reference admission before their fixes. The final
publication/result subset passed 26 tests (17 publication + 9 graph results).
A fresh read-only reviewer found two Important issues (capacity and supporting
references); both were fixed and re-reviewed with no remaining Important or
Critical findings. This is an internal independent agent review, not an external
human approval or a live model evaluation.

The initial full local suite ran 835 tests: 829 passed and six old graph-demo
runner tests errored because this host runs as root whereas their temporary
state belongs to root instead of app UID 10001. A non-root retry could not set
groups in this environment. These host limitations are recorded, not marked
as passed. GitHub's regular non-root runner must check the full PR suite.

The existing runner suite initially failed two assertions that old manifests
equal current code. Re-freezing `2b-r1` or `6-r3` would corrupt attribution of
their completed results. Their tests now check frozen manifest identity,
self-digest, exact program/corpus/oracle bytes and (for readiness) ledger
bindings. They also check that **current live gates reject code drift**.
Production gate code is unchanged. Therefore both commands below intentionally
return nonzero after M1; this is not a qualification success:

```sh
python -m tools.autonomous_mvp.program --program 2b-r1 --check
python -m tools.autonomous_mvp.readiness.program --program 6-r3 --check
```

The old manifests, scenarios, oracles and ledgers are untouched. There is no
current runnable model/readiness revision on the changed code. Future live work
requires a separately frozen revision and budget; do not refresh the historical
manifest or rerun an exposed held-out set to obtain a new qualification.

Next delivery step: M2 integration inventory and M3 deployment preparation with
the model OFF. Customer usefulness, independent coverage and full human effort
remain open in M4/M5.
