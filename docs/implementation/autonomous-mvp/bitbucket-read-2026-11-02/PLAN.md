# Bitbucket read foundation — short implementation plan

Goal: add a standalone read-only Bitbucket Cloud API building block, preserving all current GitHub/Jira runtime behavior.
Base: origin/main `5974c1fa277b9eed861ca4b2c95b8be879c4ea9c ` (#92).
Execution: inline, test-first; owner requested this short implementation batch after additive pilot scope approval.

## Scope and design

New `agent_service.connectors.bitbucket_read` uses existing pinned-host HttpClient and standard-library Basic API-token authentication. It reads only configured workspace/repositories, default-branch refs and PR metadata. Immutable dataclasses expose UUID identity and a semantic PR version including refs/title/description/state/draft, excluding updated timestamps. Empty repositories have no default branch and remain a normal metadata state.

Pagination is buffered/fail-closed, bounded to20 pages, pinned to the same API origin and exact listing path. Foreign-host/path/credentials/fragment/duplicate-query/cursor-cycle/malformed/partial failure cannot return a partial successful list or transmit auth to another host. DTOs are not wired into EventEnvelope/Core PR contracts yet.

No provider registration, configuration/schema/state migration, webhooks, Git clone/push, comment POST, deployment, real credential lookup or Bitbucket API requests. GitHub/Jira production modules unchanged. All new network tests use local synthetic HTTP stands. No Pipelines, VM or Free-tier resource usage.

## Task1 — standalone read API and actual HTTP regressions

Files: src/agent_service/connectors/bitbucket_read.py; tests/service/test_bitbucket_read.py; this report.
Interfaces: ApiTokenAuth(email,token); BitbucketReadClient(client,auth,workspace,workspace_uuid,repositories); repository(slug); branch(repository,branch=None); pull_request(repository,number); open_pull_requests(repository).

- [x] Run existing GitHub connection baseline.
- [x] Add behavior tests: decoded Basic credentials; empty repository; branch names with slash; stable UUID scope; PR versions change for title/body/head/base/branch/state/draft but not timestamps; full pagination; HTTP401/503; foreign/cyclic/contradictory/malformed page refusal; no mutation requests.
- [x] Watch missing-module RED, then implement minimal read module and watch GREEN.
- [x] Attempt whole Core discovery and run targeted service/box regressions; record incomplete/platform-limited results explicitly (see REPORT.md).
- [x] Ruff/diff check, review boundaries, commit code separately, return exact commit and next integration boundary. No merge/release/pin/VM.

## Review focus

Untrusted next URLs cannot move credentials off-origin; API repository identity cannot escape workspace or change pinned UUID; title/description/source/destination branch changes cannot retain stale PR version; incomplete listings never return partial success; missing mainbranch does not imply auth failure.

## Rulings

Native worktree creation rejected nested repository sourceRoot; workspace root is not a Git repo. Instead of modifying M3 or fighting the harness, use a normal independent local clone with no hardlinks at /Users/user/Documents/ChatGPT/ВКР/agent-bitbucket-read. Original M3 branch/files remain untouched. No linked worktree created.
