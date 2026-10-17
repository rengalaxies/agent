# Integrated lab workflow contract v1

Single SQLite store owned by lab/product/store.py. UI is plain HTML/JS, served by a separate FastAPI lab app; existing managed/UI entrypoints remain untouched. Demo roles are explicit, never real authentication. Application execution is always BLOCKED server-side.

API prefix /api/lab:
GET /state -> {changes:[], snapshots:[], jobs:[], assessments:[], cards:[], decisions:[], candidates:[], verifications:[], journal:[], execution_permission:false}
POST /changes {change_id,title,intent,proposed_diff,proposed_files,kind:"breaking"|"safe",revision,source_commit} -> change
POST /jobs {change_id,operation:"snapshot"|"analysis"|"prepare"|"verify",mode:"LIVE RUN"|"REPLAY"|"FIXTURE / CONTROL",idempotency_key} -> job (202)
POST /decisions {card_id,revision,assessment_digest,team,actor,decision,comment} -> decision
POST /apply -> 403 BLOCKED
GET /healthz -> {ready:true,execution_permission:false,demo_roles:true}

All entities: id, change_id, revision, input_digest, source_commit, mode, created_at; result entities add basis_digest, current bool. Job fields: id, operation,status QUEUED/RUNNING/SUCCEEDED/FAILED/BLOCKED/UNKNOWN, error, result_id. Job success is technical completion only. Queue unique idempotency key bound to exact request; conflicting operations on one revision denied. Late results persist current=false if change revision/input or latest snapshot basis differs. New revision/new materially changed snapshot invalidates assessment/cards/decisions/candidate/verification. Identical snapshot content keeps basis digest stable (collection timestamps excluded). Restart marks interrupted RUNNING jobs UNKNOWN and never retries automatically. SQLite transactions serialize writes; one server process/worker. Inputs never become shell commands.

Snapshots collector interface lab.product.collectors.collect() -> {basis_digest, collected_at, mode:"LIVE RUN", postgres:{...},rabbitmq:{...},repository:{...},owners:{...},edges:[{source,target,source_kind,method,confirmation,limitations,collected_at}],coverage_gaps:[], source_commit}. Runs only against env SOURCE_READ_DSN + RabbitMQ read-only management endpoint RABBIT_READ_URL with RABBIT_READ_USER/PASSWORD, repo root LAB_REPO_ROOT. Management account has monitoring tag and empty configure/write/read vhost permissions; no message consumption permission. Collection errors become BLOCKED, never silently fixture.

Workers bridge existing core.LLM / stage_candidate / evaluator.verify and runtime.inbox. LIVE analysis+prepare require actual model credentials server-only. REPLAY imports saved real-agent evidence explicitly. FIXTURE / CONTROL is deterministic test controller evidence, never a model or live acceptance. Prepare/verify run without requiring apply permission. Candidate path is private server artifact; UI receives actual diff/content and references, no secrets. Frozen financial verifier remains scoped R1-R5; separate boundary checks do not automatically authorize apply.

UI uses these exact endpoints/fields, renders four tabs (changes/change details/team inbox/patch+verification), displays mode beside every result and current/stale status. Fields may be extended compatibly; backend and UI coordinate changes through root agent.
