# Isolated PostgreSQL / RabbitMQ lab infrastructure

## Current delivery boundary

The new preflight is read-only. A successful inventory **does not** mean OS access,
VM lab deployment, LLM readiness or a working application. Check the individual
status fields in its JSON artifact. All live reads are scoped to project
`20853297-65b7-42a8-af40-25c8d2df4e11`, zone `ru.AZ-2` and the VMs already recorded
in the encrypted production state. Missing or mismatched state stops execution.
No raw state, credentials, bootstrap contents or API response bodies are emitted.

Run `Lab existing VM read-only preflight` against the exact reviewed branch commit.
The branch push trigger exists because dispatch may be unavailable through the
connector. The artifact name contains the source commit. No Terraform commands
are needed for these reads; consequently this operation does not acquire or bypass
a Terraform write lock. Any future Terraform operation must retain the existing
SSE-C backend and `use_lockfile=true`.

## Audit of existing delivery configuration (2026-10-17)

- Protected apply pins Terraform 1.10.5, provider mirror, app commit
  `29223626ae81cc51a97698bb77475b3640a660fa`, `gen-2-4` UI and `gen-2-8` core.
- Managed deploy pins `7fb471010211d12af1520d9250d447baa93a7cc0`. It is a separate
  container deployment and does not attest VM deployment.
- Existing `cloudru-plan.yml` disables backend and locking and uses `gen-8-32`.
  It is not an admissible plan for this lab and must not be reused to apply.
- Core bootstrap installs Docker and a pinned service on first boot. Terraform
  ignores later core `cloud_init_userdata` changes. No reusable command agent or
  self-hosted Actions runner is installed by that bootstrap.
- The UI resource now uses image metadata rather than the previous UI cloud-init.
  Editing cloud-init or updating main does not execute a new installation there.
- Existing core has no public IP. Its ingress permits UI security group TCP/8000;
  it does not permit SSH. UI public SSH is restricted/disabled unless an explicit
  rule exists. An SSH public key secret cannot authenticate a runner by itself.
- Recovery code stores a temporary private SSH key encrypted with SSE-C under
  `test-bucket-ds/deployment/p1/ui-recovery-key.pem`. Preflight checks readability
  and public-key correspondence with UI state metadata. This is only a candidate
  credential, not proof it is still in OS authorized_keys. Recovery removes it
  after successful bootstrap. Never run the old recovery to obtain OS access:
  its VM-replacement behavior is outside this task's authorization.
- Core bootstrap has an eight-hour auto-stop timer and a cumulative 160-hour /
  30-day budget. Retain both; service runtime may stop during a long experiment.

## Required evidence before VM installation

1. Confirm exact current VM identities and state; start the existing core only
   through an independently verified documented API and the parent's coordinated
   cloud mutation step. Starting a VM is not OS access.
2. Establish an authenticated, host-key-verified runner-to-OS path. A candidate is
   existing UI SSH credential plus restricted runner /32 ingress, then explicitly
   scoped UI-to-core SSH and a valid core credential. Both network and credential
   conditions require verification; neither is currently claimed to work.
   Do not create broad ingress or a public arbitrary command endpoint.
3. Execute `host_inventory.py` through that channel. It measures memory, load,
   disk, Docker, Compose, existing containers and volumes without inspecting env.
   Cloud VM flavor is not a measurement of free OS resources.
4. Review exact source SHA and compose configuration; use independent lab project,
   directories and volumes, no existing `dmrp-*` container replacements. Resolve
   all images to immutable digests before remote delivery. Preserve the resolved
   image IDs and source SHA with the run evidence.
5. Deliver and run only the reviewed lab artifact. Do not install an arbitrary
   root shell interface. PostgreSQL, RabbitMQ and administrative tools stay off
   public ports. Any UI must require authentication before a public route opens.
6. Run baseline, transition, independent checks and restart persistence tests on
   the VM. CI runner tests alone are not Cloud.ru acceptance.

There is deliberately no speculative VM deployment workflow until step 2 is
proved. A workflow containing unverified remote-exec APIs or cloud-init replay
would hide the actual blocker.

## Safe stop/recovery boundary

Use only the lab compose project to stop application services. Do not use
`docker system prune`, remove existing containers, `compose down --volumes`, or
modify existing experiment volumes. Restart the same project with identical
source/image digests and retained lab volumes; validate consumer records and
outbox before resuming a partially completed transition. VM power operations
must be separate from application stop; leave existing UI and managed demo alone.

## Refreshed channel probe

The corrected live preflight run `39039843414` observed UI TCP/22 reachable,
TCP/443 unreachable, core stopped, and readable recovery key matching UI state
metadata. Later runs (including rerun job 117481021499) again timed out on TCP22, so reachability is intermittent. This does not establish SSH
trust, authentication, OS access or lab readiness.

The next preflight version performs an unauthenticated SSH handshake only after
matching the API UI interface to the approved state NIC and public IP allocation.
It publishes a public host-key SHA256 fingerprint without the hostname/address.
`BLOCKED_HOST_TRUST_UNVERIFIED` means no authentication or OS command was attempted.
The observed fingerprint must be checked through a trusted independent channel;
it is not automatically added to known_hosts. Only an existing configured
`CLOUDRU_LAB_SSH_KNOWN_HOSTS` enables RejectPolicy authentication and the fixed
read-only inventory script. Missing trust is not bypassed with AutoAddPolicy.
