# Research UI - synthetic demonstration
Status: static explanatory examples plus API-connected V2, E4 and knowledge-1 panels. This is not the new migration-completion product. Last status review: 2026-10-16.

## Run
From the repository root, with Python 3.12 and the project dependencies:

```bash
python -m pip install -e '.[api,distributed,test-api]'
PYTHONPATH=src python -m services.local_demo
```

Open http://127.0.0.1:8080. This launcher serves the UI and existing API on loopback only. No Docker, database or LLM is required for the optional-local-audit synthetic mode; an optional PostgreSQL audit is a separate integration. It does not connect to client systems. Stop with Ctrl+C.

Serving only `ui/index.html` with a static HTTP server shows the explanatory examples; live panels then explicitly report unavailable API. For a real public deployment use TLS, authentication and an approved topology; the local launcher is not a production server configuration.

The mock shows:
1. Domain map `fintech -> retail -> mobility`.
2. Three **synthetic predetermined** scenarios: formula change -> REJECT; verified RUB/kopecks migration -> ACCEPT; absent consumer position -> NEEDS_REVIEW.
3. Visible rationale, input changes, consumer obligations, decision flow and JSON-style evidence illustration.

## Historical target contract and remaining gaps
The following list is an earlier design, not an exact inventory of implemented endpoints. In particular, run lookup, idempotency keys and authentication for the demo API remain production gaps. Current implemented routes are in `services/demo_api.py`:
- GET /api/v1/demo/scenarios -> {scenarios:[{id,title,description}]}
- POST /api/v1/demo/runs -> {run_id, scenario_id, status}; accepts scenario_id + idempotency key.
- GET /api/v1/demo/runs/{run_id} -> {decision, reason_codes, consumer_positions, evidence_refs, snapshot_id, constitution_version, stages}.
- GET /api/v1/knowledge/map?snapshot_id=... -> {nodes, edges, completeness, updated_at}; only verified, allowed links.
- GET /healthz -> readiness with clear `demo_live` flag.
A live mode should be enabled only when API health and auth are confirmed; never quietly fallback from unavailable backend to predetermined results labeled 'live'.

## Controls / security
UI uses synthetic data only and has no secrets. Production backend routes need server-side auth, RBAC per domain, rate limiting, strict CORS and security headers. Do not expose PostgreSQL, Kafka, SSH or internal domain API.
A disconnected core VM cannot make live release decisions. Show availability state and allow only clearly marked recorded/synthetic demonstrations.

## Acceptance
- Responsive at mobile/desktop widths.
- A user can select all three scenarios and see three distinct outcomes.
- No simulated outcome is presented as an empirical E3 result.
- No user-provided JavaScript or untrusted network data is interpolated into innerHTML in eventual API-connected version.
- Deployed under dedicated UI IPv4 and HTTPS after secure Cloud.ru provisioning.

## Verified integration as of 2026-10-13

The interface is no longer only a set of canned outcomes. The offline examples remain explicitly labeled synthetic, while the live panel calls the actual deterministic V2 engine on development scenarios. A separate signed three-process E4 demo is launched from the API. The knowledge-1 panel renders confirmed synthetic consumer dependencies from a verified snapshot, not a hand-entered graph. Core V2 now supports fail-closed PostgreSQL audit logging with a SHA-256 decision digest; local Docker integration verifies that the record survives a database-container restart. These are development demonstrations, not H1 confirmatory E3 measurements, real user records, or a deployed Cloud.ru service.

CI evidence: https://github.com/rengalaxies/agent/issues/5 and https://github.com/rengalaxies/agent/issues/13. Cloud.ru deployment is blocked until a project-scoped encrypted remote Terraform state is configured (https://github.com/rengalaxies/agent/issues/6).
