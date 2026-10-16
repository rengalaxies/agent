"""Bounded, deterministic comparison of materialized result tables.

No execution is performed here. Decimal and binary floats are converted to
exact rational numbers, so an opt-in numeric equivalence cannot round away a
difference. Tolerances belong exclusively to the expected contract.
Dataclasses are transport objects; constructors do not validate. The comparison
entry point validates both sides before examining values.
"""

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
import math
from typing import Sequence


MAX_ROWS = 200
MAX_COLUMNS = 128
MAX_NUMERIC_DIGITS = 1000
MAX_DECIMAL_EXPONENT = 1000
MAX_TEXT_LENGTH = 16_384
_KINDS = {"int", "float", "decimal", "str", "bool"}
_NUMERIC = {"int", "float", "decimal"}


class _ValueLimit(ValueError):
    pass


@dataclass(frozen=True)
class Column:
    name: str
    kind: str
    nullable: bool = True
    abs_tol: int | float | Decimal = 0
    rel_tol: int | float | Decimal = 0


@dataclass(frozen=True)
class Table:
    columns: Sequence[Column]
    rows: Sequence[Sequence[object]]


@dataclass(frozen=True)
class Comparison:
    status: str
    reason_codes: tuple[str, ...]


def _number(value: object) -> Fraction:
    if type(value) is int:
        # bit_length is bounded-cost even for an already allocated huge int.
        if value.bit_length() > 3322 or abs(value) >= 10 ** MAX_NUMERIC_DIGITS:
            raise _ValueLimit("numeric digit limit")
        return Fraction(value)
    if type(value) is float and math.isfinite(value):
        return Fraction.from_float(value)
    if type(value) is Decimal and value.is_finite():
        parts = value.as_tuple()
        if (len(parts.digits) > MAX_NUMERIC_DIGITS
                or abs(parts.exponent) > MAX_DECIMAL_EXPONENT
                or value.adjusted() >= MAX_NUMERIC_DIGITS):
            raise _ValueLimit("decimal precision/exponent limit")
        return Fraction(value)
    raise ValueError("invalid finite number")


def _validate(table: object) -> str | None:
    if type(table) is not Table:
        return "INVALID_TABLE"
    if type(table.columns) not in (tuple, list) or not table.columns:
        return "INVALID_SCHEMA"
    if len(table.columns) > MAX_COLUMNS:
        return "COLUMN_LIMIT"
    names = set()
    for column in table.columns:
        if type(column) is not Column:
            return "INVALID_SCHEMA"
        if (type(column.name) is not str or not column.name
                or column.name in names or type(column.kind) is not str
                or column.kind not in _KINDS or type(column.nullable) is not bool):
            return "INVALID_SCHEMA"
        names.add(column.name)
        try:
            absolute, relative = _number(column.abs_tol), _number(column.rel_tol)
        except _ValueLimit:
            return "TOLERANCE_LIMIT"
        except (ValueError, TypeError, OverflowError):
            return "INVALID_TOLERANCE"
        if absolute < 0 or relative < 0:
            return "INVALID_TOLERANCE"
        if column.kind not in _NUMERIC and (absolute or relative):
            return "INVALID_TOLERANCE"
    if type(table.rows) not in (tuple, list):
        return "INVALID_ROWS"
    if len(table.rows) > MAX_ROWS:
        return "ROW_LIMIT"
    types = {"int": int, "float": float, "decimal": Decimal,
             "str": str, "bool": bool}
    for row in table.rows:
        if type(row) not in (tuple, list) or len(row) != len(table.columns):
            return "ROW_SHAPE"
        for column, value in zip(table.columns, row):
            if value is None:
                if not column.nullable:
                    return "NULL_NOT_ALLOWED"
            elif type(value) is not types[column.kind]:
                return "VALUE_TYPE"
            elif column.kind == "str" and len(value) > MAX_TEXT_LENGTH:
                return "TEXT_LIMIT"
            elif column.kind in _NUMERIC:
                try:
                    _number(value)
                except _ValueLimit:
                    return "NUMERIC_LIMIT"
                except (ValueError, TypeError, OverflowError):
                    return "NONFINITE_NUMBER"
    return None


def compare_tables(expected: Table, actual: Table, *, ordered: bool = False,
                   numeric_equivalence: bool = False) -> Comparison:
    """Compare schema and rows; unsupported/invalid expectations stop evaluation.

    At most 200 rows, 128 columns, 1000 numeric digits, Decimal exponent
    magnitude 1000 and 16384 characters per text cell are accepted. Unordered
    comparison uses a perfect bipartite matching, preserving multiplicity even
    when tolerance intervals overlap. Relative tolerance uses expected values.
    """
    if type(ordered) is not bool or type(numeric_equivalence) is not bool:
        return Comparison("STOP", ("INVALID_OPTIONS",))
    error = _validate(expected)
    if error:
        return Comparison("STOP", ("EXPECTED_" + error,))
    error = _validate(actual)
    if error:
        status = "STOP" if error.endswith("_LIMIT") else "FAIL"
        return Comparison(status, ("ACTUAL_" + error,))
    if len(expected.columns) != len(actual.columns):
        return Comparison("FAIL", ("SCHEMA_MISMATCH",))
    for left, right in zip(expected.columns, actual.columns):
        if (left.name != right.name or left.nullable != right.nullable
                or (left.kind != right.kind and not (
                    numeric_equivalence and left.kind in _NUMERIC
                    and right.kind in _NUMERIC))):
            return Comparison("FAIL", ("SCHEMA_MISMATCH",))
    if len(expected.rows) != len(actual.rows):
        return Comparison("FAIL", ("ROW_COUNT_MISMATCH",))

    def matches(left: Sequence[object], right: Sequence[object]) -> bool:
        for column, a, b in zip(expected.columns, left, right):
            if a is None or b is None:
                if a is not None or b is not None:
                    return False
            elif column.kind in _NUMERIC:
                x, y = _number(a), _number(b)
                tolerance = max(_number(column.abs_tol),
                                _number(column.rel_tol) * abs(x))
                if abs(x - y) > tolerance:
                    return False
            elif type(a) is not type(b) or a != b:
                return False
        return True

    if ordered:
        passed = all(matches(a, b) for a, b in zip(expected.rows, actual.rows))
    else:
        edges = [[j for j, row in enumerate(actual.rows) if matches(wanted, row)]
                 for wanted in expected.rows]
        assigned: dict[int, int] = {}

        def augment(i: int, seen: set[int]) -> bool:
            for j in edges[i]:
                if j in seen:
                    continue
                seen.add(j)
                if j not in assigned or augment(assigned[j], seen):
                    assigned[j] = i
                    return True
            return False

        passed = all(augment(i, set()) for i in range(len(expected.rows)))
    return Comparison("PASS" if passed else "FAIL",
                      () if passed else ("ROW_VALUES_MISMATCH",))
