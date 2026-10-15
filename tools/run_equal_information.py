"""Diagnostic comparison; never reads evaluation fixtures or scoring oracles."""
import json
from pathlib import Path
from hashlib import sha256
import yaml
from itertools import product
from datamesh_release_protocol.consumer_test_baseline import consumer_test_decision
from datamesh_release_protocol.engine import ReleaseEngine
from datamesh_release_protocol.models import BaselinePolicy, Scenario, ValidationMode


def run(root):
    policy = BaselinePolicy.model_validate(yaml.safe_load((root / 'policies/v1-ind.yaml').read_text()))
    engine = ReleaseEngine(policy)
    rows = []
    for path in sorted((root / 'scenarios/development').glob('*.yaml')):
        scenario = Scenario.model_validate(yaml.safe_load(path.read_text()))
        # No family-specific changes or holdout access. Both receive the full
        # same typed requirements and migrations. Labels are not inputs.
        cases = [(scenario.scenario_id, scenario)]
        for i, (window, meaning_changed, extra_source) in enumerate(product(
                [None, 1, 60], [False, True], [False, True])):
            variant = scenario.model_copy(deep=True)
            variant.new_contract.semantic.calculation_window_days = window
            if meaning_changed:
                variant.new_contract.semantic.meaning += ':diagnostic-change'
            if extra_source:
                variant.new_contract.semantic.allowed_sources.append('diagnostic-source')
            cases.append((f'{scenario.scenario_id}:perturbation:{i}', variant))
        for identifier, case in cases:
            v2 = engine.run(case, ValidationMode.V2, 'equal-information').decision.value
            baseline = consumer_test_decision(case).value
            normalized = json.dumps(case.model_dump(mode='json'), sort_keys=True, ensure_ascii=False)
            rows.append(dict(id=identifier, input_sha256=sha256(normalized.encode()).hexdigest(),
                             v2=v2, consumer_tests=baseline, agreement=v2 == baseline))
    return dict(kind='diagnostic-conformance-not-accuracy', cases=len(rows),
                agreements=sum(r['agreement'] for r in rows), rows=rows,
                llm_comparison='NOT_RUN: no configured reproducible inference endpoint',
                limitations=['Same author and typed language; not an independent correctness oracle.',
                             'No real SQL/data execution, Pact/dbt integration, cost or business validation.',
                             'Development cases only; confirmatory evaluation unchanged.'])


if __name__ == '__main__':
    result = run(Path(__file__).resolve().parents[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['cases'] and result['cases'] == result['agreements'] else 1)
