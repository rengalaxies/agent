# Reliability acceptance on actual Cloud.ru target — 2026-11-08

Target dm-p1-ui, permanent agent-bitbucket.service, published code
c4053c6d4a959ff4d0e159c3cb1913fae87f25fb. Model OFF, publication LIVE,
UID995, loopback8092. These are actual host actions, not CI installations.

| Check | Actual outcome | Evidence |
| --- | --- | --- |
| Explicit Confluence link removal | PASS: context removed, old page text absent | links.json |
| Inaccessible Confluence page | PASS: real missing page response becomes UNAVAILABLE, no old text | links.json |
| Restore original Jira description/link | PASS: current page text returned, same comment10046 | links.json |
| API transport fault | PASS: reconcile_failed visible, liveness200, no new Jira body, recovery clears notice | outage.json |
| Active queue/core restore | PASS: actual directories replaced from matching fresh backup, resources/generations/native receipts/counters unchanged | production-restore.json |
| Reboot | PASS: boot ID changed, both units and demo returned automatically, loaded SHA/queue intact | reboot-before/after/verification.json |
| Yearly credential rotation | PASS: both services use new credentials; old three revoked; API/Git rechecked | TOKENS.md, tokens-*.json |

## What was actually done

KAN-9 description was temporarily changed only for the link checks, then restored
exactly. Worker performed ordinary polling; no manual reconcile. Comment10046
advanced generation2→3→4→5, with exactly one matching service marker in Jira.
Removal71.35s, missing-page31.83s, restore57.03s; these are observation intervals,
not performance benchmarks. Confluence text is attributed context, not semantic
requirements verification.

Transport fault used a temporary systemd runtime drop-in pointing only the
agent-bitbucket process to an unreachable loopback proxy. It simulates outbound
transport failure, NOT an actual Atlassian/Bitbucket outage. TLS validation,
firewall/public listeners and other services were not weakened. Runtime drop-in
removed in finally, ordinary network restored. Original service PID unaffected
by this fault test. HTTP health200 is liveness, not source readiness.

Production restore stopped only agent-bitbucket, created and verified a fresh
matching state copy, moved the current active LIVE directory to a safety path,
replaced it from backup, preserved current config/secrets and resumed reconciliation.
Only active queue+graph state restore is qualified; this is not whole-VM disk
recovery or a code downgrade. Both backup and safety paths are in the report.
No SQL edits or fabricated receipts. Native IDs and generations compare exactly.

Reboot was requested via systemctl on the actual VM after fresh old-service state
backup and current host-config archive. SSH socket, systemd units and Docker
restart policies were checked beforehand. HTTP baseline/post:80=200,8080=200,
18081=401 (protected endpoint),8091=200,8092=200. The elapsed observation field
in reboot-verification.json starts when the SSH polling helper began; it is NOT
measured total reboot downtime. Container health was initially starting; final
health is recorded separately. Both source credentials were checked after boot.

## Credentials and recovery

See TOKENS.md. Active Bitbucket and Jira/Confluence tokens expire2027-11-08.
Secret values stay in .private files on Mac and root0600 environment files on VM.
Historical backups containing revoked credentials cannot be used as auth rollback;
preserve/reapply current secrets before starting recovered services.

Current worker state remains /var/lib/agent-bitbucket/live-acceptance despite its
historical test directory name. To stop publication: sudo systemctl stop
agent-bitbucket. Preserve queue/core and native receipts. Stop before any state
replacement, retain a safety copy, verify matching code/config/backup, restore
ownershipUID995, then verify reconciliation and external comment identity.
Do not merge/rewind the main demo repos as part of state recovery.

## Limits and remaining work

PR3 with no Jira key still has one expected FAILED publication intent; it must
not be reported as successful integration. Old GitHub403 readiness is separate
and was not fixed by token rotation. No model or compatibility tests were run.

Not covered: actual provider-wide outage;429/rate limits; interrupted/ambiguous
external writes; restore after new external changes; disk-full; code rollback;
independent participant usefulness/false-positive evaluation. Demo rehearsal and
presentation remain necessary. This package closes the selected reliability
checks, not every possible MVP risk.
