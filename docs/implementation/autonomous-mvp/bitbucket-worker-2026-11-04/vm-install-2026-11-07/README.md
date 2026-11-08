# Cloud.ru isolated Bitbucket dry-run — 2026-11-07

Actual target dm-p1-ui, pinned SSH. Published release c4053c6d4a959ff4d0e159c3cb1913fae87f25fb
installed to /opt/agent-bitbucket/releases; current symlink points to that release.
Archive/manifest verified on target; bootstrap.stage used directly for the separate
release directory and hash-locked wheel installation. Generic box plan/install
was NOT used: its renderer supports GitHub and would target the existing contour.
This is explicit-unit installation, not box Bitbucket support.

Service agent-bitbucket.service: UID 995, no login, state /var/lib/agent-bitbucket,
config /etc/agent-bitbucket, root-owned secrets.env 0600. Credentials delivered via
pinned SSH, no values in evidence. Duplicate remote staging secrets removed.
Model OFF. publication=dry_run; only DirectorySink writes. Polling 60 seconds.
Loopback 127.0.0.1:8092; no Nginx/public access change.

## Measured acceptance

See acceptance.json. Actual loaded SHA/manifest recorded by launch.py and PID matched.
Three PR jobs DONE, three intents DELIVERED to local DirectorySink (NOT Jira).
PR2 receipt contains Confluence page 360725 and its current acceptance marker.
No notices. Authenticated status/graph HTTP200; unauthenticated status HTTP401.
Restart PASS: new PID, same three receipt hashes, no additional jobs/intents.
Autostart enabled; reboot NOT_RUN. Existing agent-service PID936113 unchanged.
Production restore, code rollback, new worker backup/restore and LIVE delivery NOT_RUN.

## Private operations

Use existing pinned SSH profile .private/m3-ssh-20261101/config, alias dm-p1-ui.
`ssh -F <profile> dm-p1-ui 'sudo journalctl -u agent-bitbucket -n 100 --no-pager'`
Run the adjacent status.py through SSH stdin with `sudo python3 -`; it reads the
root-only token and calls loopback without printing the token. /graph uses the
same Bearer auth over an SSH tunnel; never place token in URL or shell arguments.

## Rollback

`sudo systemctl disable --now agent-bitbucket.service` stops only this contour.
Keep /var/lib/agent-bitbucket and /etc/agent-bitbucket for receipts and recovery.
No previous Bitbucket release exists: downgrade NOT_APPLICABLE at fresh install.
Do not restore old agent-service state into this separate installation.
Original service backup and recovery instructions: ../vm-preflight-2026-11-07/README.md.

## Next short iteration

Create and verify matching new-contour backup, then qualify controlled LIVE Jira
publication with exactly one selected pilot PR and same-comment update. Full
Confluence version invalidation/outage acceptance on target remains. Renew the
Bitbucket credential before its 11 November expiry for the 19 November demo.
