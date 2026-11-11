# Persistent LIVE handover on Cloud.ru — 2026-11-07

Actual target: dm-p1-ui. Separate agent-bitbucket.service, accepted release
c4053c6d4a959ff4d0e159c3cb1913fae87f25fb, UID995, model OFF, loopback8092.
Existing agent-service and demo remain independent.

## Handover

Native LIVE state from previous scoped acceptance is retained in place:
/var/lib/agent-bitbucket/live-acceptance/service/service.sqlite and
/var/lib/agent-bitbucket/live-acceptance/core. Despite the historical directory
name, this is now the persistent worker state. Only publication and state/core
paths in /etc/agent-bitbucket/service.json changed. No SQL edits, queue reset,
comment-ID translation or release modification. Comment10011 retained.

Old dry-run queue/core and receipts remain at their original paths, inactive.
Before handover, both contours were snapshotted with the worker stopped; all96
files and four SQLite copies verified after scratch extraction. Root-only archive,
digest and exact before-config path recorded in handover.json. Production restore
NOT_RUN. No native Bitbucket box renderer/plan support is claimed.

The original PR2-only monkeypatch existed only in the completed acceptance script,
not the release. The normal systemd worker processes all eligible PRs in the two
configured pilot repositories and KAN scope, via60-second polling.

## Safe stop and rollback

`sudo systemctl stop agent-bitbucket` stops LIVE work; retain all state/receipts.
To return to dry-run behavior: stop the worker; preserve current LIVE state in a
root-only safety backup; atomically restore service.before.json from the exact
backup directory recorded in handover.json to /etc/agent-bitbucket/service.json
with owner root:agent-bitbucket mode0640, then start the worker. That switches to
the preserved dry-run queue; it does NOT undo external Jira/Confluence writes.
Never replace LIVE state with the old dry-run DB or erase native comment receipts.
Keep the LIVE queue for a future resumption to preserve same-comment identity.
Code rollback/reboot/full production restore are not qualified by this handover.

## Private access

Use pinned SSH alias dm-p1-ui and existing profile. Adjacent earlier status.py
still works: it calls loopback /status using root-only environment-file token.
Logs: sudo journalctl -u agent-bitbucket -n100 --no-pager.
No public listener/Nginx change. Do not put Bearer tokens in URLs or shell args.

## Negative control and first acceptance attempt

First readiness wait timed out because it incorrectly expected all three PRs to
reach DONE. Actual PR3 has no linked Jira key. Its analysis completed with
no_supported_delta; its publication intent FAILED exactly_one_linked_jira_required,
comment_id null. This is the expected fail-closed outcome, not Jira integration
success. PR1 published to KAN-4 (comment10012); PR2 retained KAN-8 comment10011.
Acceptance predicate was corrected to require exactly that one rejection and two
linked publications. Product/release code and the queue were not changed.

## Measured result — PASS

acceptance.json records actual permanent systemd worker operation, no manual
reconcile calls. Confluence page360725 v3→v4 updated the same KAN-8 comment10011
in51.88seconds measured from edit request through verified comment readback.
Restart PASS: new process PID, reconciliation checkpoint advanced, resources and
status counters unchanged, KAN-8 comment IDs unchanged. Both linked PR comments
read back from real Jira with expected author; unlinked PR3 explicitly rejected.
Final counters: five events INGESTED; four jobs DONE and one ANALYZED (PR3);
six intents DELIVERED and one FAILED (expected missing Jira key). No notices.
Autostart enabled; model OFF; original agent-service PID936113 unchanged.
Actual config (without secrets) is service.live.json.

LIVE is now persistent. Remaining: new authored PR demo, Confluence link removal /
API outage, reboot and production restore, independent usefulness evaluation.
Text context/version invalidation is supported; semantic requirements validation
is not claimed. Renew Bitbucket token before11November for19November demo.
