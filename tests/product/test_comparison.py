import unittest
from time import perf_counter
from unittest.mock import patch
from decimal import Decimal

from change_completion.comparison import Column, Table, compare_tables, MAX_ROWS
import change_completion.comparison as comparator


def table(kind, values, **policy):
    return Table([Column("value", kind, **policy)], [[v] for v in values])


class ComparisonTests(unittest.TestCase):
    def test_strict_numeric_schema(self):
        self.assertEqual(compare_tables(table("int", [1]), table("float", [1.0])).status, "FAIL")
        self.assertEqual(compare_tables(table("int", [1]), table("float", [1.0]), numeric_equivalence=True).status, "PASS")

    def test_no_float_precision_loss(self):
        n = 2 ** 53 + 1
        self.assertEqual(compare_tables(table("int", [n]), table("float", [float(n)]), numeric_equivalence=True).status, "FAIL")
        self.assertEqual(compare_tables(table("decimal", [Decimal("0.1")]), table("float", [0.1]), numeric_equivalence=True).status, "FAIL")
        self.assertEqual(compare_tables(table("decimal", [Decimal("0.5")]), table("float", [0.5]), numeric_equivalence=True).status, "PASS")

    def test_decimal_exact_even_outside_context_precision(self):
        a = Decimal("123456789012345678901234567890.01")
        b = Decimal("123456789012345678901234567890.02")
        self.assertEqual(compare_tables(table("decimal", [a]), table("decimal", [b])).status, "FAIL")

    def test_bool_is_not_int(self):
        self.assertEqual(compare_tables(table("int", [1]), table("int", [True])).status, "FAIL")
        self.assertEqual(compare_tables(table("bool", [True]), table("int", [1]), numeric_equivalence=True).status, "FAIL")

    def test_multiset_and_order(self):
        a = table("int", [1, 1, 2])
        self.assertEqual(compare_tables(a, table("int", [2, 1, 1])).status, "PASS")
        self.assertEqual(compare_tables(a, table("int", [2, 1, 1]), ordered=True).status, "FAIL")
        self.assertEqual(compare_tables(a, table("int", [1, 2, 2])).status, "FAIL")
        self.assertEqual(compare_tables(a, table("int", [1, 2])).status, "FAIL")

    def test_null_is_not_zero_or_empty(self):
        self.assertEqual(compare_tables(table("int", [None]), table("int", [0])).status, "FAIL")
        self.assertEqual(compare_tables(table("str", [None]), table("str", [""])).status, "FAIL")
        self.assertEqual(compare_tables(table("int", [None]), table("int", [None])).status, "PASS")
        self.assertEqual(compare_tables(table("int", [1], nullable=False), table("int", [None], nullable=False)).status, "FAIL")

    def test_expected_only_controls_tolerance(self):
        self.assertEqual(compare_tables(table("int", [10]), table("int", [12], abs_tol=100)).status, "FAIL")
        self.assertEqual(compare_tables(table("int", [10], abs_tol=2), table("int", [12])).status, "PASS")

    def test_non_greedy_matching(self):
        # First expected row can take either actual; second can take only 0.
        self.assertEqual(compare_tables(table("int", [1, 0], abs_tol=1), table("int", [0, 2])).status, "PASS")

    def test_relative_tolerance_is_expected_relative(self):
        self.assertEqual(compare_tables(table("int", [100], rel_tol=Decimal("0.1")), table("int", [110])).status, "PASS")
        self.assertEqual(compare_tables(table("int", [100], rel_tol=Decimal("0.1")), table("int", [111])).status, "FAIL")

    def test_nonfinite_values_and_policy(self):
        for value in [float("nan"), float("inf"), -float("inf")]:
            with self.subTest(value=value):
                self.assertEqual(compare_tables(table("float", [value]), table("float", [1.0])).status, "STOP")
                self.assertEqual(compare_tables(table("float", [1.0]), table("float", [value])).status, "FAIL")
        self.assertEqual(compare_tables(table("decimal", [Decimal("sNaN")]), table("decimal", [Decimal(1)])).status, "STOP")
        self.assertEqual(compare_tables(table("int", [1], abs_tol=-1), table("int", [1])).status, "STOP")

    def test_invalid_shapes_and_options_fail_closed(self):
        valid = table("int", [1])
        for invalid in [None, Table([], []), Table([Column("x", "unknown")], []), Table([Column("x", "int")], [[1, 2]]), Table([Column("x", "int")], [[True]])]:
            with self.subTest(invalid=invalid):
                self.assertEqual(compare_tables(invalid, valid).status, "STOP")
                self.assertEqual(compare_tables(valid, invalid).status, "FAIL")
        self.assertEqual(compare_tables(valid, valid, ordered=1).status, "STOP")

    def test_bounded_and_empty(self):
        self.assertEqual(compare_tables(table("int", []), table("int", [])).status, "PASS")
        self.assertEqual(compare_tables(table("int", [1]), table("int", [1] * (MAX_ROWS + 1))).status, "STOP")

    def test_schema_corruption_and_names(self):
        valid = table("int", [1])
        for columns in [[Column("x", "int"), Column("x", "int")],
                        [Column("x", "int", nullable="yes")],
                        [Column("x", "str", abs_tol=1)],
                        [Column("x", "int", abs_tol=True)], [None]]:
            actual = Table(columns, [])
            self.assertEqual(compare_tables(valid, actual).status, "FAIL")
        self.assertEqual(compare_tables(valid, Table([Column("other", "int")], [[1]])).status, "FAIL")

    def test_extreme_values_stop_before_rational_allocation(self):
        valid = table("decimal", [Decimal(1)])
        for value in [Decimal("1e999999999"), Decimal("1e-999999999"),
                      Decimal("9" * 1001)]:
            actual = table("decimal", [value])
            self.assertEqual(compare_tables(valid, actual).reason_codes,
                             ("ACTUAL_NUMERIC_LIMIT",))
            self.assertEqual(compare_tables(actual, valid).status, "STOP")
        self.assertEqual(compare_tables(table("int", [1]), table("int", [10 ** 1000])).status, "STOP")
        self.assertEqual(compare_tables(table("str", [""]), table("str", ["x" * 16385])).reason_codes,
                         ("ACTUAL_TEXT_LIMIT",))
        huge_tolerance = table("int", [1], abs_tol=Decimal("1e999999999"))
        self.assertEqual(compare_tables(huge_tolerance, table("int", [1])).reason_codes,
                         ("EXPECTED_TOLERANCE_LIMIT",))

    def test_large_exact_multiset_keeps_precision_and_finishes_quickly(self):
        columns = [Column(str(i), "decimal") for i in range(128)]
        rows = [[Decimal(i * 1000 + j) / 100 for j in range(128)]
                for i in range(200)]
        expected = Table(columns, rows)
        actual = Table(columns, list(reversed(rows)))
        started = perf_counter()
        self.assertEqual(compare_tables(expected, actual).status, "PASS")
        # Deliberately generous regression boundary, old implementation >80 s.
        self.assertLess(perf_counter() - started, 5.0)
        changed = [list(row) for row in actual.rows]
        changed[-1][-1] += Decimal("0.00000000000001")
        self.assertEqual(compare_tables(expected, Table(columns, changed)).status, "FAIL")

    def test_wide_tolerant_job_stops_before_pairwise_matching(self):
        columns = [Column(str(i), "int", abs_tol=1) for i in range(128)]
        rows = [[i for _ in range(128)] for i in range(200)]
        changed = [[i + 1 for _ in range(128)] for i in range(200)]
        self.assertEqual(compare_tables(Table(columns, rows), Table(columns, changed)),
                         comparator.Comparison("STOP", ("COMPARISON_WORK_LIMIT",)))
        # Exact equality remains cheap even under a permissive contract.
        self.assertEqual(compare_tables(Table(columns, rows),
                                        Table(columns, list(reversed(rows)))).status, "PASS")

    def test_matching_search_budget_stops_dense_ambiguity(self):
        expected = table("int", list(range(200)), abs_tol=10000)
        actual = table("int", list(range(1000, 1200)))
        self.assertEqual(compare_tables(expected, actual).reason_codes,
                         ("COMPARISON_WORK_LIMIT",))

    def test_numbers_are_not_reparsed_for_each_candidate(self):
        expected = table("decimal", [Decimal(i) for i in range(40)], abs_tol=Decimal("0.1"))
        actual = table("decimal", [Decimal(i) + Decimal("0.05") for i in range(40)])
        with patch.object(comparator, "_number", wraps=comparator._number) as number:
            self.assertEqual(compare_tables(expected, actual).status, "PASS")
            self.assertLess(number.call_count, 200)

    def test_large_numeric_approximation_charges_bit_complexity(self):
        expected = table("int", [10 ** 900 + i for i in range(200)], abs_tol=1)
        actual = table("int", [10 ** 900 + i + 1 for i in range(200)])
        self.assertEqual(compare_tables(expected, actual).reason_codes,
                         ("COMPARISON_WORK_LIMIT",))

    def test_ordered_tolerance_avoids_quadratic_cost(self):
        columns = [Column(str(i), "int", abs_tol=1) for i in range(128)]
        expected = Table(columns, [[i] * 128 for i in range(200)])
        actual = Table(columns, [[i + 1] * 128 for i in range(200)])
        self.assertEqual(compare_tables(expected, actual, ordered=True).status, "PASS")


if __name__ == "__main__":
    unittest.main()
