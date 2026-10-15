"""Equal-input diagnostic; expected labels loaded only after mode decisions.

All modes get the same metadata, lineage, SQL and fixtures. Executable consumer
tests replace formula-string equality with supplied SQL output assertions; the
V2 assistant retains its frozen literal formula predicate. Neither is an oracle.
"""
import copy
from datetime import datetime
import json
from pathlib import Path

from run_pr_assistant import ROOT, load_example, artifacts, report
from datamesh_release_protocol.change_assistant import metadata_issues, check_regression, advisory_decision
from datamesh_release_protocol.consumer_test_baseline import consumer_test_decision
from datamesh_release_protocol.dependency_import import import_sql
from datamesh_release_protocol.knowledge import digest


def variant(name):
    data, scenario, policy = load_example()
    if name != 'unit_break':
        scenario.new_contract.semantic = scenario.old_contract.semantic.model_copy(deep=True)
        data['new_sql'] = data['old_sql']
    if name == 'cosmetic_formula':
        scenario.new_contract.semantic.formula = 'sum( purchase_amount )'
    elif name == 'missing_state':
        data['requirement_states'] = {}
    elif name in ('expired', 'owner_changed', 'candidate'):
        state = next(iter(data['requirement_states'].values()))
        state.update({'expired': {'valid_until': '2026-10-01T00:00:00+00:00'},
                      'owner_changed': {'owner': 'another-domain'},
                      'candidate': {'status': 'candidate'}}[name])
    elif name == 'boundary_unknown':
        data['registration']['complete'] = False
    elif name == 'dynamic':
        data['consumer_sql'] = "SELECT amount FROM {{ ref('spending') }}"
    elif name == 'orphan':
        data['manifest']['nodes']['model.demo.retail']['depends_on']['nodes'].append('model.absent')
    elif name == 'json':
        data['consumer_schemas']['spending_activity_profile']['payload'] = 'json'
        data['consumer_sql'] = "SELECT json_extract(payload, '$.amount') FROM spending_activity_profile"
    elif name == 'conflict':
        extra = scenario.obligations[0].model_copy(deep=True)
        extra.obligation_id, extra.consumer_id, extra.consumer_domain = 'finance-usd', 'finance-report', 'finance'
        extra.accepted_units = ['USD']
        scenario.obligations.append(extra)
        data['registration']['consumers'].append(extra.consumer_id)
        data['requirement_states'][extra.obligation_id] = {
            **next(iter(data['requirement_states'].values())), 'owner': 'finance'}
    elif name == 'missing_requirement':
        data['registration']['consumers'].append('accounting-without-contract')
    elif name == 'wrong_sql':
        data['new_sql'] = 'SELECT user_id, amount * 100 AS amount FROM transactions ORDER BY user_id;\n'
    elif name == 'unsupported_producer':
        data['new_sql'] = 'SELECT unsupported_udf(amount) FROM transactions;'
    return data, scenario, policy


def same_artifacts(data, name):
    result = artifacts(data)
    if name in ('unregistered', 'conflict'):
        consumer = 'shadow-consumer' if name == 'unregistered' else 'finance-report'
        result.append(import_sql('SELECT amount FROM spending_activity_profile', consumer,
                                 data['consumer_schemas'], data['source_ref']))
    return result


def execute_modes(data, scenario, policy, imported):
    at = datetime.fromisoformat(data['evaluated_at'])
    execution = check_regression(data['new_sql'], data['schemas'], data['tables'], data['expected'])
    test_scenario = scenario.model_copy(deep=True)
    # Explicit capability difference: executable fixtures replace the symbolic
    # formula predicate. All other typed requirements remain in the baseline.
    for obligation in test_scenario.obligations:
        obligation.required_formula = None
    predicate = consumer_test_decision(test_scenario).value
    signals = {predicate, execution['decision']}
    baseline = 'REJECT' if 'REJECT' in signals else ('NEEDS_REVIEW' if 'NEEDS_REVIEW' in signals else 'ACCEPT')
    modes = {}
    traversals = {}
    for mode, strategy in [('consumer_tests_scan', 'flat'), ('consumer_tests_catalog', 'graph')]:
        issues, traversal = metadata_issues(scenario, imported, data['registration'],
                                           data['requirement_states'], at, strategy=strategy)
        modes[mode] = advisory_decision(baseline, issues)
        traversals[mode] = traversal
    # Run V2 on exactly these artifacts, including additional observed consumers.
    from datamesh_release_protocol.change_assistant import analyze_change
    assistant = analyze_change(scenario, policy, imported, data['registration'], data['requirement_states'], at,
                               old_sql=data['old_sql'], new_sql=data['new_sql'], schemas=data['schemas'],
                               tables=data['tables'], expected=data['expected'])
    modes['v2_graph_assistant'] = assistant['decision']
    return modes, traversals, assistant


def compare():
    catalog_path = ROOT / 'examples/pr-assistant/catalog.json'
    catalog = json.loads(catalog_path.read_text())
    rows = []
    summaries = {mode: dict(correct=0, false_rejects=0, unsafe_accepts=0, review=0)
                 for mode in ('consumer_tests_scan', 'consumer_tests_catalog', 'v2_graph_assistant')}
    for definition in catalog['cases']:
        data, scenario, policy = variant(definition['variant'])
        imported = same_artifacts(data, definition['variant'])
        decisions, traversals, assistant = execute_modes(data, scenario, policy, imported)
        # Scoring-only data is not passed to the mode implementations.
        expected = definition['expected']
        for mode, decision in decisions.items():
            summaries[mode]['correct'] += int(decision == expected)
            summaries[mode]['false_rejects'] += int(decision == 'REJECT' and expected == 'ACCEPT')
            summaries[mode]['unsafe_accepts'] += int(decision == 'ACCEPT' and expected != 'ACCEPT')
            summaries[mode]['review'] += int(decision == 'NEEDS_REVIEW')
        flat = traversals['consumer_tests_scan']
        graph = traversals['consumer_tests_catalog']
        rows.append(dict(id=definition['id'], expected=expected, rationale=definition['rationale'],
                         input_hash=digest({'data': data, 'scenario': scenario.model_dump(mode='json'),
                                            'artifacts': imported}), decisions=decisions,
                         retrieval_equal=flat['paths'] == graph['paths'],
                         scan_edge_inspections=flat['edge_inspections'],
                         graph_edge_inspections=graph['edge_inspections'],
                         graph_index_build_edges=graph['index_build_edges'],
                         gaps=assistant['gaps'], human_input_counts=assistant['human_input_counts'],
                         proposed_artifact=assistant['proposed_artifact'] is not None))
    # Separate negative/positive provenance and stale-owner remediation costs.
    return dict(kind='diagnostic-not-confirmatory-or-business-validation', cases=len(rows),
                catalog_hash=digest(catalog), summaries=summaries, rows=rows,
                retrieval_parity=all(r['retrieval_equal'] for r in rows),
                ownership_maintenance_tasks={
                    'missing-confirmation': ['locate requirement source', 'obtain owner confirmation'],
                    'expired-confirmation': ['revalidate requirement', 'renew validity evidence'],
                    'owner-mismatch': ['verify current accountable domain', 'update versioned evidence'],
                    'undocumented-consumer': ['identify owner', 'register usage', 'supply requirement']},
                cost_limits=['Human task counts are inventory, not measured person-minutes or business cost.',
                             'Traversal counts omit runtime and index memory; no latency claim.',
                             'Fixtures and expected outputs are supplied, not inferred from code.',
                             'Same author labels and implementations; no independent expert validation.'],
                llm_comparison='NOT_RUN: no configured reproducible inference endpoint')


if __name__ == '__main__':
    parser = __import__('argparse').ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = compare()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'cases': result['cases'], 'summaries': result['summaries'],
                      'retrieval_parity': result['retrieval_parity']}))
