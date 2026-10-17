# Cloud.ru integration bootstrap
This is a **read-only cloud inventory**, not an apply workflow. It is intended to detect resources created earlier by Codex before provisioning duplicates.
1. In GitHub repo Actions Secrets set `CLOUDRU_KEY_ID` and `CLOUDRU_SECRET` in GitHub Secrets (not in the repo or this chat).
2. GitHub Actions -> Cloud.ru read-only inventory -> Run workflow.
3. Review Action log. If existing VM names or IDs are exposed, compare with intended UI/core topology.
4. Next: prepare Terraform apply only after reviewing exact topology and full current cost (UI+core+disk+IPv4+egress+models).
**Security:** the key previously entered in chat should be rotated. Terraform credentials via environment variables; never commit .tfstate or .tfplan. This workflow creates no cloud resources.
Docs: https://cloud.ru/docs/terraform-evolution/ug/topics/guides/vm_create_full and https://cloud.ru/docs/terraform-evolution/ug/topics/reference/data-sources/cloudru_evolution_compute_vm_collection .

## HARD PROJECT SCOPE - author confirmed 2026-10-13
Project name: Даниил Смирнов. Immutable project UUID: `20853297-65b7-42a8-af40-25c8d2df4e11`. **Never enumerate, read, modify, import, destroy or create resources in adjacent projects (including supervisor projects).** Always supply explicit project_id. Fail closed if any configured/returned project differs. The successful VM inventory returned `[]`, which only attests to the VM collection and not other project resources. Before provisioning inspect only this project's networks, IPs, disks and quotas. No automatic `terraform apply` or destroy; obtain explicit confirmation of complete priced plan first.
