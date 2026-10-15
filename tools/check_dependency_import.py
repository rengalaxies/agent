"""Report supported-fixture extraction and explicit gaps, not global coverage."""
import argparse
import json
from pathlib import Path
from run_pr_assistant import ROOT, load_example
from datamesh_release_protocol.dependency_import import import_sql, import_manifest, impact_paths
from datamesh_release_protocol.knowledge import digest


def run():
    catalog = json.loads((ROOT / 'examples/pr-assistant/import-catalog.json').read_text())
    rows = []
    for case in catalog['cases']:
        extracted = import_sql(case['sql'], 'fixture-consumer', catalog['schemas'], 'fixture:import-v1')
        actual = {edge['producer']: edge['fields'] for edge in extracted['observations']}
        rows.append(dict(id=case['id'], expected=case['expected'], actual=actual,
                         extraction_matches=actual == case['expected'],
                         gap_expected=case['gap'], gaps=extracted['gaps'],
                         gap_matches=bool(extracted['gaps']) == case['gap']))
    data, _, _ = load_example()
    manifest = import_manifest(data['manifest'], data['source_ref'], data['bindings'])
    actual_edges = sorted((edge['producer'], edge['consumer']) for edge in manifest['observations'])
    expected_edges = sorted([('spending_activity_profile', 'retail-aggregate'),
                             ('retail-aggregate', 'retail-offers')])
    paths = impact_paths(manifest['observations'], 'spending_activity_profile')['paths']
    return dict(kind='bounded-import-diagnostic', catalog_hash=digest(catalog), rows=rows,
                sql_cases=len(rows), supported_cases=sum(not row['gap_expected'] for row in rows),
                cases_with_explicit_gaps=sum(bool(row['gaps']) for row in rows),
                exact_expected_outputs=sum(row['extraction_matches'] and row['gap_matches'] for row in rows),
                manifest_edges=[list(pair) for pair in actual_edges],
                manifest_matches=actual_edges == expected_edges,
                multihop_path_length=len(paths['retail-offers']),
                not_automated=['business meaning', 'accepted semantic changes', 'owner confirmation',
                               'JSON path schema', 'dynamic SQL', 'unregistered consumer completeness'],
                limitations=['Small author-labelled fixtures, not an independent benchmark.',
                             'Unresolved SQL compilation yields no resolved edges, not zero dependencies.',
                             'SQLite compilation support is not PostgreSQL dialect support.',
                             'The manifest fixture exercises consumed v12 fields, not full schema validation or dbt runtime.'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in ('sql_cases', 'exact_expected_outputs', 'manifest_matches')}))
    raise SystemExit(0 if result['exact_expected_outputs'] == result['sql_cases'] and result['manifest_matches'] else 1)
