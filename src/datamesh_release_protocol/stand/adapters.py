"""Equivalent typed YAML registry and JSON domain-event adapters."""
import json
from pathlib import Path
import yaml
from ..knowledge import KnowledgeStore,KnowledgeRecord


def from_yaml(path,authorities):
    store=KnowledgeStore(authorities)
    store._restore(yaml.safe_load(Path(path).read_text()))
    return store


def from_events(path,authorities):
    store=KnowledgeStore(authorities)
    for event in json.loads(Path(path).read_text()):
        record=KnowledgeRecord.model_validate(event['record']);actor=event['actor']
        if event['operation']=='propose':actual=store.propose_record(record,actor,record.valid_from)
        elif event['operation']=='confirm':actual=store.confirm_record(record.record_id,actor,record.evidence_ref,record.valid_from)
        elif event['operation']=='revoke':actual=store.revoke_record(record.record_id,actor,record.evidence_ref,record.valid_from)
        else:raise ValueError('unknown domain event')
        if actual.model_dump(mode='json')!=record.model_dump(mode='json'):raise ValueError('event content differs from resulting version')
    return store
