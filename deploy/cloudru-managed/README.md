# Cloud.ru managed hosting fallback

This branch prepares an alternative deployment; it does not replace or recreate the existing VMs.

The root Dockerfile packages the existing development V2 API and its UI on port 8080.
It runs as UID 10001. The hosting platform must terminate HTTPS.

Required environment configuration (supply values through protected platform secrets):

- DMRP_UI_USERNAME: HTTP Basic username.
- DMRP_UI_PASSWORD_SHA256: SHA-256 hex digest of the UI password.
- DATABASE_URL: PostgreSQL DSN with credentials and network reachability.
- DMRP_REQUIRE_AUDIT=1: set in the image; must remain enabled.

Do not put passwords, DSNs, IAM credentials or generated API keys in this repository.

The adapter serves the existing UI at / and existing API routes without changing the research engine.
Both /healthz and /api/healthz check PostgreSQL readiness. Only /healthz is unauthenticated for platform probes.
Missing PostgreSQL returns 503. Release checks require persisted audit records.
Only public development scenarios are packaged; confirmatory evaluation data and oracle labels are excluded.

The CI workflow builds the real image, checks authentication, rejects oversized API requests,
checks 503 without a database, starts PostgreSQL and verifies an actual V2 release audit row.
No cloud deployment credentials are required by that verification.

Deployment prerequisites still to resolve:
1. Workflow Studio service enabled and dedicated API key with project access.
2. PostgreSQL endpoint reachable from managed runtime; the private Core VM cannot be assumed reachable.
3. Secrets injected into the application and HTTPS endpoint verified.
4. Resource price/quota check before provisioning persistent managed services.

Current IAM bearer was accepted by AI Agents read APIs but returned HTTP 403 from Workflow Studio.
This does not establish that creating an agent or managed app is permitted.
No public site is claimed until deployment and browser/API checks succeed.

## Persistent public demo audit

The managed demo can select DMRP_AUDIT_BACKEND=object_storage_volume and mount
the dedicated private, versioned bucket dmrp-demo-audit-20853297 at /audit-data.
This stores independent JSON records and verifies SHA-256 on authenticated reads.
It is a development-demo audit sink, not PostgreSQL or a transactional database.
The default backend remains PostgreSQL for the original VM/experimental setup.

No IAM access key is injected into the application. The platform mounts the bucket.
Readiness fails without the exact mounted-volume marker. Do not disable the mount
check in deployed environments. No temporary-directory fallback is provided.
Only public development scenarios are retained; no confirmatory evidence is created.
The bucket is isolated from the encrypted Terraform state bucket.

Validation must include independent S3 object retrieval and reading the same run
after a real stop/start, beyond local bind-mount tests. Keep maxInstanceCount=1.
