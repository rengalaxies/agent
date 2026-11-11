# VM candidate — applied as isolated dry_run on 2026-11-07

Fresh target resource check: 3227MiB available memory, 22GiB free disk,
loopback8092 unbound, original agent-service active, Python3.12.3.

Separate account agent-bitbucket; config /etc/agent-bitbucket; state and
pre-created bare mirrors /var/lib/agent-bitbucket; dedicated release symlink
/opt/agent-bitbucket/current. service starts dry_run, model OFF, 60s polling.
Set secrets via root-owned environment file, never in repository. Required
names are the env references in service.dryrun.json plus
AGENT_SERVICE_STATUS_TOKEN. No values are included.

Before install: accept exact release, verify downloaded archive/manifest,
backup original pilot, validate policy/config under service account and
initialize dedicated bare mirrors. Ensure release venv can import agent_service.
Keep the service stopped until these checks pass. Then dry-run acceptance,
restart and backup; controlled live switch is a separate step.
The box renderer has no Bitbucket path, so this explicit unit needs target
qualification. Do not claim existing box acceptance covers this unit.

Stop agent-bitbucket.service to stop this contour. Preserve state/receipts.
Restore its matching config/state/release from backup for rollback.

Actual installation and remaining checks: ../vm-install-2026-11-07/README.md.
