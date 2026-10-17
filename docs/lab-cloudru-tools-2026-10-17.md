# Cloud.ru tools review - 2026-10-17

Scope: public official documentation and the official DevServices CLI repository. No Cloud.ru account API calls, resources, credentials or mutations were used for this review. Availability in project `20853297-65b7-42a8-af40-25c8d2df4e11` is **UNTESTED** unless separately evidenced by an operational report. Documentation existence does not prove project enablement.

## Recommendation

Keep GitHub Actions as the delivery/control path, Terraform for infrastructure state, and a separately verified guest OS channel for Docker deployment. Use Foundation Models as a model provider for the local bounded runtime if a valid service-specific key is present. Do not migrate delivery to new managed agent resources merely for novelty.

## Verified capabilities

| Tool | Verified purpose | Requirement and limitation | Recommendation |
|---|---|---|---|
| Foundation Models | OpenAI-compatible model API at `https://foundation-models.api.cloud.ru/v1` | Service-specific API Key Secret with Foundation Models selected. IAM access-key secrets and Workflow API keys are not automatically valid here | Run a bounded inference preflight, record actual model and usage; never claim live LLM readiness based on configuration alone |
| Model catalog | Includes `openai/gpt-oss-120b` and `Qwen/Qwen3-Coder-Next` with function calling / structured output | Public catalog is not an entitlement check. Some models are external, forwarding data outside Cloud.ru | Pin the selected model in run metadata and verify actual response |
| DevServices CLI `eds` | Official CLI for Repo and Workflow Studio | `EDS_API_KEY`, `EDS_PROJECT_ID`, JSON output. Not a VM guest command runner | Optional diagnostics for existing managed demo; no need to replace working Python/API path |
| Workflow Studio | Workflows, Pipelines, Services; Services connects Git code to Container Apps | Run completion alone does not mean app is live; check application status `running`. Infrastructure has charges | Keep distinct from VM deployment |
| AI Agents | Managed agents, MCP and agent systems | Requires connected ML Inference / Foundation Models, managed compute and relevant keys | New resources require separate scope/cost decision; existing VM runtime is sufficient for first experiment |
| Container Apps MCP example | Official tutorial recommends a custom MCP implementation using Container Apps and Artifact Registry APIs | Repository is `Nick1994209/cloudru-containerapps-mcp`, not an official universal infrastructure MCP. Does not establish VM exec capability | Do not replace verified deployment scripts with this tutorial example |
| VM Manager | Guest agent software management; Validation / Enforcement / Patch policies, including exec/file/pkg | Preview and free per overview. Requires installed and registered guest agent. Public runner API was not verified | Inspect whether agent already exists; do not invent an API path |
| SSH and consoles | SSH with keys/password; virtual console; serial console | Serial console is Preview and requires running VM and guest login/password. Console recovery is documented via UI | Verify existing runner SSH or preinstalled bounded executor before deployment |
| Monitoring | Resource metrics and dashboards | Does not independently prove correct business processing | Supplement with consumer-state checks |
| Audit Logging | Cloud audit events, 30-day storage, Object Storage archival | SIEM export described as Preview. Cloud audit is not application evidence | Retain run-level evidence separately |
| Distributed Train CLI / SDK | CLI and Python SDK for Distributed Train | Not a universal Cloud.ru SDK or VM management channel | Not needed for this stand |

## Guest execution and bootstrap limitations

No documented universal public Cloud.ru endpoint for arbitrary commands in an already-created VM was verified. Do not guess `/exec` or `/run-command` paths. Terraform configuration updates do not establish that commands executed in the guest.

VM Manager policy content supports `exec.validate` and `exec.enforce` with `script`, `args`, and `interpreter` (`SHELL` / `POWERSHELL`, among others). This is usable only after the guest agent is installed and registered. Registration instructions require opening a guest command line, downloading the agent, and installing its generated token/configuration. Consequently this does not by itself solve an inaccessible-guest bootstrap problem.

The current VM creation documentation says SSH keys cannot be added to an existing VM through the personal cabinet; addition requires a guest terminal. Compute Agent password management is not evidence of arbitrary guest execution support.

September 2026 release notes extend cloud-init to all image types. An older FAQ still says custom images only; use the release notes and current creation guide. Neither statement promises re-execution of updated user-data on an existing VM. Do not recreate the VM merely to rerun bootstrap.

## Costs and maturity

- VM Manager: explicitly Preview and free in the inspected overview.
- Serial console: explicitly Preview.
- Foundation Models: pay-as-you-go; input/output token units and model card prices. Exact current model rates were not verified and are not estimated here.
- AI Agents: allocated/dynamic vCPU and RAM, with separate Foundation Models / ML Inference / Object Storage charges. Numerical examples in its documentation are illustrative, not a current tariff quote.
- Workflow Studio: uses Container Apps or Managed Kubernetes infrastructure; both are paid, with Container Apps free tier where applicable. Do not infer a zero bill.
- GA status for Foundation Models, AI Agents and Workflow Studio was not explicitly established by the inspected pages.

## Security and reproducibility notes

The official `eds` README documents production defaults `https://devtools.api.cloud.ru/repo/api/v1` and `https://devtools.api.cloud.ru/workflow/v1`. Its `repo clone` embeds the API key in plaintext in `.git/config`; do not print remote URLs or include that directory in artifacts. Prefer environment-provided secrets and pinned binaries/commits over unreviewed latest installers.

Cloud.ru's GitHub Actions tutorial validates the build/push/Container Apps pattern. Its broad auto-deploy tag example is not an immutable deployment guarantee. This experiment should record exact source commit and image digests and should test application/consumer state, not merely a green workflow.

## Official sources inspected

1. [Foundation Models authentication](https://cloud.ru/docs/foundation-models/ug/topics/api-ref__authentication)
2. [Foundation Models chat API](https://cloud.ru/docs/foundation-models/ug/topics/guides__llm-chat-request)
3. [Available models](https://cloud.ru/docs/foundation-models/ug/topics/overview__available__models)
4. [Foundation Models pricing](https://cloud.ru/docs/foundation-models/ug/topics/pricing)
5. [Official DevServices CLI repository](https://github.com/cloud-ru/evolution-devservices-cli)
6. [DevServices CLI tutorial](https://cloud.ru/docs/pipeline/ug/topics/tutorials__dev-services-cli)
7. [Workflow Studio limitations](https://cloud.ru/docs/pipeline/ug/topics/overview__limitations)
8. [Workflow Studio pricing](https://cloud.ru/docs/pipeline/ug/topics/faq_cq_pricing)
9. [GitHub Actions integration](https://cloud.ru/docs/artifact-registry-evolution/ug/topics/tutorials__ci-cd)
10. [AI Agents overview](https://cloud.ru/docs/ai-agents/ug/index)
11. [AI Agents prerequisites](https://cloud.ru/docs/ai-agents/ug/topics/guides__create-agent)
12. [AI Agents pricing](https://cloud.ru/docs/ai-agents/ug/topics/pricing)
13. [Custom Container Apps MCP tutorial](https://cloud.ru/docs/foundation-models/ug/topics/tutorials__vibecode-django-photo-app-mcp-server)
14. [VM Manager overview](https://cloud.ru/docs/vmmanager/ug/index)
15. [VM Manager registration](https://cloud.ru/docs/vmmanager/ug/topics/guides__host-register)
16. [VM Manager exec policy schema](https://cloud.ru/docs/vmmanager/ug/topics/concepts__politics-enforcement-validation)
17. [VM connection methods](https://cloud.ru/docs/virtual-machines/ug/topics/guides__connection)
18. [Serial console](https://cloud.ru/docs/virtual-machines/ug/topics/guides__console-serial)
19. [VM creation, SSH keys and cloud-init](https://cloud.ru/docs/virtual-machines/ug/topics/guides__create-vm)
20. [VM release notes](https://cloud.ru/docs/virtual-machines/ug/topics/overview__release-notes)
21. [Audit logging](https://cloud.ru/docs/audit-logging/ug/index)
22. [Monitoring](https://cloud.ru/docs/service-monitoring/ug/index)
23. [Distributed Train CLI and SDK](https://cloud.ru/docs/aicloud/mlspace-cli/index)
