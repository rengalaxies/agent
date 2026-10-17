"""Run from repository root: PYTHONPATH=src:. python examples/knowledge/demo.py."""
import json
from datetime import timedelta
from tests.test_knowledge import fixture, T
from datamesh_release_protocol.knowledge_release import KnowledgeReleaseEngine
store,old,new=fixture()
engine=KnowledgeReleaseEngine(store)
for run,formula in [('compatible','purchases_30d > 0'),('semantic-change','sessions_30d > 0')]:
    new.semantic.formula=formula
    snapshot=store.build_snapshot(run,old,new,T+timedelta(seconds=2))
    release=engine.run(snapshot.snapshot_id,run,T+timedelta(seconds=3))
    print(json.dumps(release.producer_view(),ensure_ascii=False,indent=2))
