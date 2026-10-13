# Deployment gate - P1

Approved project only: `20853297-65b7-42a8-af40-25c8d2df4e11`.

## Verified

- Read-only discovery completed; one subnet, no VMs, disks, NAT or public IP.
- UI 2 vCPU / 4 GiB with 30 GiB SSD; private core 8 vCPU / 32 GiB with 80 GiB SSD.
- Terraform plan passed with 15 planned creates and no apply.
- Development-only API and UI Docker images built; end-to-end UI proxy to actual V2 passed (GitHub Issue #5).

## Hard gates before actual paid deployment

1. Owner must approve an itemized full monthly cost estimate and runtime schedule, including compute, both SSDs, public IPv4, network egress and any NAT, backups and model spend.
2. Configure encrypted durable Terraform remote state with locking and restricted access. Never apply with ephemeral runner state.
3. Supply actual SSH public key or another verifiable supported bootstrap/access mechanism; remove plan-only placeholders.
4. Ensure private core has outbound access for bootstrap or pre-stage container artifacts using an approved private delivery path. No NAT exists in the approved project today.
5. Deploy secure HTTPS and authentication before exposing an interview UI. Current UI Docker image only serves HTTP on 8080, intended behind a protected TLS reverse proxy.
6. Verify API/data isolation and security-group restrictions on actual resources. No public PostgreSQL or internal domain service.
7. Runtime PostgreSQL, E4 three-process network and knowledge-1 graph must be separately deployed and smoke tested before making any corresponding product claim. Current development demo exposes one-process real V2 only.

## Required approval

Only request a YES after the gates above have concrete testable implementations and an exact priced scope. Apply must be a separate explicitly triggered job with protected GitHub environment approval, pinned validated plan, persistent state and no automatic destroy.
