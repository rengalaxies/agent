import unittest
from decimal import Decimal

from change_completion.comparison import Column, Table, compare_tables, MAX_ROWS


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


if __name__ == "__main__":
    unittest.main()
