# Bitbucket source probe — short batch 2

Adds installation configuration and `python -m agent_service bitbucket-probe --config FILE` on top of read foundation PR #93. This is source qualification, not a running Bitbucket analysis/publication connector.

## Usage

Use a separate configuration file based on [probe.example.yaml](probe.example.yaml). Its workspace/repository identities are synthetic. For the real pilot, use `rengalaxies`, pin its independently verified workspace UUID and the actual UUIDs of `agent-pilot-orders` and `agent-pilot-reporting`. Choose graph repository IDs that do not collide with existing GitHub graph IDs. An empty repository is a successful result and has no branch/PR reads.

The process needs environment variables named by `email_env` and `token_env`; no values belong in YAML, shell command arguments, repository or chat. A future narrowly scoped REST API token needs repository and pull-request read permissions for the pilot. This batch does not create or request a token and does not call real Bitbucket.

```sh
python -m agent_service bitbucket-probe --config /path/to/separate-probe.yaml
```

Exit 0 and `status: READ_ONLY_VERIFIED` mean only that configured private repository identities, default branch refs and complete open-PR metadata were readable during this probe. `runtime_ready: false` remains explicit. Destination tips are named `destination_tip_sha`; they are not computed Git merge-bases. The report omits credentials and PR title/body. Exit 1 provides a safe reason and no partial repository report. No persistent readiness checkpoint is written.

The command dispatches before normal service construction. It does not open/create the configured state path, load the core policy/model, inspect other providers' credentials, start workers, fetch Git or publish comments. `serve`, `reconcile`, `status` and `doctor` explicitly reject a configured Bitbucket section before normal runtime state/credentials; do not add it to the running installation yet. Existing configurations without Bitbucket retain their behavior.

## Acceptance boundaries

- Synthetic HTTP verifies actual Basic auth, GET-only traffic, UUID pins, private repository scope, complete listing errors, no state creation, CLI redaction, and refusal of unsupported runtime configuration.
- Configuration rejects missing/duplicate UUIDs/graph IDs, GitHub graph-ID collisions, extra fields/inline token and nonofficial production origins. Loopback requires the existing test opt-in.
- Read foundation #93 at `3eba3e784a8b8deb594c3cab2c6998bdef1cb300`: four CI workflows PASS (Core, Linux install, exact recovery, offline pilot qualification); these are dependency checks, not this branch's acceptance.
- Real Bitbucket API/token qualification, PR→queue→core, Git fetching, webhook/publication, Jira development panel and Cloud.ru deployment: **NOT_RUN** for this batch.

Next short batch: introduce the explicit Bitbucket PR contract/runtime path and exact Git revision preparation, with multi-provider graph scope and GitHub regressions. No merge/release/deployment is performed here. This branch is stacked on #93 until that dependency merges.

## Rollback

The live service, pin, credentials and Bitbucket resources were untouched. Discard/revert this code branch and remove the separate probe configuration if created; no VM restart or state restore is required.

API fields/auth references remain those documented in [the read foundation report](../bitbucket-read-2026-11-02/REPORT.md#primary-references). Local/CI outcomes for this batch are recorded in REPORT.md and evidence files.
