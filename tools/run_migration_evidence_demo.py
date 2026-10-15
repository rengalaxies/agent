"""Reproduce declaration-only V2 vs executable fixture evidence on development U-02."""
import json
from pathlib import Path
import yaml
from datamesh_release_protocol.migration_evidence import run_with_migration_evidence
from datamesh_release_protocol.models import Scenario, BaselinePolicy

root = Path(__file__).resolve().parents[1]
scenario = Scenario.model_validate(yaml.safe_load((root / 'scenarios/development/U-02.yaml').read_text()))
policy = BaselinePolicy.model_validate(yaml.safe_load((root / 'policies/v1-ind.yaml').read_text()))
cases = []
for label, expression, fixtures in [
    ('correct', 'value / 100', [{'input': '123', 'expected': '1.23'}, {'input': '-50', 'expected': '-0.5'}]),
    ('wrong_but_declared_valid', 'value * 100', [{'input': '123', 'expected': '1.23'}]),
    ('unsupported_expression', 'WRONG', [{'input': '123', 'expected': '1.23'}]),
    ('missing_examples', 'value / 100', []),
    ('weak_zero_only_fixture', 'value * 100', [{'input': '0', 'expected': '0'}]),
]:
    candidate = scenario.model_copy(deep=True)
    candidate.migrations[0].expression = expression
    cases.append(dict(case=label, **run_with_migration_evidence(candidate, policy, [fixtures], 'demo')))
print(json.dumps(dict(kind='development-diagnostic-not-accuracy', cases=cases), ensure_ascii=False, indent=2))
