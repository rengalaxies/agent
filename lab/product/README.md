# Internal integrated lab workflow

Plain HTML/JS + the repository's FastAPI/Python stack. Existing managed demo and `ui/index.html` are untouched. The app is served separately on localhost; no Cloud.ru deployment is claimed.

User path: create a supported breaking or docs-only change → collect actual PostgreSQL/RabbitMQ/repository/declared-owner grounds → asynchronous analysis → billing/analytics or coordinator cards → exact-revision team decision → actual SQL candidate → independent fresh financial verification → history. Preparation and verification remain available while apply is always blocked server-side.

## Run the UI

Python 3.12, Docker with Compose (for independent candidate checks), and the existing lab dependencies are needed. API dependencies tested: fastapi 0.115.12, uvicorn 0.34.2, httpx 0.28.1. Core database/broker application dependencies remain in `lab/requirements.lock`.

```sh
python -m pip install fastapi==0.115.12 uvicorn==0.34.2 httpx==0.28.1 pika==1.3.2 'psycopg[binary]==3.2.9'
python -m uvicorn lab.product.api:app --host 127.0.0.1 --port 8088
```

Open `http://127.0.0.1:8088`. Default durable database is `/tmp/lab-product/state.sqlite`; set `LAB_PRODUCT_DB` to a private persistent path for retention. Keep one server process/worker. Do not expose this trusted demo-role API as an authenticated corporate service. Role selector filters the demo inbox and does not authenticate users.

Without live source credentials collection visibly BLOCKS; no fixture is substituted. Required server-only settings:

- `SOURCE_READ_DSN`: unprivileged SELECT/catalog role in the lab source PostgreSQL database.
- `RABBIT_READ_URL`, `RABBIT_READ_USER`, `RABBIT_READ_PASSWORD`: monitoring-only management account; configure/write/read permissions all `^$`, so it cannot consume, publish or mutate.
- `RABBIT_PERMISSION_ATTESTATION_FILE`: fresh trusted operator/CI JSON `{username,vhost,configure,write,read,broker_identity,collected_at,source}` matching actual authenticated user and live broker identity; see collector tests. The collector never receives broker administrator credentials. Permission provenance is explicitly an attestation, not a claim of self-verification.
- `LAB_REPO_ROOT`: trusted checkout, default repository root. Supported changes must name the exact current commit; caller-provided stale/fictional commits are rejected.
- `LAB_ENABLE_ISOLATED_VERIFIER=1` enables the existing Docker verifier.
- For a new LIVE model run only: `CLOUDRU_FOUNDATION_API_KEY` and `CLOUDRU_LLM_MODEL`, never sent to the browser.

Model cap per change revision: two reserved calls total across analysis/prepare, 64000 tokens, 240 measured model seconds, serial execution. Unknown/missing provider usage blocks subsequent inference; no automatic paid retry. No hard currency cap is claimed. A team acknowledgement is never an action grant.

## Reproduce tested full paths

GitHub Actions `Integrated lab product recheck without inference` (`lab-product-recheck.yml`) is the repeatable no-cost-inference path: actual disposable services, monitoring account, live collection, browser journey, A-H controls, screenshots and cleanup. It has no model secrets. `Integrated lab product path and new real agent` additionally has a model job gated on integration PASS. Do not rerun it for cosmetic UI changes.

For the same local CI controller, install Playwright 1.51.0 and Chromium, use a clean checkout/output directory, and provide `GITHUB_SHA` equal to the actual checkout commit, `GITHUB_REPOSITORY=rengalaxies/agent`, `GITHUB_RUN_ID=local`. Then run `python -m lab.product.ci_flow`. It creates only disposable local Compose resources, binds database/management ports on loopback, runs the browser and deletes the resources. `--live` adds real paid inference; its prerequisites and limits above apply. `lab.product.ci_server` contains explicitly CI-only delay hooks for late-result/SIGKILL tests and is not the normal server entrypoint.

The controller uses only fixed argv commands and trusted SQL fixtures; user text never becomes a shell command. API endpoints and freshness rules are in `CONTRACT.md`; frozen expected scenarios are in `SCENARIOS.json` and `SCENARIOS.sha256`.

## Durable state and boundaries

SQLite transactions persist all change revisions, snapshots, jobs, assessments, cards, decisions, candidate artifacts, verifier results and action history. Requests return queued jobs rather than waiting for inference. Exact-input idempotency keys and revision conflicts are checked server-side. Late results remain in history with `current=false`. New revisions/material grounds invalidate old results and decisions. Repeated collection with the same semantic basis does not invalidate accepted material evidence merely because its timestamp changed; superseded snapshot collections themselves are shown as historical. Interrupted RUNNING jobs become UNKNOWN after actual process restart and are not automatically repeated.

LIVE RUN means new live collection/model invocation; REPLAY means reused saved model output, even if its artifact is independently rechecked now; FIXTURE / CONTROL identifies deterministic scenario control. Configured bindings are not observed message delivery. Repository syntax adapters are narrow literal AST/SQL-reference extraction, not general static analysis or a complete dependency graph. Owner bindings are declared, not discovered people. Telemetry is absent and shown as a gap.

All financial verification is scoped R1-R5 candidate acceptance. Original full T01-T19 acceptance, deployed-state freshness, signed multi-party authorization and general recovery remain open. `POST /api/lab/apply` always returns 403. No model output, team review or green technical job can override it.


## Browser-only interview preparation

The participant installs nothing. Remote executor: `.github/workflows/lab-interview-ci.yml`, no model credentials. Interview runbook/status: `lab/reports/interview/RUNBOOK.md` and `REPORT.md`. Until a protected cloud URL passes target acceptance, use CI_ONLY evidence/saved-materials format; localhost is not participant delivery.

Optional deployment owner configuration: `LAB_REQUIRE_AUTH=1`, nonempty `LAB_AUTH_USERNAME`/`LAB_AUTH_PASSWORD` from private server secrets, `LAB_COOKIE_SECURE=1` behind HTTPS. Authentication covers every UI/API route; protected mode requires a selected isolated session. Keep one process/worker, private durable session storage, no public database/broker/admin. New sessions/reset each have separate SQLite and artifacts; observations are opt-in, category-only, exportable/deletable separately from technical audit.

The ordinary web process has no Docker authority: `LAB_ENABLE_ISOLATED_VERIFIER` defaults off. Only the trusted disposable CI harness sets it to1. Do not mount a Docker socket or grant Docker-group privileges to the public application. New cloud verification requires a separately restricted executor; saved checks must remain historical REPLAY. Apply stays403.
