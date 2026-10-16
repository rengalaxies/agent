# First executable transition: two independent consumers

This is a working **internal lab profile** (`sql-window/1`), not a claim of generic SQL, Python, Java or client-stack support. It runs a computed candidate against owner-authored expectations. The underlying product contracts remain technology-neutral.

Supported environment for this prototype: Linux, Python 3.12, project dependencies (`python -m pip install -e .`). The worker uses POSIX resource limits and no-follow file descriptors; native Windows execution is not supported. Docker, Kafka, a graph database and a model endpoint are not required for the deterministic example.

From the repository root:

```bash
PYTHONPATH=src python -m change_completion.run_cli run \
  --repository examples/product/execution/repository \
  --transition examples/product/execution/transition.json \
  --expectations examples/product/execution/expectations.json \
  --fixtures examples/product/execution/fixtures \
  --trust examples/product/execution/trust.json \
  --state .runtime/completion-demo --actor demo-worker
```

Expected result: `READY_FOR_REVIEW`, `effects_authorized=false`. Exit codes: 0 ready, 1 demonstrated mismatch, 2 stopped. This synthetic example is approved from 2026-10-16 until 2027-10-16; after expiry use an explicitly dated **replay** clock `--at 2026-10-16T16:00:00Z`. Production authorization must use the deployment clock, never a request-supplied historical clock.

## What actually happens

1. Read deployment-controlled transition/approval/fixtures separately from the candidate repository. Validate pinned content digests, grants and exact consumer scope.
2. Discover SQL relation references and files through bounded, no-follow descriptor reads. Runtime consumers outside the local snapshot remain unknown and are reported explicitly.
3. Read the approved target intent: analytics must use 90 days; audit must remain at 30 days. Compute one literal rewrite in an unambiguous `WHERE age_days < N` predicate. The resulting patch is not a copy of an old compatibility SQL file.
4. Keep source files unchanged. Execute the candidate SQL bytes and the unchanged audit SQL in fresh restricted workers against two real fixture sets per consumer.
5. Derive actual result types and values from SQLite, build observations and per-case hashes in the coordinator, then invoke the independent verifier. The candidate supplies SQL only, not actual outputs, expected answers or trust.
6. Recheck repository/fixtures, current grants and suite validity. Only then return a review package with source/candidate digests, actual diff, observations and verification. Failed/stopped runs do not export candidate bodies.
7. Save state and ordered history in a private SQLite database outside the candidate checkout. The same run can be retrieved after process restart.

The actual expected totals are:

| Consumer | Normal inputs | Boundary inputs | Window |
|---|---:|---:|---:|
| analytics | 160 | 31 | less than 90 days |
| audit | 100 | 7 | less than 30 days |

`expectations.json` contains separately authored expected numbers, pinned in `trust.json`. They are public synthetic fixtures, not hidden evaluation. The candidate provider does not receive them. This finite set cannot establish correctness for all possible inputs.

## Inspect history and repeat

Use the `run_id` from the result:

```bash
PYTHONPATH=src python -m change_completion.run_cli history \
  --state .runtime/completion-demo --run-id RUN_ID
```

A second identical `run` returns the same run with `reused=true` after revalidating source, fixtures, expectations, cached candidate hashes, time and authority. It creates no duplicate run/events or external PR. A changed context/provider/runtime revision receives another run. An interrupted `RUNNING` claim is deliberately not reclaimed: an operator must investigate before another attempt. This is conservative interruption handling, not automated checkpoint recovery.

State stores may contain source SQL, test values and observations. Treat the directory as sensitive, operator-owned data; do not put it into a public repository or expose the CLI/database as an unauthenticated service. SQLite append-only triggers prevent ordinary event updates/deletes, not an administrator from rewriting the installation. Preflight rejection before a run claim is not a full persisted request audit.

## Optional client model gateway

`--provider-config /operator/patch-provider.json` enables an explicit client-owned HTTP gateway. This is a small gateway contract, not a claim of direct compatibility with every model vendor. Deployment configuration must include endpoint, model, endpoint allowlist and `allow_source_transfer=true`. HTTPS is required; loopback HTTP is opt-in for local tests. Credentials may come from a named `key_env` variable and are never persisted in identity/history.

The gateway receives only `{model,source,intent:{old_window,new_window}}` and must return exactly `{candidate:"SQL"}`. It never receives test answers, fixtures or authority. Redirects are disabled, ambient proxy settings are ignored, source/response bytes and request time are bounded. There is one proposal per changed consumer, not an unlimited repair loop. Deterministic mode is the default and requires no inference. Tests use a local fake gateway to check transport boundaries; no real model endpoint or model quality has been validated.

## Isolation and scope limits

The worker runs trusted Python with `-I -S`, cleared environment, closed inherited descriptors, temporary working directory and CPU/memory/file limits. Candidate input is restricted SQLite SELECT, with a read-only authorizer and allowlisted functions over an in-memory fixture database. ATTACH, PRAGMA, write statements, extension loading and external functions are denied. SQL is never interpolated into a shell or executed as Python.

This is **not a general OS sandbox for arbitrary code**. Runtime image/dependency hardening and an installation threat assessment remain necessary for a client deployment. Limits include a 2-second worker wall timeout, 256 MiB address space, SQL instruction budget, bounded inputs/output and result rows. The overall 60-second budget is checked between bounded operations; it is not a separate supervisor that kills every parent operation at exactly 60 seconds.

Empty/all-NULL output columns, ambiguous predicates, complex unsupported dependency syntax and unsupported profiles yield STOP. Discovery is static and local. No auto-merge, GitHub PR publication, notification, production switch or legacy retirement is implemented. Human review is required; `READY_FOR_REVIEW` never means deployed or accepted.
