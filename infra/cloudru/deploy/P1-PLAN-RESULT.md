# Confirmed Cloud.ru plan - 2026-10-13
**Verified result** from GitHub Issue https://github.com/rengalaxies/agent/issues/4, run `38431734472`.

- Project hard scope: `20853297-65b7-42a8-af40-25c8d2df4e11` ("Даниил Смирнов").
- Terraform plan: **PASS**, **15 resources to create**, no other actions recorded.
- Kinds: VMs, boot disks, interfaces, security groups, security-group rules, one external IP.
- Source: official Cloud.ru Terraform provider; UI flavor `gen-2-4`, private core flavor `gen-8-32`; Ubuntu 24.04 image `fe51a6e6-a5ad-410e-b441-1a195208a8cf`.
- Existing subnet exact UUID: `d58e80ef-fff1-43eb-b601-96fb358224b7`, CIDR 10.0.0.0/24.
- P1 plan used nonfunctional placeholder SSH key and admin CIDR; these MUST be changed before an approved apply.
- **No resources created** yet. A successful plan is not proof of viable runtime/networking.
- State must be durable and securely stored before apply; GitHub ephemeral runner-only state is unacceptable.
- Before paid apply: verify Cloud.ru actual per-SKU price and egress/SNAT, choose budget ceiling, ensure user approval of complete cost, prepare cloud-init and deploy backend/UI.
- Do not modify or enumerate adjacent projects. Preserve independent research evaluation oracle, no trial E3 contamination.

## 2026-10-13 storage optimization
Owner agreed to reduce core boot SSD from 200 GiB to 80 GiB while retaining UI boot SSD 30 GiB. Total planned SSD becomes 110 GiB. The original 15-resource PASS plan predates this size change and MUST be rerun before approval. This is a capacity hypothesis, not an observed PostgreSQL requirement. No HDD provisioned by default; archive storage added separately only if needed. Disk tariff estimate is indicative, verify Cloud.ru final invoicing and all cost categories.
