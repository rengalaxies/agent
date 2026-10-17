# Initiator and dependent-team inbox - verified CLI replay

**PASS:** [Actions 39067851363](https://github.com/rengalaxies/agent/actions/runs/39067851363), exact implementation commit `0dd24672b93869acd54ab5d4fb9f176707e2e9cd`. Twenty tests and a nine-command actual CLI journey passed. Evidence is committed under `inbox-ci-39067851363/`: CLI command/result transcript, revision inputs, complete persistent team inbox and decision history, unknown-owner inbox and its deliberately modified catalog, unit-test log, and run report.

This is explicitly **SAVED_REAL_AGENT_REPLAY**, not new inference or fresh financial verification. It reuses [39066354050](https://github.com/rengalaxies/agent/actions/runs/39066354050), source `88826fc4c2121657f18d8a2ec00a1605b508f1ee`. Patch/candidate hashes are checked on import. Zero new LLM calls, external notifications or VM actions. Main and the automatic-application block remain unchanged. No team acknowledgement or decision creates an action grant.

## What is discovered and what is configured

The narrow source adapter parses actual Python AST in the saved service snapshot:

- Billing: `channel.basic_get(queue='billing', auto_ack=False)` inside a function that invokes `event_minor`. The adapter identifies this supported business-consumer pattern; the migration's routing probe is not presented as a dependent business team.
- Analytics: literal SQL strings reading `analytics.orders_v1` and `analytics.orders_v2`.

Each ground includes source fragment, exact line, file SHA256, replay source commit and relation type. These are **static references**, not observed live traffic or a complete field-level impact graph. The risk of the change is inferred separately. The owner/team bindings come from **declared** `owners.json`, with its hash and UNKNOWN owner freshness; they are not automatically discovered people. The CLI operator explicitly names `orders-owner` as initiator and `stand-coordinator` as coordinator. These are scenario roles, not verified corporate identities. Unsupported dynamic syntax and undisclosed consumers are outside this adapter's coverage.

The source freshness is HISTORICAL_REPLAY_SNAPSHOT; deployed freshness is NOT_VERIFIED. A changed local app/contract/SQL snapshot cannot borrow the historical PASS. Unknown or conflicting ownership does not cause arbitrary assignment: it produces a blocked coordinator card.

## Card content and meaning

Every card carries change ID, exact revision, assessment digest, affected service(s), dependency object(s), provenance/freshness, inferred risk, separate reproduction result, prepared patch reference/digest, independently verified result with scope, specific next action and owner, team decision, and `execution_permission=false`.

Statuses are: `требуется решение`, `исправление подготовлено`, `проверено`, `заблокировано`, `устарело`. Here `проверено` means the compatible SQL candidate passed the **historical** R1-R5 financial replay. It does not mean the team approved it, that current VM state was checked, or that deployment is allowed. Reproduction here means the submitted broken migration was independently rejected at S1 with CheckViolation; corruption of Billing or Analytics was **not** reproduced in this particular replay and is not claimed.

## Complete observed user journey

1. Initiator submits `orders-minor-001`, revision 1. Separate billing and analytics cards are created. Both contain literal source grounds, replay patch and scoped financial PASS. Next action: that team reviews the patch/results and records its decision for this revision.
2. Billing reviewer records `acknowledged`, bound to its card ID, revision 1 and exact assessment digest. This is only acknowledgement; `grants_execution=false`.
3. Analytics reviewer records `request_changes` on its own card/revision. That card becomes `заблокировано`; next action belongs to `orders-owner`: address remarks and submit a new revision.
4. Initiator repeats the same assessment. The stored result, decisions, two cards and two local notification records are unchanged.
5. Initiator submits revision 2. The two revision-1 cards become `устарело`, both prior decisions become invalid. Two fresh addressed cards require a decision. They have no inherited patch/PASS for revision 2: `NOT_RUN_FOR_THIS_REVISION`. Next action: initiator obtains a new analysis and independent check; teams clarify requirements.
6. A reviewer tries to decide the old billing card. CLI returns exit 2 with `Decision refers to stale or mismatched revision/assessment.` No state is changed.
7. Repeating revision-2 assessment creates no additional notifications: four local notification records total across the two distinct revisions, two active cards.
8. Billing acknowledges revision 2. The new acknowledgement is bound to revision 2; no execution permission is granted and unverified revision 2 is not promoted to verified.
9. In a **separate controlled unknown-owner variation**, the exact `#consume` binding is removed from a copied declared catalog. Billing's source dependency remains visible, owner becomes UNKNOWN, and a blocked card goes to `stand-coordinator` asking them to establish/confirm the owner of that object and repeat assessment. Analytics keeps its own card. There is no mass notification or guessed billing owner.

`inbox-evidence/cli-journey.json` contains exact CLI invocations, exit codes, card/decision statuses, local-notification counts and state digests at every step. `team-inbox.json` preserves inactive cards and invalidated decisions as history rather than deleting them.

## CLI use

From repository root, using a fresh local store:

```sh
python -m lab.runtime.inbox --store /tmp/team-inbox-demo.json assess --change lab/catalog/change.example.json --root . --initiator orders-owner --coordinator stand-coordinator
python -m lab.runtime.inbox --store /tmp/team-inbox-demo.json list
```

For this exact fresh-store example, billing revision 1 is:

```sh
python -m lab.runtime.inbox --store /tmp/team-inbox-demo.json decide --card-id c3511c180d3c216ff81d2a8d --revision 1 --assessment f95a5dc06fa83939ecc2e71e29cfb73645fe9e35120845b25ec7fbe95b2d1316 --team billing --actor billing-reviewer --decision acknowledged --comment "Reviewed this exact revision; no execution permission"
```

For another assessment, use IDs/digests returned by `list`. Allowed decisions: acknowledged, reviewed, request_changes, rejected. Actor/team values are operator-declared audit attributes; the local CLI is **not a multi-user authentication system**. The store uses atomic file replacement and assumes one trusted writer. Local notification records have no external delivery worker.

To replay the full tested journey from a clean checkout without an existing `inbox-evidence` directory:

```sh
python -m lab.evaluator.inbox_flow
```

It invokes the real CLI in new subprocesses and writes JSON evidence. No secrets or model access are needed. The application's existing run-local runtime inbox is retained; this persistent team-review CLI is the minimal internal workflow for the explicitly replayed case.

## Coverage limits

The three requested cases pass in this CLI replay. T17 signal/revision handling is qualified in this scope. T08 has scoped evidence for unknown-owner routing to the designated coordinator; broader conflict resolution and directory authentication remain open. Live ownership validation, corporate inbox authentication, external delivery and general dependency discovery remain future work. No historical financial PASS is upgraded into a fresh transition/deployment authorization.
