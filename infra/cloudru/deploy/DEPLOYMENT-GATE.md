# Deployment gate - P1

Approved project only: `20853297-65b7-42a8-af40-25c8d2df4e11`.

## Verified

- Read-only discovery completed; one subnet, no VMs, disks, NAT or public IP.
- UI 2 vCPU / 4 GiB with 30 GiB SSD; private core 8 vCPU / 32 GiB with 80 GiB SSD.
- Terraform plan passed with 16 planned creates (including NAT gateway) and no apply.
- Development-only API and UI Docker images built; end-to-end UI proxy to actual V2, knowledge-1 graph and three-process E4 passed (GitHub Issue #5).
- PostgreSQL audit persistence and verification after container restart passed in Docker integration (GitHub Issue #13). Cloud.ru VM PostgreSQL runtime has NOT been deployed.

## Hard gates before actual paid deployment

1. Owner must approve an itemized full monthly cost estimate and runtime schedule, including compute, both SSDs, public IPv4, network egress and any NAT, backups and model spend.
2. Configure encrypted durable Terraform remote state with locking and restricted access. Never apply with ephemeral runner state.
3. Supply actual SSH public key or another verifiable supported bootstrap/access mechanism; remove plan-only placeholders.
4. Ensure private core has outbound access for bootstrap or pre-stage container artifacts using an approved private delivery path. No NAT exists in the approved project today.
5. Deploy secure HTTPS and authentication before exposing an interview UI. Current UI Docker image only serves HTTP on 8080, intended behind a protected TLS reverse proxy.
6. Verify API/data isolation and security-group restrictions on actual resources. No public PostgreSQL or internal domain service.
7. Real Cloud.ru runtime PostgreSQL, E4 three-process network and knowledge-1 graph must be smoke tested after authorized apply. The development demo already implements local PostgreSQL audit, knowledge-1 and three-process E4; these have only passed local Docker CI, not cloud operation.

## Required approval

Only request a YES after the gates above have concrete testable implementations and an exact priced scope. Apply must be a separate explicitly triggered job with protected GitHub environment approval, pinned validated plan, persistent state and no automatic destroy.

## Current security build
Terraform now requests encrypted SSD volumes; cloud-init is base64 encoded; Caddy enforces HTTPS and bcrypt-based HTTP authentication with credentials supplied at protected apply. Bootstrap tests and schema validation pass. Confirm fresh `terraform plan` after these changes. Existing plan-only SSH and auth credentials are test placeholders and must never be used for real apply.

## Verified current blockers

GitHub Issue #6 automatically checks Issues #4, #5, #7, #8, #9, #10, #11 and #13. Technical code checks have passed; the live Cloud.ru state bucket and required protected deployment inputs remain unavailable. Do NOT substitute a local Terraform state for the missing remote backend. A passing `terraform plan -refresh=false` does not establish a tested production network, spending limit, bucket ownership or runtime SSL issuance.
