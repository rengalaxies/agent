"""Real SQLite mutations against manually authored independent expectations.

SQLite is used only for test-owned SQL here, not offered as a candidate sandbox.
"""
from decimal import Decimal
import sqlite3
import unittest

from change_completion.comparison import Column, Table, compare_tables


def observed(sql):
    with sqlite3.connect(":memory:") as db:
        cursor = db.execute(sql)
        rows = cursor.fetchall()
        types = {int: "int", float: "float", str: "str", bool: "bool"}
        columns = [Column(item[0], types[type(value)]) for item, value in zip(cursor.description, rows[0])]
        return Table(columns, rows)


class VerifierRegressionTest(unittest.TestCase):
    def test_cast_integer_as_real_is_contract_dependent(self):
        expected = Table([Column("value", "int")], [[1]])
        actual = observed("SELECT CAST(1 AS REAL) AS value")
        self.assertEqual(compare_tables(expected, actual).status, "FAIL")
        self.assertEqual(compare_tables(expected, actual, numeric_equivalence=True).status, "PASS")

    def test_big_integer_precision_loss_is_not_equivalence(self):
        expected = Table([Column("value", "int")], [[9007199254740993]])
        actual = observed("SELECT CAST(9007199254740993 AS REAL) AS value")
        self.assertEqual(compare_tables(expected, actual, numeric_equivalence=True).status, "FAIL")

    def test_duplicate_union_is_not_same_result(self):
        expected = Table([Column("value", "int")], [[1]])
        self.assertEqual(compare_tables(expected, observed("SELECT 1 AS value UNION ALL SELECT 1")).status, "FAIL")

    def test_unseen_case_branch_is_rejected(self):
        expected = Table([Column("value", "int")], [[10], [20]])
        actual = observed("WITH src(kind) AS (VALUES('a'),('b')) SELECT CASE WHEN kind='a' THEN 10 ELSE 0 END AS value FROM src")
        self.assertEqual(compare_tables(expected, actual).status, "FAIL")

    def test_equal_grand_total_does_not_hide_wrong_customer_rows(self):
        expected = Table([Column("customer", "str"), Column("amount", "int")], [["alice", 10], ["bob", 20]])
        actual = observed("SELECT 'alice' AS customer,20 AS amount UNION ALL SELECT 'bob',10")
        self.assertEqual(sum(r[1] for r in expected.rows), sum(r[1] for r in actual.rows))
        self.assertEqual(compare_tables(expected, actual).status, "FAIL")

    def test_wrong_shared_reference_does_not_override_owner_example(self):
        expected = Table([Column("net", "int")], [[80]])  # Owner's 100 gross - 20 refund.
        wrong_candidate = observed("SELECT 100 AS net")
        wrong_legacy_reference = observed("SELECT 100 AS net")
        self.assertEqual(wrong_candidate, wrong_legacy_reference)
        self.assertEqual(compare_tables(expected, wrong_candidate).status, "FAIL")

    def test_money_cannot_be_silently_rounded_through_binary_float(self):
        expected = Table([Column("amount", "decimal")], [[Decimal("0.10")]])
        actual = observed("SELECT CAST(0.10 AS REAL) AS amount")
        self.assertEqual(compare_tables(expected, actual, numeric_equivalence=True).status, "FAIL")

    def test_window_boundary_expected_by_owner_is_not_old_behavior(self):
        expected = Table([Column("id", "int")], [[1], [2]])
        actual = observed("WITH events(id,age_days) AS (VALUES(1,29),(2,30),(3,90)) SELECT id FROM events WHERE age_days<30")
        self.assertEqual(compare_tables(expected, actual).status, "FAIL")
