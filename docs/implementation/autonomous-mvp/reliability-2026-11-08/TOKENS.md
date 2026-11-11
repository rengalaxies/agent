# Credential rotation — 2026-11-08

Owner completed issuance; agent prepared forms and saved values privately,0600.
New Bitbucket token agent-pilot-bitbucket-read-20261108: expires2027-11-08,
read:repository:bitbucket + read:pullrequest:bitbucket only.
New Jira/Confluence token agent-pilot-jira-confluence-20261108: expires2027-11-08,
same classic token type as previous credential; no additional account permissions.

Replaced on dm-p1-ui:
- /etc/agent-service/secrets.env: Jira email/token.
- /etc/agent-bitbucket/secrets.env: Bitbucket and Jira email/token.
Both root0600; both processes restarted and credentials in /proc matched files
without printing values. Jira identity + Confluence read from both service configs
PASS; Bitbucket API and HTTPS Git ls-remote underUID995 PASS. Health both ports200.
This does not assert the old GitHub contour's full scenario readiness.

Updated active local files: .private/m3-ssh-20261101/jira.env,
jira.candidate.env; .private/bitbucket-intake-20261102/credentials.json;
.private/releases/c4053c6/deploy/secrets.env. Private previous copies retained;
historical archives are not active configuration and were not rewritten.

Following specific owner approval, revoked old agent-pilot-bitbucket (unused),
agent-pilot-bitbucket-read-20261104, agent-pilot-jira. UI list now contains only
the two new tokens, both expiring2027-11-08. No token values are in this report.
GitHub App PEM has no observed expiring static token to rotate; issued installation
access tokens are managed automatically. No unrelated credentials were changed.

IMPORTANT: historical host backups contain REVOKED old tokens. A restore must
preserve current secrets.env or reapply the new private credentials before start.
Do not use revoked credential backups as an authentication rollback. Fresh
reliability backup after this rotation contains the current values.
