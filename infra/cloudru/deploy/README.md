# Cloud.ru deployment - DRAFT ONLY, do not apply
Project scope **ONLY** `20853297-65b7-42a8-af40-25c8d2df4e11` ("Даниил Смирнов"), one zone `ru.AZ-2`, existing subnet ID `d58e80cf-fff1-43cb-b601-96fb35822ab7`.
Staged resources: private UI/core interfaces, 2 VM, 2 boot disks, 2 security groups, restrictive rules and one dedicated UI public IPv4. First iteration UI is mandatory.
**Current state:** provider schema validation not yet confirmed; cloud deployment has NOT happened. The code is a proposed IaC draft, not approved for apply.

## Blockers before a real plan
1. Auto-validation must pass: `docs/launch-2026-10/cloudru-deployment-validation.json`. The file may not exist if workflow failed before publishing; inspect Actions then.
2. Discover real VM flavors and image (and check matching `ru.AZ-2` zone and min_disk); obtain results in `cloudru-candidates-latest.json`.
3. Verify networking: existing subnet ownership within project, security group association, public IPv4 allocation and egress for UI/backend. Avoid nonfunctional launch caused by missing NAT or DNS.
4. Provide SSH *public* key and restricted admin CIDR via protected GitHub variables or environment; NEVER private key in repository. Bootstrap templates now exist in [../bootstrap](../bootstrap/); their presence and static validation do not prove that any VM was provisioned or that services are healthy. Verify the rendered configuration and current runtime before deployment.
5. Choose secure persistent Terraform state (encrypted remote backend, locking and limited permissions). **Never use an ephemeral GitHub Actions runner as the only location of state and never run apply without state persistence.** Without state, reruns may duplicate paid resources.
6. Confirm exact monthly price (UI compute 720h, core requested hours, disk 230GiB 720h, one IPv4, egress/NAT, backups and LLM), then obtain owner's explicit approval.

## Next actions
- Read-only provider introspection and `terraform validate` (no billing)
- Build non-applying plan after correct image/flavors/ssh values are confirmed
- Separate signed-off, manually gated Apply workflow with project hard-check, state lock and no destroy
- Provision, smoke-test OS, install private services, deploy working UI and TLS, show synthetic three-verdict demonstration
- Keep H1 experiments isolated from public-demo traffic.

## Current unsafe shortcuts forbidden
No blind auto-apply on push; no public PostgreSQL/Kafka ports; no committing secrets, private keys, state, raw cloud inventory or personal data; no naming `terraform validate` a successful infrastructure provisioning.
