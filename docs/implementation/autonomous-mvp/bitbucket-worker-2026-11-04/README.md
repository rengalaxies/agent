# Bitbucket: actual local queue worker acceptance — 2026-11-04

Scope: explicit local-only adapter over pre-fetched mirrors. No VM, deployment pin,
release, Jira issue or Bitbucket PR was changed. Installation factory stays queue_only.

## Executed

Actual private Bitbucket PR1, repository UUID ce63c558-64b3-462f-9ab9-1b954c14f5d9:
API reconciliation → durable ServiceStore → standard Service worker → real CoreAnalyzer.
The fresh isolated worker database is recorded in summary.json. Earlier held queue
was not consumed or migrated. Credentials remained in the existing private file.

The request uses provider=bitbucket, schema 2.2, orders base
61ed1494ce9849d7fa7865b30447326e9c3f8e4e and head
cff5845d729cb97acb913938a1c67000c6fc662a. Reporting main remains
3a8010d70b3cc54cf08e60f68b367a71d9b38d5d. See request.json and result.json.

One event INGESTED, one job ANALYZED, one publication intent PENDING.
A new Service instance over the same database reconciled with enqueued=0 and no
worker steps. DirectorySink contained no delivered JSON. MODEL OFF.
Result: PAGE_DEFAULT_CHANGED 100→20 and POSSIBLE_TRUNCATION for reporting/client.py:8,
under authored requirement R-pilot-export-all. This is static evidence:
test_executed=false, compatibility_confirmed=false; no real service request ran.

## Implementation and checks

BitbucketLocalAnalysisConnector explicitly opts into analysis; publication_ready=false
holds all its intents, including failure intents. It validates current PR version,
repository identity and scope, rejects forks, verifies commits reachable from allowed
local heads, and computes the merge base. No checkout, Git push or remote code execution.
Missing objects require an explicit mirror refresh by the operator.
Output schema 2.2 adds Bitbucket; 2.0/2.1 GitHub inputs remain accepted, Bitbucket with
older declared minor is refused. Existing default queue-only connector stays held.

77 targeted tests PASS (worker, output contracts, Bitbucket queue, connection,
reconcile, delivery, pilot fairness); Ruff F401/F811/F841 on changed source PASS;
git diff --check PASS. Independent review found no blocking defect for the bounded
Bitbucket-only local use. Its missing-revision check was strengthened and tested.
No claim of full-suite or new CI acceptance.

## Boundaries and next iteration

This manual adapter is not installed or wired into the service factory. Mixed GitHub
and Bitbucket graph context is unqualified: existing GitHub mainline orchestration
needs a separate test/change before combining providers in one worker. No unattended
polling, webhook, live publication or restart/reboot of the VM was tested here.
The preserved GitHub/Jira pilot was not changed.

Next: publish/review this code batch, then separately qualify runtime configuration
and deployment. Public comments require a write-capable publisher and a bounded live
acceptance; the existing Bitbucket read credential cannot publish comments.

## Rollback

Stop the one-shot local runner (already exited). Keep the isolated database as
read-only evidence or remove only its worker-* directory after retaining evidence.
Use the prior code checkout to return to queue-only intake. Do not open a database
written with schema 2.2 analysis results in an older worker without compatibility
qualification. No VM rollback, token revocation, repository reset or PR modification
is needed for this iteration.
