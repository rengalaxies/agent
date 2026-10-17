"""Durable authorization, restart, duplicate suppression and receipt demo."""
import json
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from tests.test_knowledge import fixture,T
from datamesh_release_protocol.knowledge import KnowledgeStore
from datamesh_release_protocol.knowledge_release import KnowledgeReleaseEngine

with TemporaryDirectory() as directory:
    path=Path(directory)/'ledger.json'
    store,old,new=fixture(path)
    snapshot=store.build_snapshot('proposal',old,new,T+timedelta(seconds=2))
    first=KnowledgeReleaseEngine(store).run(snapshot.snapshot_id,'run-1',T+timedelta(seconds=3))
    restored=KnowledgeStore(list(store.authorities),path)
    replay=KnowledgeReleaseEngine(restored).run(snapshot.snapshot_id,'run-1',T+timedelta(seconds=4))
    duplicate=KnowledgeReleaseEngine(restored).run(snapshot.snapshot_id,'run-2',T+timedelta(seconds=4))
    restored.acknowledge_publication(first.release_id,'synthetic-publisher-receipt',T+timedelta(seconds=5))
    final=KnowledgeStore(list(store.authorities),path)
    print(json.dumps({'first_state':first.terminal_state,'restart_exact_replay':first==replay,
        'second_run_state':duplicate.terminal_state,'same_release_id':first.release_id==duplicate.release_id,
        'pending_after_receipt':len(final.pending_publications()),'journal_events':len(final.release_journal())},indent=2))
