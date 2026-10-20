"""Advisory PR analysis: explicit metadata, observed impacts and runnable repair.

No GitHub comments, deployments, approvals or release authorizations are issued.
"""
from collections import defaultdict
from datetime import datetime
import difflib
import sqlite3

from .consumer_test_baseline import consumer_test_decision
from .dependency_import import impact_paths, memory_schema, readonly_authorizer
from .engine import ReleaseEngine
from .knowledge import digest, canonical, utc
from .models import ValidationMode


def execute_fixture(sql, schemas, tables):
    """Run SELECT in an isolated SQLite DB with supplied fixtures and work limits."""
    if len(sql) > 100000 or sum(len(rows) for rows in tables.values()) > 1000:
        raise ValueError('fixture/query size limit exceeded')
    connection = memory_schema(schemas)
    try:
        for table, rows in tables.items():
            if table not in schemas:
                raise ValueError('fixture table missing from schema')
            fields = list(schemas[table])
            for row in rows:
                if set(row) != set(fields):
                    raise ValueError('fixture row/schema mismatch')
                if any(type(v) not in (str, int, float, bool, type(None)) for v in row.values()):
                    raise ValueError('only scalar fixture values are supported')
                if any(isinstance(v, str) and len(v) > 1024 for v in row.values()):
                    raise ValueError('fixture string too long')
            placeholders = ','.join('?' for _ in fields)
            columns = ','.join(f'"{field}"' for field in fields)
            connection.executemany(f'INSERT INTO "{table}" ({columns}) VALUES ({placeholders})',
                                   [tuple(row[field] for field in fields) for row in rows])
        connection.set_authorizer(readonly_authorizer(defaultdict(set)))
        work = [0]
        def progress():
            work[0] += 1
            return int(work[0] > 100)
        connection.set_progress_handler(progress, 1000)
        cursor = connection.execute(sql)
        if not cursor.description:
            raise ValueError('fixture query must return rows')
        rows = cursor.fetchmany(1001)
        if len(rows) > 1000:
            raise ValueError('fixture result limit exceeded')
        return dict(status='executed', columns=[c[0] for c in cursor.description],
                    rows=sorted([list(row) for row in rows], key=canonical),
                    input_hash=digest({'sql': sql, 'schemas': schemas, 'tables': tables}))
    except (sqlite3.Error, ValueError, OverflowError):
        return dict(status='needs_review', reason='unsupported_query_or_fixture')
    finally:
        connection.close()


def check_regression(sql, schemas, tables, expected):
    if not any(tables.values()):
        return dict(status='needs_review', reason='empty_input_fixture', decision='NEEDS_REVIEW')
    result = execute_fixture(sql, schemas, tables)
    if result['status'] != 'executed':
        return {**result, 'decision': 'NEEDS_REVIEW'}
    matches = result['columns'] == expected['columns'] and result['rows'] == sorted(expected['rows'], key=canonical)
    return {**result, 'decision': 'ACCEPT' if matches else 'REJECT',
            'guarantee': 'supplied SQLite fixture and expected rows only'}


def metadata_issues(scenario, artifacts, registration, states, at, *, strategy='graph'):
    at = utc(at)
    observations = [edge for artifact in artifacts for edge in artifact['observations']]
    retrieval = impact_paths(observations, scenario.new_contract.product_id, strategy=strategy)
    issues = [gap for artifact in artifacts for gap in artifact['gaps']]
    if not registration.get('complete') or not registration.get('evidence_ref'):
        issues.append('registered_boundary_unconfirmed')
    registered = set(registration.get('consumers', []))
    requirements = {o.consumer_id for o in scenario.obligations}
    if registered - requirements:
        issues.append('registered_consumer_missing_requirement')
    if requirements - registered:
        issues.append('requirement_consumer_outside_registered_boundary')
    for consumer in sorted(registered - set(retrieval['paths'])):
        issues.append('registered_consumption_not_observed:' + consumer)
    for consumer in sorted(set(retrieval['paths']) - requirements):
        # Intermediate transformations are not necessarily end consumers, but
        # require an explicit role/exemption rather than silent exclusion.
        if consumer not in registration.get('intermediate_nodes', []):
            issues.append('observed_consumer_missing_requirement:' + consumer)
    for obligation in scenario.obligations:
        state = states.get(obligation.obligation_id, {})
        if state.get('status') != 'confirmed' or not state.get('evidence_ref'):
            issues.append('requirement_unconfirmed:' + obligation.obligation_id)
        if state.get('version') != obligation.obligation_version or state.get('owner') != obligation.consumer_domain:
            issues.append('requirement_owner_or_version_mismatch:' + obligation.obligation_id)
        try:
            start = utc(datetime.fromisoformat(state['valid_from']))
            end = utc(datetime.fromisoformat(state['valid_until']))
            if not start <= at < end:
                issues.append('requirement_not_current:' + obligation.obligation_id)
        except (KeyError, ValueError, TypeError):
            issues.append('requirement_validity_unknown:' + obligation.obligation_id)
    return sorted(set(issues)), retrieval


def advisory_decision(typed_decision, issues):
    # A demonstrated violation is retained even when other evidence is missing.
    return 'REJECT' if typed_decision == 'REJECT' else ('NEEDS_REVIEW' if issues else typed_decision)


def analyze_change(scenario, policy, artifacts, registration, states, at, *, old_sql, new_sql,
                   schemas, tables, expected):
    issues, retrieval = metadata_issues(scenario, artifacts, registration, states, at)
    typed = ReleaseEngine(policy).run(scenario, ValidationMode.V2, 'pr-assistant')
    regression = check_regression(new_sql, schemas, tables, expected)
    signals = [typed.decision.value, regression['decision']]
    decision = advisory_decision('REJECT' if 'REJECT' in signals else
                                 'NEEDS_REVIEW' if 'NEEDS_REVIEW' in signals else 'ACCEPT', issues)
    changes = {key: dict(old=scenario.old_contract.semantic.model_dump()[key],
                         new=scenario.new_contract.semantic.model_dump()[key])
               for key in scenario.old_contract.semantic.model_dump()
               if scenario.old_contract.semantic.model_dump()[key] != scenario.new_contract.semantic.model_dump()[key]}
    artifact = None
    if decision == 'REJECT':
        compatible = scenario.model_copy(deep=True)
        compatible.new_contract = scenario.old_contract.model_copy(deep=True)
        compatible.new_contract.contract_version = scenario.new_contract.contract_version + '-compat.1'
        compatible.migrations = []
        repair_regression = check_regression(old_sql, schemas, tables, expected)
        repair_issues, _ = metadata_issues(compatible, artifacts, registration, states, at)
        repair_decision = advisory_decision(consumer_test_decision(compatible).value, repair_issues)
        repair_signals = {repair_decision, repair_regression['decision']}
        repair_decision = ('REJECT' if 'REJECT' in repair_signals else
                           'NEEDS_REVIEW' if 'NEEDS_REVIEW' in repair_signals else 'ACCEPT')
        artifact = dict(kind='side_by_side_compatibility_candidate',
                        contract=compatible.new_contract.model_dump(mode='json'), sql=old_sql,
                        regression_test=dict(schemas=schemas, tables=tables, expected=expected),
                        typed_recheck=repair_decision, regression_recheck=repair_regression,
                        applies_automatically=False,
                        remaining_work=['owner reviews semantic suitability',
                                        'route existing consumers to compatibility endpoint',
                                        'verify deployment SQL dialect and real data'])
    observations = [edge for item in artifacts for edge in item['observations']]
    inputs = dict(scenario=scenario.model_dump(mode='json'), artifacts=artifacts,
                  registration=registration, requirement_states=states, evaluated_at=utc(at).isoformat(),
                  old_sql=old_sql, new_sql=new_sql, schemas=schemas, tables=tables, expected=expected)
    payload = dict(format='pr-change-assistant-1', input_hash=digest(inputs), decision=decision,
                   mode='advisory', release_authorization=False, semantic_changes=changes,
                   diff=''.join(difflib.unified_diff(old_sql.splitlines(True), new_sql.splitlines(True),
                                                  fromfile='producer-before.sql', tofile='producer-after.sql')),
                   affected=[dict(consumer_id=o.consumer_id, owner=o.consumer_domain,
                                  obligation_id=o.obligation_id, path=retrieval['paths'].get(o.consumer_id),
                                  requirement_source=states.get(o.obligation_id, {}).get('evidence_ref'))
                             for o in scenario.obligations],
                   observed_edges=observations, gaps=issues, typed_reasons=typed.reason_codes,
                   regression=regression, proposed_artifact=artifact,
                   human_input_counts=dict(declared_requirements=len(states),
                                           supplied_expected_rows=len(expected['rows']),
                                           explicit_registration_boundaries=1),
                   limitation='observed code does not establish business meaning or complete coverage')
    return {**payload, 'report_hash': digest(payload)}
