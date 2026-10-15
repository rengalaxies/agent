# Managed public development demo

Public URL: https://dmrp-demo-audit.containerapps.ru

This deployment packages the existing deterministic V2 engine, development UI,
knowledge map and synthetic three-process E4 demonstration on port 8080.
Only scenarios/development are packaged; evaluation inputs and oracle labels are excluded.
The hosting platform terminates HTTPS. Application routes require HTTP Basic authentication,
except /healthz for readiness probes.

## Public-demo persistence

Select DMRP_AUDIT_BACKEND=object_storage_volume. Cloud.ru mounts the dedicated private,
versioned bucket dmrp-demo-audit-20853297 at /audit-data using a platform S3 volume.
No IAM key is injected into the application. The Terraform state bucket is not mounted.

Each V2 request writes one independent JSON record with its decision, run ID,
scenario ID, timestamp and SHA-256 digest. The file is closed, fsynced and read back
before persisted=true is returned. Authenticated GET /api/v1/demo/audit/{run_id}
verifies the record digest. Failed persistence returns 503.

This is a development audit sink, not PostgreSQL, a transactional database,
tamper-proof storage or confirmatory E3 evidence. Bucket versioning preserves
object versions; SHA-256 detects accidental corruption, not malicious rewriting.

Required runtime environment:
- DMRP_UI_USERNAME
- DMRP_UI_PASSWORD_SHA256: SHA-256 hex digest of the UI password.
- DMRP_REQUIRE_AUDIT=1
- DMRP_AUDIT_BACKEND=object_storage_volume
- DMRP_AUDIT_DIRECTORY=/audit-data

The mounted marker .dmrp-audit-volume-v1.json must identify the approved project
20853297-65b7-42a8-af40-25c8d2df4e11, dataset development and format 1.
Readiness fails without the exact mount and marker. Never disable mount checks
in cloud deployment. There is no temporary-directory fallback.
Keep minInstanceCount=1 and maxInstanceCount=1 for this demo.

## Original PostgreSQL path

The default backend remains postgres. For the original VM/experimental setup,
provide DATABASE_URL or DMRP_DATABASE_URL_FILE and DMRP_REQUIRE_AUDIT=1.
No PostgreSQL instance is provisioned by the managed-demo deployment.
Managed Container Apps currently cannot connect to Cloud.ru Managed PostgreSQL;
do not provision a database assuming such connectivity.

## Verification

cloudru-managed-test.yml builds the real image, checks Basic authentication,
oversized request rejection, missing-storage readiness and actual PostgreSQL writes.
It also checks volume integrity, failed writes, concurrent independent records,
and persistence through complete local container removal and recreation.

cloudru-managed-deploy.yml builds the pinned verified source, pushes to the existing
Artifact Registry, preserves authentication and volumes, and verifies real V2 runs,
the knowledge API, an independent S3 read and bucket versioning. It does not suspend
the public application during routine deployment verification. Its output contains pass/fail markers, not private payloads.

cloudru-managed-browser.yml opens the real public page in Chromium, clicks the V2
button and compares the displayed decision with authenticated persisted-audit retrieval.

Deployment success requires the cloud and browser checks to pass; CI alone is insufficient.
Do not put passwords, DSNs or unencrypted IAM credentials in the repository.

## Observed cloud lifecycle limitation

The original workflow-created container returned 502 after explicit suspension and
resume even though its process started and configuration remained intact.
The recovered independent container dmrp-demo-audit reads the same pre-suspension
audit records successfully. Its resources are 0.2 vCPU and 512 MiB, with one warm instance.
The old workflow-created application was suspended after replacement acceptance.
Do not use the old Workflow Studio pipeline as the current deployment target.
The precise cause of the old endpoint failure remains unconfirmed.
