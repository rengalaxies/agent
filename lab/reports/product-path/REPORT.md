# Integrated user path - CI and browser evidence

**Result:** one connected UI/backend/live-ground/model/independent-verifier path is implemented and verified in isolated CI. It is **not deployed in Cloud.ru**. PR23 remains draft; main and managed demo are unchanged. No external notifications or cloud VM actions occurred. Apply remains BLOCKED server-side.

## Exact revisions and executions

| Evidence | Commit | Actions | Result |
|---|---|---|---|
| Contract + expected A-H frozen before execution | `8bab32889ba3fc1605d811b99c81582e49d2f7f3` | source files `lab/product/CONTRACT.md`, `SCENARIOS.json`, `SCENARIOS.sha256` | fixed expectations |
| First integrated + new real-model path | `373ca9299870ed7379135cefdb8004877ccbb5fc` | [39068710511](https://github.com/rengalaxies/agent/actions/runs/39068710511) | both jobs PASS; independent review found gaps listed below |
| Corrective integrated + new real-model path | `032595515dd733cb0841ab7847955033780c33d8` | [39068862920](https://github.com/rengalaxies/agent/actions/runs/39068862920) | A-H integration and LIVE model path PASS |
| Final journal-origin/readability recheck; zero inference | `d3b7ee2109fb4040d0872cee099a19031c662f2b` | [39069174791](https://github.com/rengalaxies/agent/actions/runs/39069174791) | A-H + browser PASS; 20 product and 20 original unit tests PASS |
| Existing full live-service regression | `032595515dd733cb0841ab7847955033780c33d8` | [39068862881](https://github.com/rengalaxies/agent/actions/runs/39068862881) | PASS; original main scenario matrix remains INCOMPLETE |

Documentation/evidence-only commits after these revisions do not change the tested implementation. The screenshots and raw JSON preserve their exact original source commits rather than pretending all executions used one revision.

## Requirement → implementation → proof

| Requirement | Existing base / gap closed | Verification |
|---|---|---|
| Common contract and state | Runtime/inbox digests combined into transactional SQLite entities and API; analysis-run is an operation job linked to assessment | Store/API unit checks, D/F/G |
| Actual grounds | PostgreSQL system catalogs; broker HTTP GET; literal repository references; declared owners with provenance | Real CI services, stable digest + real binding mutation E |
| Background operations | Durable queue, exact-input idempotency, conflicting-operation denial, errors and UNKNOWN restart | API tests, F/G |
| Team workflow | Separate source-grounded billing/analytics/coordinator cards, exact revision + assessment decisions | A/C/D and browser |
| Real artifact/verifier | Existing stage_candidate + independent fresh PostgreSQL/RabbitMQ verifier, no hidden evaluator input to model | A; new LIVE path with saved requests/responses |
| UI | Four plain HTML/JS views with modes, history, errors, current/stale, patch and per-check evidence | Actual Chromium UI interaction and screenshots |
| Backend admission | Fixed source commit, safe profile validation, path scopes, immutable artifact hashes, apply 403 | API/unit + H |

## What the user can do

The browser creates a supported change without manual JSON editing. It collects live grounds, queues analysis and shows status/error separately from business findings. The change page lists dependency rows with collection time, method, confirmation and limitations. The team inbox records a demo user's revision-specific acknowledgement/review/remarks. The patch page stages actual SQL, displays its diff, runs the independent verifier and exposes each check and its coverage. History preserves stale results and decisions. No interface operation grants apply permission.

All four views use the same SQLite-backed API/state; there is no separate UI business-rule implementation. Durable result entities bind change ID, revision, input/diff/source and basis digests, and candidate/suite digests where applicable. A successful technical job does not imply a passing verifier, accepted team decision or execution permission.

## Scenario matrix - exact checked layer

| Case | Result | Actual checked layers / qualification |
|---|---|---|
| A Breaking change | PASS | Browser creates, collects actual catalogs, analyses, records billing decision, stages real SQL, invokes fresh independent verifier. Integration uses explicitly REPLAY model output; separate LIVE job uses new real model. |
| B Safe change | PASS | Final browser creates supported docs-only proposal; API control analyses it; no dependent blocking cards. A client safe flag cannot override a code/SQL change. |
| C Unknown owner | PASS | API + deliberately removed declared owner binding in copied catalog; live PG/broker collection retained; blocked coordinator card. This ownership variation is CONTROL, not automatic people discovery. |
| D New revision | PASS | API invalidates assessment/cards/decisions/candidate/PASS; browser displays stale history; prior result cannot authorize new version. |
| E Changed infrastructure basis | PASS | Actual RabbitMQ binding added in isolated CI; fresh GET snapshot changes semantic digest and invalidates assessment. Collector is read-only; mutation is the trusted test controller. |
| F Late reply | PASS | Actual asynchronous API job with deliberately delayed deterministic CONTROL analysis finishes after N+1; old result stored current=false. No expensive model needed to test the race. |
| G Restart | PASS | Actual SIGKILL of API/worker while collector job RUNNING, same SQLite reopened; changes/cards/decisions/history survive; job becomes UNKNOWN; same idempotency key does not start a second job. |
| H Restrictions | PASS | Disabled UI apply plus direct POST returns 403 regardless of role/approval body. This is a server gate, not a hidden-button control. |

Screenshots establish rendered UI states; backend invariants are established by the separate API/store assertions and real service checks, not by the pictures. The initial run tested B via API only; the corrective/final run also tests creation through UI.

Real binding digest evidence, retained in `final-recheck/binding-before.json` and `binding-after.json`:

- before: `6b5ab435d0ae1df08c8f61a9501646b6806e3e45dbbb47e7000432a0d9ad3180`
- after: `2e52501245e7c192ac32624a2f8ecdf69d0566b9e7bf756f03df778476f9eb12`

Configuration, declared ownership and static source links remain separate confirmation classes. No spans or observed end-to-end traffic graph is claimed. Absence of edges never proves completeness.

## New paid model runs, all retained

Model `openai/gpt-oss-120b`, official Foundation Models chat endpoint. Two stateless real requests per path: impact analyst and SQL patch executor. Input is the **new live catalog/binding snapshot**, exact submitted broken backfill and allowed code evidence with the reference SQL replaced by the submitted broken artifact. Held-out verifier files/answers are absent from the saved requests. Provider responses, actual patches and independent results are retained under `first-live/` and `reviewed-live/`.

| Run | Requests | Prompt tokens | Completion tokens (including reasoning) | Total | Model seconds |
|---|---:|---:|---:|---:|---:|
| First 39068710511 | 2 | 25005 | 910 | 25915 | 7.680 |
| Corrective 39068862920 | 2 | 25049 | 1224 | 26273 | 8.447 |
| Total new work | 4 | 50054 | 2134 | **52188** | **16.127** |

One initial path and one corrective path were used. The second addressed substantive source/freshness/safe-profile review findings, not cosmetic UI tuning. The later readability/journal-origin change used a separate recheck workflow with no model credentials or inference job. No failed provider calls or paid retries are omitted; both new model paths passed. Replay calls in integration cost no new model tokens.

Runtime enforces at most 2 reserved calls / 64000 tokens / 240 measured model seconds per revision. Unknown prior usage blocks continuation. Cost USD/RUB and manual labor remain NOT_MEASURED; no hard currency cap is promised. The workflow's two permitted paid paths bound this batch to four calls and at most 128000 tokens; no additional paid run was triggered for final screenshots.

Corrective LIVE identifiers:

- input digest: `5e92b5d34fe63bcaae68eed3adf9b9774c88a37c3d0ac1402965335fc39c2bde`
- diff digest: `7b72abaa56af47369f03cfb5dc0fbbff955f4f42e8d7892136381e578994a2ab`
- snapshot basis: `6b5ab435d0ae1df08c8f61a9501646b6806e3e45dbbb47e7000432a0d9ad3180`
- candidate digest: `10d08f22547bc9ad1688107d34de87e1cb29cf5dfb0e3642dfbf54e85b4b3352`
- verification ID: `11d2403653e14fb499e46d1eece349c1`; scoped R1-R5 PASS, never apply permission.

The candidate fixes the real submitted `amount_minor=amount_rub` into exact `amount_rub*100`. Independent verifier runs trusted application code in a new disposable project, mounts candidate SQL read-only, tests per-order totals/mixed S0-S5 behavior and uses its frozen held-out amounts. This remains one narrow repair task, not evidence of general migration competence.

## Review findings and corrections

1. Safe UI sample originally targeted lab/README.md outside the allowed docs-only profile; corrected to docs/note.md and browser-tested.
2. Caller source_commit could differ from actual repository; server now rejects it and worker checks live snapshot source commit.
3. Superseded snapshot collections were visually current; now explicitly historical, with stable semantic basis allowing equivalent recollection without invalidating unchanged material results.
4. Candidate/diff digests were missing in display; persisted/calculated fields and UI are corrected.
5. Service journal events originally inherited a generic FIXTURE / CONTROL tag even for live operations. Raw old evidence is retained unchanged: its primary jobs/assessments/candidates/verifications and provider audit prove LIVE origin. New event provenance now inherits actual operation mode and has a regression test; this metadata correction did not cause extra paid inference.
6. Per-check evidence originally rendered as a dense JSON paragraph; final UI uses a readable table with expandable evidence and source/input/basis bindings.

## Screenshots and evidence

Committed screenshots are lossless WebP copies with pixel equality checked against original CI PNGs; original PNGs remain in Actions artifacts.

- `screenshots/01-sources.webp`: actual PostgreSQL/RabbitMQ/static/declared grounds and limitations.
- `screenshots/02-inbox.webp`: team card and exact-revision decision, final UI recheck (REPLAY-labelled candidate evidence).
- `screenshots/03-patch.webp`, `04-verification.webp`: real SQL diff, per-check independent results and permanent apply blocker, final no-inference recheck.
- `screenshots/05-stale.webp`: stale revision history.
- `screenshots/live-inbox.webp`, `live-verification.webp`: actual corrective LIVE model user path at source 0325955, before the final readability-only polish.

Each subdirectory contains its original run report/state and exact source SHA. Model request/response files contain payloads without Authorization headers. Full original Actions artifacts additionally retain SQLite, controller logs, image manifests and candidate source bundles. The committed JSON/artifact subset plus exact source commit is durable evidence; hosted artifact retention is 30 days.

## Launch and actual placement

See `lab/product/README.md`. Tested placement is disposable GitHub-hosted CI and localhost Chromium. Normal app entrypoint: `python -m uvicorn lab.product.api:app --host 127.0.0.1 --port 8088`, private persistent SQLite path, trusted live read credentials. The no-inference Actions workflow reproduces services/account setup, A-H/browser checks and cleanup. No frontend key, new paid cloud resource, VM replacement, main merge or managed-demo change was made.

Cloud.ru delivery remains concretely blocked: earlier incoming SSH and outgoing GitHub connections timed out; no trusted guest execution channel or OS capacity FIT report exists. Existing encrypted state/recovery credentials and Foundation Models access are available, but they do not prove guest delivery. Do not call the CI UI a Cloud.ru deployment.

## Three next-stage limits

1. Trusted single-worker demo app: role selector/actor names are not corporate authentication, and SQLite/queue are not a multi-instance authorization platform.
2. Narrow grounds/repair profile: one source PostgreSQL DB, one RabbitMQ vhost, literal syntax and declared ownership; no telemetry, full graph completeness or broad language patching.
3. Execution/deployment acceptance remains open: financial candidate PASS does not qualify current VM state, S4 partial cutover/unknown recovery, independent operator restore or full R1-R8 execution admission. Apply stays blocked until those grounds and a fresh exact authority are satisfied.
