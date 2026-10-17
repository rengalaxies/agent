# Interview rehearsal - 19 October 2026

Status: CI_ONLY until a protected Cloud.ru URL and target acceptance are recorded. There is currently no new interview URL. Do not send participants to the existing managed demo or to localhost. The participant installs nothing. GitHub Actions is the remote executor; CI screenshots/JSON are a backup for moderator presentation, not independent participant interaction.

## Access and preflight

The moderator obtains the protected HTTPS URL and separate access credentials from the deployment owner through a private channel. Never place credentials in this document, repository, URL or export. If no accepted HTTPS URL exists, use the saved materials format and say so explicitly. CI HTTP loopback with synthetic Basic credentials proves application checks only, not cloud TLS.

Before each interview, open the protected address in a clean browser context. Unauthenticated access must require authentication. Check exact source commit, readiness and that apply remains BLOCKED. Select a fresh interview session; record its random ID and scenario version. Do not reuse another participant's session. Roles are demonstration labels inside authenticated access, not corporate IAM.

## Three situations

| Session scenario | Start and origin | Task | Expected boundary |
|---|---|---|---|
| confirmed | New empty session; existing A breaking example. Collect actual catalog evidence; explicitly choose REPLAY for saved model analysis/SQL. | "Определи, касается ли изменение твоей команды и почему". "Какое следующее действие ты выберешь?" | Separate billing/analytics cards with current grounds; risk is separate from reproduction. Team acknowledgement never grants apply. |
| unknown-owner | New empty session; existing C declared-owner CONTROL profile, same real collection. Analysis uses FIXTURE / CONTROL. | "Каких сведений не хватает для решения?" | Explicit unknown owner and coordinator question. The missing owner is a controlled input, not a newly discovered production fact. |
| stale | New empty session; repeat existing A then use the existing new-revision action (D); E basis change requires trusted moderator/CI broker control. | "Что изменилось после новой ревизии?" | Prior cards/decisions/patch/PASS are history; fresh assessment is needed. |

For each start: choose scenario, create session, use the existing breaking example to create revision 1, open change details, collect sources in LIVE RUN. For confirmed/stale select REPLAY, run analysis, open inbox, choose team and record its decision. Open patch view, prepare saved SQL. Fresh verification runs only in isolated trusted CI; without that executor use the separately saved verifier evidence as historical REPLAY, not a new PASS. Never give the public web app Docker privileges.

For unknown-owner select FIXTURE / CONTROL analysis after collection; read the coordinator card and its explicit ownership-control label. For stale, use new revision, then confirm prior result is no longer current. No new inference is needed for these situations.

## Recording and clean sessions

Explain the optional minimal observation notice before enabling consent. Recording is off by default. It stores random session ID, scenario/version, mode, timestamps and action/error/decision/help categories; no names, email, free text, keystrokes or screen recording. Technical audit is separate. Declining must not block the scenario.

Enable research recording only after explicit consent. Moderator assistance uses the category selector, without narrative identifying notes. Export JSON for that selected session. Deleting research data removes observations and disables consent; necessary technical audit and evidence remain.

Finish pending work before reset/end. Reset affects only this session and creates a new empty generation, preserving its old technical evidence. A new session has its own empty SQLite/artifact workspace, no previous team's decisions. End the session, then create a new session for the next participant. Export before ending when recording is desired. Do not infer understanding from clicks or describe elapsed time as labor saved.

## Errors and explicit replay

On a blocked/failed/UNKNOWN job, inspect the displayed reason and preserve its technical record. Do not blindly repeat interrupted work or claim a successful result. If LIVE is unavailable, state that it is unavailable; explicitly select REPLAY and start the existing analysis/prepare actions. The failed LIVE job stays in history. Collection itself has no synthetic fallback: unavailable current sources remain blocked. Do not turn a historical PASS into a current cloud check.

On loss of the protected cloud address, switch format to moderator presentation of saved screenshots/JSON. This does not test independent browser use. Stop research recording and export/delete according to the participant's choice; end the selected session.

## Backup and executor

Existing backup screenshots are in `lab/reports/product-path/screenshots/`. This batch adds synthetic-session export and CI browser evidence under `lab/reports/interview/`. Workflow `lab-interview-ci.yml` executes remotely on GitHub Actions without model credentials. All rehearsal reports must state CI_ONLY until target cloud acceptance exists. Agent rehearsal is not a user study.
