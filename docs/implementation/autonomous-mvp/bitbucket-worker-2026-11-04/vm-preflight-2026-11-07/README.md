# VM preflight — 2026-11-07

Performed on actual dm-p1-ui over pinned SSH, approximately 17:28–17:30 UTC.
No release installed or activated, no credentials transferred in this iteration.

## Fresh observations

- Host dm-p1-ui, uptime 9 days 21 hours; memory available 3217 MiB; disk free 22 GiB.
- agent-service active, enabled, non-root User=agent-service, PID 936113.
- Active release 5fb6484fecff116d005137f0acaaa81d2d25854c (backup writer identity).
- Nginx active; nginx -t PASS. Public listeners 22/80; no 443 listener observed.
- Existing loopback listeners 8080, 8091, 18081; candidate port 8092 free.
- State/config/release usage 112M/40K/113M. Existing demo ports unchanged.

## Backup verification

See backup.json and verification.json. Native online backup completed, six file
hashes verified. Both SQLite files copied into a separate temporary directory,
PRAGMA integrity_check returned ok. Temporary copies removed afterwards.
This is scratch-copy verification, NOT a production restore or full restore drill.
Host configuration (including secrets) retained on VM only, root-owned archive
mode 0600; only its digest and member count are recorded here. Archive includes
/etc/agent-service, /etc/nginx, current service unit and box journal.

Backup: /var/backups/agent-service/20261107T172857033694Z-pre-bitbucket-c405

## Recovery and next boundary

Existing service remains active. Nothing needs rollback from this iteration.
For a later restore of the original service, use its matching installed box manager:
`sudo agent-service-box restore 20261107T172857033694Z-pre-bitbucket-c405`.
That is a state-changing production recovery command, NOT executed here. Confirm
matching release and arrange interruption before invoking it. Preserve the host
configuration archive privately; inspect paths before selective recovery rather
than extracting it over a live system indiscriminately.

Next: stage accepted c4053c6 archive into the separate agent-bitbucket contour,
validate config, permissions and dry_run before enabling any new worker. Existing
agent-service and demo stay in place. No public network changes required.
