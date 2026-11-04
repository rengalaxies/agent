# Actual Bitbucket code → graph core — 2026-11-04

Status: VERIFIED local graph-core acceptance. No service AnalysisRequest provider was relabeled as GitHub. The existing service PR contract still only accepts GitHub; this iteration invokes the provider-neutral Graph engine directly. Queue work remains held, no comment was published and no Cloud.ru change occurred.

The fresh real Bitbucket API probe matched both repository UUIDs, main tips and PR1 head in the preceding Git acquisition evidence. The core read actual bare Git objects at those full commits; no worktree/fixture replacement was used. MODEL OFF.

## Observed result

- Orders api.py lines8–10: PAGE_DEFAULT_CHANGED,100→20.
- Reporting client.py line8: requests.get to Orders GET /orders without explicit page_size; SINGLE_REQUEST_OBSERVED.
- Finding: POSSIBLE_TRUNCATION for reporting, with CURRENT code dependency and source receipts.
- The authored test requirement R-pilot-export-all is pinned to the exact export-requirement.md digest. This is an explicitly configured pilot test condition, not an inferred customer requirement.
- Neutral main→main control:0 deltas/0 findings.

The finding remains conditional static evidence: test_executed=false and compatibility_confirmed=false. This run did not execute the service API or Reporting client, prove a production failure, make a release decision, or use an LLM.

## Files and handoff

[summary.json](summary.json) captures scope, pins and assertions. [analysis.json](analysis.json) is the native core result, [control.json](control.json) the neutral control, and [provenance.json](provenance.json) maps cited source IDs to Git source metadata/snapshots. [graph.html](graph.html) is the existing core renderer's mainline graph view. The unmerged PR head is analysed separately and is not installed as mainline graph memory. [policy.json](policy.json) records local mirror paths, source/operation scope and the authored requirement; it contains no credentials.

Operational helper retained privately: /Users/user/Documents/ChatGPT/ВКР/.private/bitbucket-intake-20261102/analyze-pilot.py. Derived state path is recorded in summary.json. No production behavior was changed, so verification consists of actual source freshness, Git reads and engine/control assertions rather than new implementation-mirroring unit tests.

Next: extend and validate the explicit Bitbucket core PR contract/adapter, then connect queue execution with guarded publication. Do not mark the existing queued PR analysed or delivered from this direct core result. Runtime correlation with Jira and external comments remain separate acceptance steps.

Rollback: discard only this new private core-analysis-1ozwlfbs directory and documentation branch if unwanted. Remote refs, queue rows and VM state are unaffected; no rollback was executed.
