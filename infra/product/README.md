# Product installation and operator handover

This is a single-node installation candidate, not a certified enterprise release.
The corporate control registry and two execution profiles are Python CLIs; the UI
still displays one SQL transition installation. They are not a distributed control
plane or a native GitLab service.

## Build and start

Python 3.12/Linux. `requirements.lock` records exact versions from the tested
interpreter; it is not a vulnerability assessment or a hash-verified supply chain.
The Python base tag is not digest-pinned: pin your approved image digest before
release. Build requires package-index access:

```
docker build -f infra/product/Dockerfile -t change-completion:operator-build .
```

Set absolute `PRODUCT_REPOSITORY`, `PRODUCT_CONTROL`, `PRODUCT_STATE`,
`PRODUCT_SECRETS` (a private env file) and `PRODUCT_WORKER_ACTOR`; see
`examples/product/execution/WEB.md` for identities/control files. Pre-create the
state directory owned by uid10001, mode0700; secrets0600. Candidate source and
operator controls must be separate. Then:

```
docker compose -f infra/product/compose.yaml up -d
```

Compose uses Linux host networking: the existing server binds127.0.0.1:8081.
Use a host TLS/auth reverse proxy or SSH tunnel. Do not expose all interfaces by
accident. This is not Docker Desktop portability qualification. The read-only
root, dropped capabilities and tmpfs do not make arbitrary Python safe. The
supported profiles execute restricted SQL and a canonical mapping template.

For an offline build, on an approved connected builder for the same Linux/Python
architecture build the project wheel and download its dependencies into a
`wheelhouse` directory using the lock constraints. Verify licenses, hashes and
scan the dependencies; transfer the wheelhouse and approved Python base image.
Build `infra/product/Dockerfile.offline` with that directory as build context.
Runtime uses no package index. Offline install is not proved by the Dockerfile's
presence; perform the clean-install check in the client's actual environment.
LLM inference and Git hosting are separate explicitly configured dependencies.

## Restart, retry and reconciliation

SQL CLI `run` accepts `--retry-of FAILED_RUN --retry-key UNIQUE_OPERATOR_KEY`.
Same key reuses the same attempt; old STOP/FAIL remains immutable. A new key is
an explicit new attempt. READY_FOR_REVIEW cannot be retried as failure. Stop a
stuck worker and investigate before using `run_cli reconcile --state ...
--run-id ... --actor ... --reason ... --worker-stopped`. Older attempts without
recorded context require separate manual handling. Never delete history for retry.

An outbox SENDING/UNKNOWN requires external receipt reconciliation; retrying a
calculation is not permission to resend an external effect. Corporate queue
leases fence local completion and expire to UNKNOWN, not automatic re-execution.

## Snapshot and restore

Stop server/queue workers and confirm no in-flight work. Then:

```
python -m change_completion.state_transfer snapshot /private/state /private/backup --quiesced
python -m change_completion.state_transfer restore /private/backup /private/restored-state
```

Snapshot locks all `.sqlite3` files in the state directory, refuses in-flight
RUNNING/SENDING, uses SQLite backup (including committed WAL data), records file
hashes and verifies integrity. Restore refuses overwrites, symlinks, traversal and
changed bytes. Restored permissions are private. This is not encryption or a
remote tamper-proof backup: use approved encrypted storage and access controls.

Operator control artifacts, independent fixtures, identity secrets, LLM routes
and software version must be backed up separately under their own security
policy. Restore these first, update absolute registered bindings if needed, then
revalidate authority and evidence. Restore never grants new rights. Registry identities restore revoked, memberships
are cleared, queued tasks become UNKNOWN and a fresh OS-operator recovery is
required. Review approvals become STALE; pending deliveries are cancelled. Backup of
another directory containing control registry must also be taken while quiesced;
there is no cross-host transaction. Test backup/restore before accepting release.

## Acceptance checklist

Another operator installs cleanly; unauthorized actor denied; secret rotation/
revocation tested; both profiles' positive/negative cases run; interrupted run is
reconciled; two DB and registry snapshots restore; UNKNOWN delivery is not resent;
logs and retention are reviewed. Customer technology/version matrix and support
terms remain installation-specific. New registry token revocation is immediate;
old web bearer identity mapping still requires restart. No SSO is claimed.

## Comparison

`python -m change_completion.lab_benchmark --example examples/product/contract_change`
runs unchanged/correctly scoped/blanket variants with one independent suite. It
measures engineering behavior and wall time only. It is not comparison with a
strong agent and not evidence of saved customer hours.

Before commercial comparison freeze6-10 customer tasks and the same accessible
artifacts, tools, expectations and budgets for each alternative. Use separate
operators or counterbalanced tasks to avoid learning; record installation,
questions, review, STOP, cleanup, provider work and compute separately. An
independent acceptor assesses hidden cases. Target30% fewer customer hours is a
hypothesis gate; defects, total hours and uncertainty also decide continuation.
No customer artifacts, budgetholder or independent external acceptance were
available in this implementation session.
