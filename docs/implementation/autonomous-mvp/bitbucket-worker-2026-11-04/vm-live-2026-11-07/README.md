# Scoped Cloud.ru LIVE acceptance — 2026-11-07

## Backup

backup.json records a stopped-worker snapshot of /etc/agent-bitbucket,
/var/lib/agent-bitbucket and the dedicated systemd unit. Archive is root-only
on target. All 90 files compared after scratch extraction; both SQLite integrity
checks PASS. This is scratch restore, not production replacement. The original
agent-service was not stopped. backup_check.py records the actual procedure.

## Scope and publication state

LIVE acceptance uses the accepted c4053c6 release on dm-p1-ui as UID995, model OFF.
Only PR2 is passed from real Bitbucket polling candidates into reconciliation.
Separate state is /var/lib/agent-bitbucket/live-acceptance; its own graph and queue
are kept. Dedicated Git mirrors are shared while persistent dry_run worker is
stopped; it is restarted in finally. No duplicate concurrent reconciler runs.
The installed /etc/agent-bitbucket/service.json remains publication=dry_run.
This is an operator-started scoped acceptance, NOT autonomous persistent LIVE.

Reason: dry_run stores local DirectorySink comment IDs, incompatible with native
Jira backend IDs. Blind mode switching would reuse invalid IDs. A supported
handover/migration must be qualified before persistent mode is changed. No SQL
manipulation, release patching, or silent queue reset was used.

## Recovery

Stop the separate worker before any restore. Keep current state in a root-only
safety backup, verify archive digest from backup.json, extract into a private
staging directory and compare release SHA/schema/config before replacing paths.
The snapshot includes secrets; never copy it to a public evidence location.
The tested procedure only extracted into scratch and removed those copies.
Do not blindly extract over running services. No production restore was run.
External Jira comments survive state restore: retain LIVE acceptance state and
receipts to avoid duplicate publication. Undoing the local worker does not undo
external Jira/Confluence writes.

LIVE script contains a single-use Confluence marker and refuses blind replay
after that change. Inspect report.json and external comment before resuming a
partial run. Do not delete its queue to replay acceptance.

## Result — PASS on actual target

live.json: PR2 → KAN-8 comment **10011**, created 21:16:59 and updated 21:17:38
Moscow time. Confluence page360725 version2→3, Git head unchanged at16003689.
Generation1→2, same Jira comment, exactly one new external comment in total.
Repeated reconciliation enqueued0, no steps; both jobs DONE, no notices.
The page text marker CF-VM-LIVE-20261107 is present in the fetched Jira comment.
The graph model remains OFF. Text inclusion/version invalidation is verified;
semantic comparison of Confluence requirements against code is NOT implemented.

Links:
- https://rengalaxies.atlassian.net/browse/KAN-8?focusedCommentId=10011
- https://bitbucket.org/rengalaxies/agent-pilot-orders/pull-requests/2
- https://rengalaxies.atlassian.net/wiki/spaces/OOP/pages/360725

## Next boundary

Qualify a persistent LIVE handover with one retained queue/marker/comment identity;
do not simply flip the existing dry_run queue. Then test a newly authored PR,
Confluence link removal/API outage, and restart while LIVE. Reboot and production
restore remain NOT_RUN. Bitbucket token renewal before11November is required for
the19November demonstration. The scoped script must not be presented as an
already autonomous persistent LIVE installation.
