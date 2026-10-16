# Offline verification replay

This is a deterministic replay of **synthetic, manually authored observations**, not an execution of the candidate or a migration demo. `candidate.txt` is only an identity artifact. The fixtures and expected values are public, not a hidden evaluation set. Parent transition-manifest examples remain declarations with no implemented technology adapters.

From the repository root:

```bash
PYTHONPATH=src python -m change_completion.verify_cli \
  --transition examples/product/verification/transition.json \
  --candidate examples/product/verification/candidate.txt \
  --expectations examples/product/verification/expectations.json \
  --observations examples/product/verification/observations.json \
  --trust examples/product/verification/trust.json \
  --actor fixture-worker --at 2026-10-16T14:00:00Z
```

Exit codes: 0 PASS, 1 FAIL, 2 STOP. Reports always have `scope=provided_observations_only` and `effects_authorized=false`. No candidate code or SQL is executed. Omit `--at` to use current UTC; an explicit clock is for replay only and must not become an untrusted production authorization parameter. The example deliberately expires on 2026-10-17 and needs its explicit replay clock after that date.

Reproduce failures in copies of these files:

- Change a candidate byte: STOP because observations refer to another digest.
- Change expected output, including whitespace: STOP until deployment-owned approval is updated. The CLI never auto-approves the file.
- Change the observed refund result from 80 to 100: FAIL.
- Remove/duplicate a case, change fixture reference, use error/timeout: no PASS.
- Replay at 2026-10-17T12:00:00Z: STOP without changing any observation.

The independent suite is pinned by its exact SHA-256 in a separate trusted configuration. This separation is an API boundary, not cryptographic issuer authentication: future deployment must protect the trust configuration, capture observations from a controlled executor and fetch current grants/revocations. Candidate-supplied trust.json is not trusted. Preparation/capture timestamps, input counts and fixture references remain externally supplied claims; this module cannot prove execution provenance or completeness of business expectations.

Scope: materialized tables of int, float, decimal, str, bool and NULL. Decimal cells are text on the JSON wire (e.g. `"0.10"`) and exact Decimal in the comparator. Columns and their order are checked independently from row ordering. Numeric equivalence and tolerances must be explicitly set by expected contracts. Bool is never an integer. Unknown types, execution errors, unsupported or oversized inputs cannot silently pass.

Limits per table: 200 rows, 128 columns, 1000 numeric digits, bounded decimal exponents, 16384 characters per text cell; serialized bundles up to 1 MB and 50 cases. Unordered rows use multiset matching with exact rational arithmetic and expected-only tolerances. Exceeding limits returns STOP. These limits do not replace sandbox CPU/time/memory enforcement in the future executor.

```bash
PYTHONPATH=src python -m unittest discover -s tests/product -v
```

Tests include independent owner examples and real in-memory SQLite mutations. That SQLite exists only in test-owned SQL; this module does not advertise a SQL dialect adapter. A shared defect in candidate and reference is not detectable by hashing: independent expectations and discriminating examples remain necessary, and cannot prove correctness outside the tested scope.
