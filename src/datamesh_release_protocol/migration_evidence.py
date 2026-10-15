"""Opt-in executable fixture evidence; separate from the frozen V2 protocol.

Only finite Decimal arithmetic over `value` and numeric constants is supported.
Never evaluates Python code. Passing fixtures is not a proof for unseen inputs.
"""
from __future__ import annotations

import ast
from decimal import Decimal, DecimalException, localcontext
from hashlib import sha256
import json
from pathlib import Path

from .models import Migration, Scenario, Decision, BaselinePolicy, ValidationMode
from .engine import ReleaseEngine

VERSION = 'migration-fixtures-1'
VERIFIER_SHA256 = sha256(Path(__file__).read_bytes()).hexdigest()


def _hash(payload):
    return sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _number(raw):
    if not isinstance(raw, str) or len(raw) > 64:
        raise ValueError('numbers must be decimal strings of at most 64 characters')
    number = Decimal(raw)
    if not number.is_finite() or abs(number) > Decimal('1e18'):
        raise ValueError('nonfinite or out-of-range number')
    return number


def _parse(expression):
    if len(expression) > 256:
        raise ValueError('expression too long')
    tree = ast.parse(expression, mode='eval')
    nodes = list(ast.walk(tree))
    if len(nodes) > 32:
        raise ValueError('expression too complex')
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Name, ast.Load,
               ast.Constant, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.UAdd, ast.USub)
    for node in nodes:
        if not isinstance(node, allowed):
            raise ValueError('unsupported expression syntax')
        if isinstance(node, ast.Name) and node.id != 'value':
            raise ValueError('only value may be referenced')
        if isinstance(node, ast.Constant):
            if type(node.value) not in (int, float):
                raise ValueError('only numeric constants are allowed')
            _number(ast.get_source_segment(expression, node))
    return tree.body


def _execute(node, expression, value):
    if isinstance(node, ast.Name):
        return value
    if isinstance(node, ast.Constant):
        return _number(ast.get_source_segment(expression, node))
    if isinstance(node, ast.UnaryOp):
        result = _execute(node.operand, expression, value)
        return -result if isinstance(node.op, ast.USub) else result
    left = _execute(node.left, expression, value)
    right = _execute(node.right, expression, value)
    if isinstance(node.op, ast.Add):
        result = left + right
    elif isinstance(node.op, ast.Sub):
        result = left - right
    elif isinstance(node.op, ast.Mult):
        result = left * right
    else:
        result = left / right
    if not result.is_finite() or abs(result) > Decimal('1e18'):
        raise ValueError('arithmetic result out of range')
    return result


def verify_migration(migration: Migration, fixtures: list[dict[str, str]]) -> dict:
    """Recompute evidence every call; a caller-supplied `passed` flag is never read.

    `validated_examples` stays a legacy declaration and cannot replace fixtures.
    Identity mapping and external functions require another versioned verifier.
    """
    if not isinstance(fixtures, list):
        raise ValueError('fixtures must be a list')
    if len(fixtures) > 256:
        raise ValueError('at most 256 fixtures')
    for row in fixtures:
        if not isinstance(row, dict) or set(row) != {'input', 'expected'}:
            raise ValueError('fixture must contain input and expected only')
        if any(not isinstance(v, str) or len(v) > 64 for v in row.values()):
            raise ValueError('fixture values must be bounded decimal strings')
    payload = dict(verifier=VERSION, verifier_sha256=VERIFIER_SHA256,
                   migration=migration.model_dump(mode='json'), fixtures=fixtures)
    rows = []
    decision, reason = Decision.NEEDS_REVIEW, 'NO_EXECUTABLE_FIXTURES'
    try:
        if migration.dimension != 'unit_scale':
            reason = 'UNSUPPORTED_DIMENSION'
        elif not fixtures:
            pass
        else:
            tree = _parse(migration.expression)
            with localcontext() as context:
                context.prec = 50
                for fixture in fixtures:
                    actual = _execute(tree, migration.expression, _number(fixture['input']))
                    expected = _number(fixture['expected'])
                    rows.append(dict(**fixture, actual=str(actual), passed=actual == expected))
            decision = Decision.ACCEPT if all(r['passed'] for r in rows) else Decision.REJECT
            reason = 'FIXTURES_PASSED' if decision == Decision.ACCEPT else 'FIXTURE_MISMATCH'
    except (ValueError, SyntaxError, DecimalException, OverflowError):
        decision, reason = Decision.NEEDS_REVIEW, 'UNEXECUTABLE_OR_INVALID_ARITHMETIC'
    result = dict(**payload, input_hash=_hash(payload), decision=decision.value,
                  reason=reason, results=rows, guarantee='listed fixtures only')
    return {**result, 'receipt_hash': _hash(result)}


def run_with_migration_evidence(scenario: Scenario, policy: BaselinePolicy,
                                fixture_sets: list[list[dict[str, str]]], run_id: str) -> dict:
    """Advisory gate: verify every listed migration in order, even unused ones.

    The existing V2 decision is preserved separately. This does not authorize a
    KnowledgeStore commit and does not change the deployed protocol's semantics.
    """
    if len(fixture_sets) != len(scenario.migrations):
        raise ValueError('exactly one fixture set per migration required')
    release = ReleaseEngine(policy).run(scenario, ValidationMode.V2, run_id)
    receipts = [verify_migration(m, f) for m, f in zip(scenario.migrations, fixture_sets)]
    decisions = {release.decision.value, *(r['decision'] for r in receipts)}
    decision = ('REJECT' if 'REJECT' in decisions else
                'NEEDS_REVIEW' if 'NEEDS_REVIEW' in decisions else 'ACCEPT')
    payload = dict(policy=VERSION, scenario_snapshot_id=release.proposal.snapshot_id,
                   legacy_v2_decision=release.decision.value, decision=decision,
                   receipts=receipts, release_authorization=False)
    return {**payload, 'evidence_bundle_hash': _hash(payload)}
