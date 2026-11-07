# Confluence read-access preflight — 2026-11-07

Existing owner-authorized Atlassian credential successfully read the configured
site's Confluence API v2 spaces endpoint. No new credential was created.
No page contents or attachments were read. This is access preflight only.

Runtime connector is not implemented. Next input is one explicit page URL in
a Jira issue description. Limit initial integration to the agreed site, page
text and ordinary tables; retain page ID, version, section and supporting text.
No child-page search, link traversal or attachment retrieval.

## Reader and rendering failure controls

New deterministic cases cover reading changed version2 after version1,
removing an explicit link with no Confluence call, and denied/deleted pages
(403/404). Reader emits UNAVAILABLE with page identity and safe reason for
access denial or disappearance; old content is not reused. Re-rendering
replaces the prior documentation section, including when no links remain.
The original failures were reproduced before the fix.

These are test-stand controls, not real Confluence access revocation tests.
They apply when analysis is triggered. Standalone page-version changes and
Jira-link changes do not yet independently enqueue a Bitbucket analysis.
That invalidation path is required before unattended three-system acceptance.

## Documentation change invalidation

Bitbucket analysis snapshots now combine the semantic PR version with a
digest of explicitly linked page context (identity, version, extracted text
and availability). Both list/reconcile and fetch use this same snapshot
path. A page-version change or removal of a link therefore changes the
resource version during the next polling reconciliation. Analysis rendering
uses the context captured by its snapshot. Publisher source rechecks use
the combined version.

Regression through the actual Service queue: original context creates
generation1, unchanged context adds no work, page version2 creates
generation2 with the same Git head, removing the page creates generation3
and removes the old text. This is stand acceptance. Real remote page change
with unattended polling and target VM qualification remain pending.

## Actual page-change polling acceptance

Updated authored Confluence page360725 from version1 to version2 while PR2
Git head stayed 16003689c9e99e9ba593168cc5347de090888c7f. Ordinary
Service.reconcile detected the context version and created generation6
after baseline generation5. Worker delivered stale notice and result to
the existing KAN-8/comment10010. API read-back confirms the new page text.
Next reconciliation enqueued zero jobs and performed zero worker steps.

This acceptance used the existing local LIVE queue and filtered candidates
to PR2 to avoid publishing unrelated pilot results. No operator event was
injected for the page change. Continuous VM polling remains unqualified.
See page-change-polling-live.json.

## Publication candidate limits and review

Reader accepts at most five explicit pages with 4000 extracted characters per
page; truncation is visible. Page response identity and _links.base must match
the configured page ID/site. Malformed unrelated URLs are ignored. HTML void
elements, including self-closing br tags, preserve skipped macro boundaries.
Regression coverage includes both HTML and XML-style serialization.

Confluence remains attributed context in a publication document; it does not
produce code findings or verified compatibility. Page-version invalidation is
qualified locally and via real API polling. Cloud.ru installation of this
feature, token expiry/renewal, cross-system race/outage matrix and semantic
requirement-to-code mapping remain open.
