# Bitbucket configuration and source probe

Owner requested the next short additive pilot batch after the read foundation. Existing GitHub/Jira and the Cloud.ru service must continue unchanged; no paid resources or real credentials are needed for code acceptance.

The next usable boundary is an explicit `bitbucket-probe` CLI command: load installation configuration, resolve configured private repositories against pinned workspace/repository UUIDs, read default branch heads and open PR identities/versions, then print one bounded JSON report. Empty repositories are a successful metadata state. Errors produce a stable safe diagnostic and nonzero exit, with no partial report. A probe never opens state, starts a worker, loads the analyzer, mutates configuration or publishes comments. Other configured providers need no credentials for this command.

Approaches considered: immediately register a runtime connector (would also require Git fetching, PR contract/schema changes, multi-provider graph pinning and publication); silently accept configuration without runtime behavior (misleading); expose a guarded read-only probe (chosen by implementer to keep the requested batch short and independently usable). Runtime commands explicitly refuse a configured Bitbucket section until connector support exists, before opening state or reading credentials.

Configuration uses environment variable names for API-token email/token, pinned workspace UUID and a nonempty slug→{UUID, graph repository ID} mapping. Repository UUIDs/graph IDs are unique within Bitbucket, graph IDs do not collide with configured GitHub IDs. Production API origin is fixed; loopback is allowed only under the existing test opt-in. Existing configurations remain valid. PR discovery reports destination branch tip as such, never as a Git merge-base or completed analysis.

No runtime queue/provider/schema, webhooks, Git transport, Jira writes, release/pin/VM changes, real API requests or Bitbucket resources in this batch. Next gate remains runtime integration with exact Git refs and core compatibility. The branch is stacked on read foundation PR #93 until that dependency is merged.
