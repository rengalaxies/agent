"""Observed dependencies only. No inferred business semantics or owner approval."""
import re
import sqlite3
from collections import defaultdict, deque
from .knowledge import digest

MANIFEST_V12 = 'https://schemas.getdbt.com/dbt/manifest/v12.json'
IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def memory_schema(schemas):
    """Bounded, empty, in-memory SQLite schema; schema types are not SQL code."""
    if len(schemas) > 100 or sum(len(fields) for fields in schemas.values()) > 1000:
        raise ValueError('schema too large')
    connection = sqlite3.connect(':memory:')
    try:
        for table, fields in sorted(schemas.items()):
            if not IDENTIFIER.fullmatch(table) or not fields:
                raise ValueError('unsupported table identifier or empty schema')
            if any(not IDENTIFIER.fullmatch(field) for field in fields):
                raise ValueError('unsupported field identifier')
            columns = ','.join(f'"{field}"' for field in fields)
            connection.execute(f'CREATE TABLE "{table}" ({columns})')
        return connection
    except Exception:
        connection.close()
        raise


def readonly_authorizer(reads):
    def authorize(action, table, column, database, trigger):
        if action == sqlite3.SQLITE_READ:
            reads[table].add(column or '')
            return sqlite3.SQLITE_OK
        if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE):
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY
    return authorize


def import_sql(sql, consumer_id, schemas, source_ref):
    if not consumer_id or not source_ref:
        raise ValueError('consumer and immutable source reference required')
    if len(sql) > 100000:
        raise ValueError('SQL too large')
    gaps = []
    reads = defaultdict(set)
    if '{{' in sql or '{%' in sql:
        gaps.append('uncompiled_template_or_dynamic_sql')
    else:
        connection = memory_schema(schemas)
        try:
            connection.set_authorizer(readonly_authorizer(reads))
            # Compile only; input data and functions are not executed.
            connection.execute('EXPLAIN ' + sql).fetchall()
        except sqlite3.Error:
            gaps.append('unsupported_or_invalid_sqlite_select')
            # Failed compilation can emit a partial, SQLite-version-dependent
            # callback prefix. Do not present it as resolved lineage.
            reads.clear()
        finally:
            connection.close()
    observations = []
    for table, columns in sorted(reads.items()):
        if table not in schemas:
            gaps.append('unresolved_relation:' + str(table))
            continue
        fields = sorted(c for c in columns if c)
        if any(field not in schemas[table] for field in fields):
            gaps.append('implicit_or_unknown_column:' + table)
        if any(str(schemas[table].get(field, '')).lower() in ('json', 'jsonb') for field in fields):
            gaps.append('json_path_semantics_unresolved:' + table)
        observations.append(dict(producer=table, consumer=consumer_id, fields=fields,
                                 field_scope='read_columns' if fields else 'relation_only',
                                 status='observed', evidence_ref=source_ref,
                                 source_hash=digest({'sql': sql, 'schemas': schemas}),
                                 extractor='sqlite-compile-1'))
    payload = dict(format='dependency-observations-1', observations=observations,
                   gaps=sorted(set(gaps)), parse_status='partial' if gaps else 'supported',
                   coverage='provided artifacts only; unregistered consumers unknown')
    return {**payload, 'artifact_hash': digest(payload)}


def import_manifest(manifest, source_ref, bindings=None):
    """Read dependency edges from v12 resource depends_on.nodes, no SQL rendering.

    This validates consumed fields, not the complete dbt JSON schema. Other
    manifest versions are refused with an explicit gap.
    """
    if not source_ref:
        raise ValueError('manifest source reference required')
    bindings = dict(bindings or {})
    if any(not isinstance(k, str) or not isinstance(v, str) or not v for k, v in bindings.items()):
        raise ValueError('bindings must map resource identifiers to nonempty logical identifiers')
    if manifest.get('metadata', {}).get('dbt_schema_version') != MANIFEST_V12:
        return dict(format='dependency-observations-1', observations=[],
                    gaps=['unsupported_manifest_version'], parse_status='partial',
                    coverage='provided artifacts only; unregistered consumers unknown')
    resources = {}
    gaps = []
    for section in ('nodes', 'sources', 'exposures', 'metrics'):
        entries = manifest.get(section, {})
        if not isinstance(entries, dict):
            raise ValueError('manifest resource section must be an object')
        for identifier, resource in entries.items():
            if identifier in resources or resource.get('unique_id') != identifier:
                raise ValueError('duplicate or inconsistent resource identifier')
            resources[identifier] = resource
    if len(resources) > 10000:
        raise ValueError('manifest too large')
    observations = []
    source_hash = digest({'manifest': manifest, 'bindings': bindings})
    for identifier, resource in sorted(resources.items()):
        dependencies = resource.get('depends_on', {}).get('nodes')
        if dependencies is None and resource.get('resource_type') not in ('source', 'seed'):
            gaps.append('missing_dependencies:' + identifier)
        if dependencies is not None and (not isinstance(dependencies, list)
                                         or any(not isinstance(x, str) for x in dependencies)):
            raise ValueError('depends_on.nodes must be a list of identifiers')
        for producer in sorted(set(dependencies or [])):
            if producer not in resources:
                gaps.append('unresolved_dependency:' + producer)
            observations.append(dict(producer=bindings.get(producer, producer),
                                     consumer=bindings.get(identifier, identifier), fields=[],
                                     source_resource=producer, target_resource=identifier,
                                     field_scope='relation_only', status='observed',
                                     evidence_ref=source_ref, source_hash=source_hash,
                                     extractor='dbt-manifest-v12'))
    payload = dict(format='dependency-observations-1', observations=observations,
                   gaps=sorted(set(gaps)), parse_status='partial' if gaps else 'supported',
                   coverage='provided artifacts only; unregistered consumers unknown')
    return {**payload, 'artifact_hash': digest(payload)}


def impact_paths(observations, producer, *, strategy='graph'):
    """Equivalent BFS and repeated flat scans; return observed paths, not safety."""
    if strategy not in ('graph', 'flat'):
        raise ValueError('unknown retrieval strategy')
    adjacency = defaultdict(list)
    if strategy == 'graph':
        for edge in observations:
            adjacency[edge['producer']].append(edge)
    paths = {producer: []}
    queue = deque([producer])
    inspections = 0
    while queue:
        current = queue.popleft()
        edges = adjacency[current] if strategy == 'graph' else observations
        for edge in sorted(edges, key=lambda e: (e['producer'], e['consumer'], digest(e))):
            inspections += 1
            if edge['producer'] != current:
                continue
            target = edge['consumer']
            if target not in paths:
                paths[target] = paths[current] + [edge]
                queue.append(target)
    return dict(paths={key: paths[key] for key in sorted(paths) if key != producer},
                edge_inspections=inspections,
                index_build_edges=len(observations) if strategy == 'graph' else 0)
