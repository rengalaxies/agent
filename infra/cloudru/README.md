# Cloud.ru integration bootstrap
This is a **read-only cloud inventory**, not an apply workflow. It is intended to detect resources created earlier by Codex before provisioning duplicates.
1. In GitHub repo Actions Secrets set `CLOUDRU_KEY_ID` and `CLOUDRU_SECRET` in GitHub Secrets (not in the repo or this chat).
2. GitHub Actions -> Cloud.ru read-only inventory -> Run workflow.
3. Review Action log. If existing VM names or IDs are exposed, compare with intended UI/core topology.
4. Next: prepare Terraform apply only after reviewing exact topology and full current cost (UI+core+disk+IPv4+egress+models).
**Security:** the key previously entered in chat should be rotated. Terraform credentials via environment variables; never commit .tfstate or .tfplan. This workflow creates no cloud resources.
Docs: https://cloud.ru/docs/terraform-evolution/ug/topics/guides/vm_create_full and https://cloud.ru/docs/terraform-evolution/ug/topics/reference/data-sources/cloudru_evolution_compute_vm_collection .
