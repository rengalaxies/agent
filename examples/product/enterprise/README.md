# Scoped queue and two execution profiles

Python3.12/Linux; from repository root after installing `.[api,distributed,test-api]`.
This is a working single-node CLI control service, not the multi-department Web UI
or corporate SSO. The existing Web UI remains bound to one SQL installation.

Keep registry, config, approved expectations and state outside candidate checkout.
Load a private32+character token from your secret manager into `CONTROL_TOKEN`.
The CLI accepts env variable names, never a literal token argument:

```
python -m change_completion.control_cli --registry /private/control.sqlite3 init
python -m change_completion.control_cli --registry /private/control.sqlite3 scope --id company --kind organization
python -m change_completion.control_cli --registry /private/control.sqlite3 scope --id products --kind division --parent company
python -m change_completion.control_cli --registry /private/control.sqlite3 scope --id finance --kind department --parent products
```

Create an identity with `identity --actor demo-worker --new-token-env WORKER_TOKEN
--expires-at UNIX_TIMESTAMP`; grant it exact finance permission `work`. Grant the
operator finance permissions `read enqueue` separately. Parent scope membership
never implies child membership; registry operator status is not worker authority.
The existing SQL profile additionally requires current runtime trust grants.

Register operator JSON with `register --scope finance --id financial-change
--config /private/binding.json`. SQL config has absolute repository, transition,
expectations, fixtures, trust, state and worker_actor. See the execution example.
For the second profile config uses `profile:contract-python-sql/1`, repository,
expectations, state, worker_actor and approved_suite_sha256. Optional operator-owned changes_path
is pinned at registration; the worker then generates a fresh candidate inside
private state and verifies it with the independent suite. Without changes_path
it verifies the supplied candidate. Pin the independent
suite from the protected approval location, never derive approval from candidate.
See [profile generation and Git/CI](../contract_change/README.md).

```
python -m change_completion.control_cli --registry /private/control.sqlite3 enqueue --binding financial-change --key request-001
python -m change_completion.control_cli --registry /private/control.sqlite3 --token-env WORKER_TOKEN work-loop --max-jobs 10 --max-seconds 60
python -m change_completion.control_cli --registry /private/control.sqlite3 history --scope finance
```

The loop polls a durable queue, processes bounded profiles sequentially and stops
at configured job/time budgets. Time budgets are checked between jobs; an active
profile has its own limits. It is not a distributed scheduler or an auto-scaling
fleet. A long-lived service manager can restart the loop under an operator's
budget; do not use unconditional restarts to defeat the cost cap.

Tokens and memberships are checked on each call and before completion. A lease
expiry or authority loss during work yields UNKNOWN; it is not automatic retry.
Explicit `retry --task ID --key NEW_KEY` is limited to recorded SQL STOP/FAIL.
Read-only result evidence is not permission for deployment or external delivery.

## Recovery

[Snapshot/restore and installation](../../../infra/product/README.md). Snapshot
covers only `.sqlite3` databases in the chosen directory, not the absolute bound
state directories. Quiesce all workers, snapshot registry and every bound state
separately, retain approved control artifacts/version and record path mapping.

Restored registry tokens are all revoked, memberships cleared and queued tasks
quarantined. An OS operator must create a fresh operator using `recover-restored
--actor NEW_ACTOR --confirmed-authority` with a fresh token in CONTROL_TOKEN.
Reissue exact memberships and review worker bindings and runtime grants. Old
identity tokens are never reactivated automatically. Review packages restore as
STALE and pending delivery is cancelled; previous acceptance is not restored as
current authorization. Restored absolute paths must be checked before starting.
