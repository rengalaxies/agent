# Review of cloud acceptance harness

One fresh reviewer examined the candidate helper/control harness; one substantive fix pass. This review is distinct from the adapter review in ../review.md. No production service behavior changed in this pass.

Accepted findings and fixes, with RED→GREEN checks in tests/service/test_kaiten_live_acceptance.py:

1. Removed arbitrary remote file reads: credentials/service configuration cannot be returned through a generic read action. Test-log export is parsed into fixed test counters/names, never raw output. Test child environments exclude provider credentials.
2. Assessor requires the current result intent, delivery receipt, persisted published generation, exact scoped comment ID/digest and full provider base/head/consumer snapshots. Stale notices and absent pins cannot produce PASS.
3. Recovery evidence records actual PID/start ticks, intent SENDING/lease, DB device/inode and verified remote ID/digest before an external SIGKILL. Recovery checks require a new process, same DB, recovered SENDING and receipt wrote=false; no hardcoded restart success.
4. Every connector fetch, including publication fences, is pinned to the expected PR, OPEN state, head/ref/base/destination and current phase target.
5. Candidate manifest is anchored to a local SHA, exact file set/hashes and expected module origins; isolation covers policy, constitution, ownership, model/runtime context and installation/environment identity.
6. Append-only failure history and reconciliation notices prevent revived work from hiding earlier failures.
7. Control run IDs are validated before opening logs; logs use exclusive creation.
8. Added explicit scoped target lifecycle operations; secondary exact title/board/relationship checks precede mutation. Result deletion additionally proves the native comment, marker/author and stored digest before deletion. Recreation uses an explicit semantic card-context update, not SQLite alteration.

Local helper suite: 12 tests OK. Full candidate Linux suite: see linux-tests-summary.json (157 tests, zero skips, four SIGKILL cases).

Operational findings: cloning root-owned candidate mirrors from agent-owned production mirrors requires exact-source safe.directory in the child git upload-pack, not only the parent git command. Trust remains command-scoped; production/global Git configuration is unchanged. Intermittent SSH connect timeouts were recorded; a pinned-host multiplexed connection was reused once available.
