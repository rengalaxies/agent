"""Independent equal-information predicate baseline, not an installed dbt/Pact test.

Does not call V2, validators, or interpreter. Measures decision equivalence under
the existing typed language, not real-world correctness or maintenance costs.
"""
from .models import Scenario, Decision


def consumer_test_decision(scenario: Scenario) -> Decision:
    old = scenario.old_contract.model_dump()
    new = scenario.new_contract.model_dump()
    semantic = new['semantic']
    results = []
    for name, datatype in old['schema_fields'].items():
        results.append(new['schema_fields'].get(name) == datatype)

    def migration(dimension, source, target):
        return any(m.dimension == dimension and m.source == source and m.target == target
                   and m.validated_examples > 0 and (dimension != 'identity_scope' or m.bijective)
                   for m in scenario.migrations)

    for requirement in scenario.obligations:
        r = requirement.model_dump()
        predicates = []
        for required, actual in [('required_meaning', 'meaning'), ('required_formula', 'formula')]:
            if r[required] is not None:
                predicates.append(r[required] == semantic[actual])
        if r['accepted_units']:
            pairs = [(unit, scale) for unit in r['accepted_units']
                     for scale in (r['accepted_scales'] or [semantic['scale']])]
            predicates.append(any((unit == semantic['unit'] and scale == semantic['scale'])
                                  or migration('unit_scale', f"{semantic['unit']}:{semantic['scale']}",
                                               f'{unit}:{scale}') for unit, scale in pairs))
        if r['min_window_days'] is not None:
            actual = semantic['calculation_window_days']
            predicates.append(None if actual is None else actual >= r['min_window_days'])
        if r['accepted_identity_scopes']:
            predicates.append(any(scope == semantic['identity_scope']
                                  or migration('identity_scope', semantic['identity_scope'], scope)
                                  for scope in r['accepted_identity_scopes']))
        if r['allowed_sources']:
            predicates.append(all(source in r['allowed_sources'] for source in semantic['allowed_sources']))
        if r['required_purposes']:
            predicates.append(all(purpose in semantic['purposes'] for purpose in r['required_purposes']))
        results.extend(predicates or [None])
    if False in results:
        return Decision.REJECT
    if None in results:
        return Decision.NEEDS_REVIEW
    return Decision.ACCEPT
