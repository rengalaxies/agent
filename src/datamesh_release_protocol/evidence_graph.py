"""Read-only explanation graph over a verified knowledge snapshot.

This projection does not authorize a release, discover unregistered consumers, or
turn a metadata assertion into a fact about running code. Use KnowledgeReleaseEngine
for authorization and its current-state fence.
"""
from __future__ import annotations

from .knowledge import KnowledgeSnapshot, digest


def project_evidence_graph(snapshot: KnowledgeSnapshot, changed_fields: list[str] | None = None) -> dict:
    """Return reproducible evidence paths, retaining untrusted/stale records as warnings.

    None means product-wide (including semantic changes). An explicit list narrows
    to field usages; an empty list has no field impacts. Snapshot completeness is
    never upgraded by that filter. References outside the snapshot remain explicit.
    """
    snapshot.verify()
    by_id = {r.record_id: r for r in snapshot.records}
    nodes = []
    edges = []
    issues = list(snapshot.issues)
    impacts = []

    def edge(source, target, relation, evidence):
        edges.append(dict(source=source, target=target, relation=relation, evidence=evidence))
        if target not in by_id:
            issues.append(f'dangling:{source}:{relation}:{target}')

    for record in snapshot.records:
        warnings = []
        if record.status != 'confirmed':
            warnings.append(record.status)
        if record.valid_until and record.valid_until <= snapshot.as_of:
            warnings.append('expired')
        nodes.append(dict(id=record.record_id, version=record.version, kind=record.kind,
                          owner=record.owner_domain, confirmed_by=record.confirmed_by,
                          evidence_ref=record.evidence_ref, warnings=warnings,
                          record_hash=snapshot.record_hashes[f'{record.record_id}@{record.version}']))
        issues.extend(f'{warning}:{record.record_id}' for warning in warnings)
        data = record.data
        for key, relation in [('producer_team_ref', 'owned_by'), ('consumer_team_ref', 'owned_by'),
                              ('usage_ref', 'requires_usage')]:
            if key in data:
                edge(record.record_id, data[key], relation, record.record_id)
        if record.kind in ('usage', 'attribute', 'coverage', 'global_rule', 'constitution'):
            products = [p for p in snapshot.records if p.kind == 'product'
                        and p.data['product_id'] == data['product_id']]
            for product in products:
                edge(product.record_id, record.record_id, record.kind, record.record_id)

    for usage in snapshot.records:
        if usage.kind != 'usage' or not usage.data['active']:
            continue
        fields = usage.data['field_paths']
        if changed_fields is not None and not set(fields).intersection(changed_fields):
            continue
        requirements = [r for r in snapshot.records if r.kind == 'obligation'
                        and r.data['usage_ref'] == usage.record_id]
        if not requirements:
            issues.append(f'missing_obligation:{usage.record_id}')
        # Paths are evidence references, not a claim that this consumer is healthy.
        impacts.append(dict(consumer_id=usage.data['consumer_id'], usage=usage.record_id,
                            field_paths=fields, owner=usage.owner_domain,
                            requirements=sorted(r.record_id for r in requirements),
                            evidence_paths=[[p.record_id, usage.record_id, r.record_id]
                                            for p in snapshot.records if p.kind == 'product'
                                            and p.data['product_id'] == usage.data['product_id']
                                            for r in requirements]))
    payload = dict(format='evidence-graph-1', snapshot_id=snapshot.snapshot_id,
                   as_of=snapshot.as_of.isoformat(), completeness=snapshot.completeness,
                   scope='registered snapshot records only',
                   changed_fields=None if changed_fields is None else sorted(set(changed_fields)),
                   nodes=sorted(nodes, key=lambda n: n['id']),
                   edges=sorted(edges, key=lambda e: (e['source'], e['relation'], e['target'])),
                   impacts=sorted(impacts, key=lambda i: i['usage']), issues=sorted(set(issues)))
    return {**payload, 'graph_id': digest(payload)}
