"""Read-only, synthetic knowledge-1 dependency map for stakeholder demos.

Graph nodes and consumer dependencies are extracted from confirmed E4
KnowledgeSnapshot records, not guessed by a language model and never from
evaluation labels. It makes no claim to be a production metadata catalog.
"""
from __future__ import annotations

from functools import lru_cache
from datamesh_release_protocol.stand.fixtures import catalog


@lru_cache(maxsize=1)
def development_knowledge_map() -> dict:
    _, snapshots = catalog()
    snapshot = snapshots["ACCEPT"]
    snapshot.verify()

    producer = snapshot.old_contract.owner_domain
    active_usages = [
        item for item in snapshot.records
        if item.kind == "usage"
        and item.status == "confirmed"
        and item.data.get("active") is True
        and item.data.get("product_id") == snapshot.product_id
    ]
    consumer_domains = sorted({record.owner_domain for record in active_usages})
    nodes = [{"id": producer, "role": "producer", "status": "confirmed"}]
    nodes += [
        {"id": domain, "role": "consumer", "status": "confirmed"}
        for domain in consumer_domains if domain != producer
    ]
    edges = [
        {
            "source": producer,
            "target": record.owner_domain,
            "kind": "confirmed_usage",
            "product_id": record.data["product_id"],
            "consumer_id": record.data["consumer_id"],
            "record_id": record.record_id,
        }
        for record in sorted(active_usages, key=lambda record: record.record_id)
    ]
    if not active_usages or any(edge["source"] == edge["target"] for edge in edges):
        raise RuntimeError("synthetic dependency map integrity check failed")
    return {
        "dataset": "synthetic_E4",
        "schema_version": snapshot.schema_version,
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_completeness": snapshot.completeness,
        "evaluation_oracle_loaded": False,
        "explanation": "Versioned knowledge-1 snapshot with confirmed consumer usage records",
        "nodes": nodes,
        "edges": edges,
    }
