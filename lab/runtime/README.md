# Agent runtime boundary

Run from repository root with Python 3.12 and the lab dependencies:

```sh
python -m lab.runtime.run --intent-file lab/catalog/change.example.json --output /audit/run-unique --mode live
```

Required inference configuration: `CLOUDRU_FOUNDATION_API_KEY` (Foundation Models API key, not IAM) and `CLOUDRU_LLM_MODEL` (an actually available model ID). Endpoint is pinned to `https://foundation-models.api.cloud.ru/v1`. Missing settings produce exit 2, `BLOCKED`, an audit trail and discovery evidence. `--mode dry-run` only exercises static discovery; its result is `NOT_RUN`, never model success.

The analyst and patch executor make separate stateless LLM requests. Both receive allowed source snapshots, never evaluator files or hidden answers. The model has no shell, filesystem or deployment tool. Its only write output is a JSON replacement for `lab/sql/expand.sql`. The orchestrator copies app, SQL, contracts and catalog to a fresh candidate directory, rejects paths, symlinks, oversized/no-op patches, records source and patch hashes, then invokes the trusted evaluator. Candidate Python is never imported by the dispatcher. ChangeRequest.proposed_files can supply the exact broken migration as the repair baseline without modifying the source checkout; its hashes are recorded alongside the source and repaired artifact. A real repair run must begin from a broken candidate input; reformatting the already correct reference SQL is not evidence of repair competence.

Limits default to two serial calls, 180 seconds for model calls, and 64000 total provider-reported tokens. Missing usage prevents continuation. Optional `--max-cost-usd` requires operator-configured verified `CLOUDRU_INPUT_USD_PER_MILLION` and `CLOUDRU_OUTPUT_USD_PER_MILLION`; absent prices are `NOT_MEASURED`, not zero cost. Endpoint timeout limits each request. Provider exception bodies and secrets are omitted from audit.

`discover` parses actual literal SQL calls, SQL files, Python `queue_bind` calls, JSON broker definitions and declared owners. Dynamic references remain gaps. Repository freshness is not deployment freshness. Owners with no confirmation timestamp remain UNKNOWN freshness; rare consumers remain visible from static code without a trace. Graph completeness is not claimed. Source-level SQL references do not imply field-level proof.

`dispatch.execute` is a separate trusted operator API with no network exposure. Every step requires an expiring, unrevoked exact-scope grant bound to change/source, candidate and evaluator digests; a fresh independent verifier PASS is required. It performs only S1-S5 using the trusted service and candidate SQL. State before/after and unknown outcomes are journaled; ambiguous retries stop. Grant files rely on trusted operator filesystem permissions; signed multi-party authorization is not implemented. Ownership is never interpreted as permission. Read-only observations and confirmed owner information remain required operator checks before grant issuance.

A verifier `INCOMPLETE` result blocks deployment. A dry-run or successful static analysis does not prove live PostgreSQL/RabbitMQ compatibility or Cloud.ru deployment. An internal `inbox.json` contains grouped change/team cards, unresolved owners and explicit coverage; no external message is sent. `update_inbox` accepts an existing persistent path to supersede prior revisions; CLI run-local inbox files preserve per-run evidence rather than pretending to be a shared notification service.

Independent verification has its own fixed controller timeouts (build/start/test/cleanup), separate from model-call duration. Runtime execution is serial; no concurrent dispatcher calls are supported. `LAB_EXPAND_SQL` is cleared during dispatcher application and restored afterward so an inherited test override cannot replace the verified migration.
