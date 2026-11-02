# Independent review before merge

Scope: PR #89 Jira bootstrap/full pagination, restart/retry, recovery preflight,
and VM-CHECK/helper evidence. Reviewer: separate agent with a fresh context,
read-only review; this is not human approval or independent real-Jira qualification.

Final verdict: **no remaining blocking source findings in this scope**.

Findings identified independently and fixed in the revision:

1. Nonterminal pages without tokens, contradictory terminal tokens, repeated
   cursors, malformed responses and missing requested issue project data could
   be mistaken for a complete listing. These now fail before candidates return
   or completion checkpoints advance.
2. Recovery could swallow later provider/graph API failures after an initially
   successful full read. Preflight now checks the second reconciliation and
   current graph result. A repaired graph read clears its stale error notice;
   removed-provider notices do not block configured providers.
3. The VM results helper omitted DirectorySink's provider directory. It now
   uses the actual Jira path and validates sink ID/marker/generation/body digest
   against the delivered queue receipt. Fixtures use production build/store/sink.
4. Selected metadata was insufficient to prove a valid analysis result. The
   helper now uses standard result contract/request binding, including the job
   attempt, event, installation, environment and resource version.

Reviewer verification: independently reproduced malformed-page and later API
failure paths in memory, checked that recovery completion remains unset,
inspected restart/reopen transaction logic and all new regressions, parsed
changed Python syntax and checked the diff. The filesystem-writing suite was
run by the implementation agent, not independently rerun by the reviewer.

Implementation-agent evidence: final targeted suite **104 tests PASS**
(54.611 seconds), including all final helper contract tests. The regression
matrix includes four fresh-interpreter SIGKILL cases and actual local HTTP
pagination. Ruff F401/F811/F841 and diff check PASS. Final-head CI links and
SHA are recorded in PR #89 after CI completes; no earlier head is called final.

Additional target-version finding: a manager calling the older immutable
connector's seven-day method could still certify an incomplete recovery. The
revision adds manager-owned REST-v3 ID/project discovery, retaining selected
target auth/fetch/version semantics. An explicit subprocess qualification runs
against real immutable14e/234 archives locally, and published14e plus exact
candidate in recovery CI. Four failure/retry/idempotence cases per target; no
archive or PROFILE patch, and no target worker or publication.

Limits retained: 20-page fail-closed bound; no target VM, real credentials, live
Jira analysis quality or client-benefit qualification. New published release
acceptance and a pin change require separate decisions. Main/pin/published
assets and target VM were not changed.

The final expanded suite has104 targeted tests; the immutable compatibility
matrix has4 scenarios on each of real14e and234 (8 cases). The matrix was
executed locally and is required again with14e and the exact CI candidate.

Final independent source re-review also covered manager-owned legacy-target
discovery and its CI harness: no blocking findings. Exact final tree binding
and final CI results are recorded in PR #89 after publication.
