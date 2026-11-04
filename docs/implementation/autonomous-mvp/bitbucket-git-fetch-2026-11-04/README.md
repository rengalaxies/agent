# Actual Bitbucket Git acquisition — 2026-11-04

Status: VERIFIED, local one-shot acceptance. This does not enable automatic runtime fetch, core analysis, comments or Cloud.ru deployment.

The existing owner-authorized read token fetched exactly the two configured pilot repositories into new private bare repositories. The implementation reuses the existing box mirror Git environment: credentials only in a host-scoped environment header, credential helper/hooks disabled. Redirects and non-HTTPS Git protocols are refused. No checkout, submodule operation, push or Pipeline was executed. TLS verification used installed certifi; it was not disabled.

Fresh API probe before acquisition pinned workspace and repository UUIDs, default heads and PR1 head. Bare clones were checked with git fsck --strict; all required full SHA commit objects exist. A second API probe after acquisition matched the first, rejecting a source change during the operation. Neither stored Git config contains the token or Basic header.

| Source | Full Git SHA |
| --- | --- |
| Orders main / PR1 destination tip | 61ed1494ce9849d7fa7865b30447326e9c3f8e4e |
| Orders PR1 head | cff5845d729cb97acb913938a1c67000c6fc662a |
| Computed Git merge-base | 61ed1494ce9849d7fa7865b30447326e9c3f8e4e |
| Reporting main | 3a8010d70b3cc54cf08e60f68b367a71d9b38d5d |

PR1 diff: api.py only, one insertion/one deletion, default page_size100→20. This is an actual computed merge-base, unlike the API destination-tip metadata saved by queue intake.

[actual-fetch.json](actual-fetch.json) records the exact private directories, UUIDs and checks. The retained one-shot helper is /Users/user/Documents/ChatGPT/ВКР/.private/bitbucket-intake-20261102/fetch-pilot.py. It creates fresh private copies and never overwrites existing mirrors. Credentials remain outside this repository. This operational helper is not a deployed or scheduled connector; no production behavior was modified in this iteration.

Next iteration can use bb.orders.git and bb.reporting.git at these pinned commits for core compatibility and dependency analysis. The Bitbucket queue remains held; no queued job was claimed or published by acquisition. No analysis was run. Re-probe freshness before future analysis rather than assuming these refs remain current.

Rollback: remove only the newly created private git-fetch-if2j_ddx directory if these derived copies are no longer needed. No remote, queue or VM rollback is required. No rollback/deletion was performed.
