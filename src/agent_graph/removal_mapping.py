"""Resolve head calls against proven removed base declarations, without mutating contexts."""
from __future__ import annotations

from .discovery import consumers


def proven_removed_operations(policy, base, head, opaque_additions):
    current = {o['id'] for o in head['graph']['operations']}
    result = {}
    for operation in base['graph']['operations']:
        if operation['id'] in current or base.get('operation_id') not in (None, operation['id']):
            continue
        # An operation belongs to a service, which can span multiple allowed
        # repositories. Its old witness file is not the complete provider scope.
        repositories = {r.id for r in policy.repositories if r.service == operation['service']}
        repositories.update(base['sources'][e['source_id']]['repository'] for e in operation['evidence'])
        if repositories & opaque_additions:
            continue
        uncertain = False
        for context in (base, head):
            sources = {s['id'] for s in context['sources'].values() if s['repository'] in repositories}
            operations = {o['id'] for o in context['graph']['operations'] if o['service'] == operation['service']}
            # Provider/collection gaps carry source_id/repository/operation_id.
            # Consumer gaps carry call evidence and do not invalidate the catalogue.
            uncertain |= any(g.get('repository') in repositories or g.get('source_id') in sources
                             or g.get('operation_id') in operations for g in context['graph']['gaps'])
        if not uncertain:
            result[operation['id']] = operation
    return result


def call_key(item):
    citations = item.get('evidence')
    citation = citations[0] if isinstance(citations, list) and citations else citations
    column = item.get('call_column')
    if not isinstance(citation, dict) or type(column) is not int:
        return None
    return (citation.get('source_id'), citation.get('start_line'), citation.get('end_line'), column)


def caller_unverifiable(dependency, head):
    # A fully parsed current file with no matching call proves the old static
    # call is absent within the grammar. Other unreadable files do not undo it.
    repo, path = dependency['repository'], dependency['path']
    present = any(s['repository'] == repo and s['path'] == path for s in head['sources'].values())
    for gap in head['graph']['gaps']:
        if gap['code'] in {'unmapped_call', 'dynamic_parameters', 'requirement_basis_stale'}:
            continue
        citation = gap.get('evidence') or {}
        source = head['sources'].get(gap.get('source_id') or citation.get('source_id'), {})
        gap_repo, gap_path = gap.get('repository') or source.get('repository'), gap.get('path') or source.get('path')
        if gap_repo != repo:
            continue
        if gap_path == path or gap_path is None and not present:
            return True
        if not present and gap['code'] in {'commit_unavailable', 'source_unavailable', 'directory_unreadable', 'object_unavailable'}:
            return True
    return False


def remap_removed_calls(policy, base, head, removed):
    original_gaps = head['graph']['gaps']
    empty = dict(dependencies=[], current_ids=[], resolved=[], gaps=list(original_gaps))
    selected = base.get('operation_id')
    selected_removed = {key for key in removed if selected is None or key == selected}
    if not selected_removed:
        return empty
    # Resolve against the full base catalogue so retained exact routes keep
    # precedence over removed templates. Cross-check each position at head.
    eligible = {call_key(g) for g in original_gaps if g['code'] == 'unmapped_call' and call_key(g) is not None}
    head_calls = {call_key(d): d for d in head['graph']['dependencies'] if call_key(d) is not None}
    parsed, parsed_gaps = consumers(policy, head['sources'], base['graph']['operations'])
    current = {}
    for dependency in parsed:
        if dependency['operation_id'] not in selected_removed:
            continue
        key = call_key(dependency)
        replacement = head_calls.get(key)
        if key not in eligible and replacement is None:
            continue
        dependency = dict(dependency)
        if replacement is not None:
            dependency['replacement_operation_id'] = replacement['operation_id']
        current[dependency['id']] = dependency
    dependencies = {d['id']: d for d in base['graph']['dependencies']
                    if d['operation_id'] in selected_removed and caller_unverifiable(d, head)}
    dependencies.update(current)
    resolved_keys = {call_key(d) for d in current.values()}
    gaps = [g for g in original_gaps if not (g['code'] == 'unmapped_call' and call_key(g) in resolved_keys)]
    # Mapping the historical target can expose previously unparsed usage; do
    # not erase that uncertainty when replacing its unmapped-target gap.
    for gap in parsed_gaps:
        if call_key(gap) in resolved_keys and gap not in gaps:
            gaps.append(gap)
    resolved = [dict(dependency_id=d['id'], operation_id=d['operation_id'], head_call=d['evidence'][0],
                     call_column=d['call_column'], base_declaration=removed[d['operation_id']]['evidence'],
                     replacement_operation_id=d.get('replacement_operation_id'))
                for d in sorted(current.values(), key=lambda d: d['id'])]
    return dict(dependencies=sorted(dependencies.values(), key=lambda d: d['id']),
                current_ids=sorted(current), resolved=resolved, gaps=gaps)
