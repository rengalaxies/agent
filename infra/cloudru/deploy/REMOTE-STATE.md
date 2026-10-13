# Protected Terraform state prerequisite

Do **not** apply the current plan-only Terraform configuration: it intentionally has no live remote state.

Before paid deployment:
1. Provision a **private** Cloud.ru Object Storage bucket dedicated to Terraform state in the approved project context. Enable versioning, encryption at rest, restrictive bucket policy and no anonymous/public access. Use isolated access keys with only the state path.
2. Configure the Terraform S3 backend with `bucket`, `key`, `region`, `endpoints.s3`, `use_lockfile=true` only after confirming the S3 implementation supports the lock-file semantics used by Terraform 1.10+. Never silently disable locking to make apply run. See https://developer.hashicorp.com/terraform/language/backend/s3.
3. Set S3 access key through runtime environment `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`; never print or commit credentials/state/plan artifacts.
4. Perform `terraform init -reconfigure` and `terraform state list` with the persistent backend, then run a refresh-enabled plan and verify no existing resources outside this project. First apply requires a protected approval.
5. Prove repeatability: a second runner must read the same remote state and produce zero extra creates after a successful deployment.

Official Cloud.ru provider docs list Object Storage resources: https://cloud.ru/docs/terraform-evolution/ug/topics/reference/resources/cloudru_evolution_obs_bucket

NOTE: Terraform's S3 backend and Cloud.ru's own API provider use different credential mechanisms. Existing `CLOUDRU_KEY_ID`/`CLOUDRU_SECRET` secrets do not, by themselves, guarantee S3 bucket access.

No state bucket or state credentials have been created. This is a blocking prerequisite, not an accomplished deployment.
