# P1 deployment status: blocked by public IP quota

Owner approved the initial iteration at up to 8000 RUB per 30 days: UI 2 vCPU/4 GiB, core 8 vCPU/32 GiB limited to 160 hours. Project: 20853297-65b7-42a8-af40-25c8d2df4e11, ru.AZ-2. No LLM, RAG or external agent inference is enabled.

Actual protected apply run 38466919178 restored the encrypted remote state and planned 3 creates, 0 changes and 0 deletes. Previously created disks, NAT, security groups, rules and interfaces were preserved. The two interfaces were untainted after fixing the optional empty VM attachment that caused a provider inconsistency.

The remaining public UI IP allocation failed with `Organization quota for network.ip.quantity exceeded`. The UI and core VMs were not created. Do not claim the site is deployed or functional tests passed.

Created boot disks: core c5ef8c65-ad6c-45f4-bdaa-71a132a3dafe; UI 9af43326-a6e1-45f1-8235-b82937a1f664. Created NAT: baaebb13-2c79-4e7b-8bc1-73fc1c1d9110. These resources accrue charges while quota resolution is pending. Do not delete or recreate them merely to retry deployment.

Next action: Cloud.ru support must add one available public IP to the organization quota. Do not enumerate or change other projects. Once confirmed, dispatch the protected apply on main with the same project, 8000 RUB approval and existing remote state. Plan must contain no deletions. Verify HTTPS, admin authentication, live V2 audit, knowledge-1 and three-process E4 with the opt-in deployed UI smoke test.

Already verified against real Cloud.ru S3: SSE-C state and lock encryption, concurrent lock rejection, fresh-directory state recovery and no-op probe plan (run 38458566308). The probe versions were removed; production state is retained. Secrets are stored in GitHub. Public SSH is disabled. Admin website login is admin; the owner retains the password in the downloaded private access bundle.

The core bootstrap includes an eight-hour session stop and a persistent 160-hour-per-30-day runtime counter. YAML and actual counter script were tested for restart accounting, threshold shutdown and budget period renewal. Cloud VM execution of these safeguards remains unverified until provisioning succeeds.
