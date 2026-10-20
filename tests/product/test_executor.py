"""Exercise the real isolated SQLite worker, including hostile SQL."""
import os
import unittest
from unittest.mock import patch

from change_completion.executor import execute_select
from change_completion.verification import TableRecord


FIXTURE = {"schemas": {"events": {"amount": "INTEGER", "age_days": "INTEGER"}},
           "tables": {"events": [{"amount": 100, "age_days": 10},
                                  {"amount": 250, "age_days": 70}]}}


class ExecutorTests(unittest.TestCase):
    def test_actual_types_are_captured_not_expected(self):
        result = execute_select("SELECT sum(amount) AS total FROM events", FIXTURE)
        self.assertEqual(result["status"], "executed")
        self.assertEqual(result["actual"]["rows"], [[350]])
        self.assertEqual(result["actual"]["columns"][0]["kind"], "int")
        TableRecord.model_validate(result["actual"])
        cast = execute_select("SELECT CAST(amount AS REAL) AS amount FROM events", FIXTURE)
        self.assertEqual(cast["actual"]["columns"][0]["kind"], "float")

    def test_read_only_and_no_external_functions(self):
        hostile = ["DELETE FROM events", "DROP TABLE events", "UPDATE events SET amount=0",
                   "ATTACH DATABASE '/tmp/must-not-open' AS other", "PRAGMA database_list",
                   "SELECT readfile('/etc/passwd')", "SELECT load_extension('/tmp/a')",
                   "SELECT writefile('/tmp/a','x')", "SELECT system('id')",
                   "SELECT name FROM sqlite_master"]
        for sql in hostile:
            with self.subTest(sql=sql):
                result = execute_select(sql, FIXTURE)
                self.assertEqual(result["status"], "unsupported")
                self.assertIsNone(result["actual"])

    def test_multiple_statements_and_invalid_sql(self):
        for sql in ["SELECT 1; DELETE FROM events", "SEL nonsense"]:
            self.assertEqual(execute_select(sql, FIXTURE)["status"], "error")

    def test_unknown_and_heterogeneous_types_fail_closed(self):
        for sql in ["SELECT amount FROM events WHERE 0", "SELECT NULL AS a",
                    "SELECT CASE WHEN age_days<30 THEN 1 ELSE 'x' END AS a FROM events",
                    "SELECT 1e999 AS a", "SELECT x'4142' AS a", "SELECT 1 AS a, 2 AS a"]:
            with self.subTest(sql=sql):
                self.assertEqual(execute_select(sql, FIXTURE)["status"], "unsupported")

    def test_duplicates_and_null_values_retained(self):
        result = execute_select("SELECT amount AS value FROM events UNION ALL SELECT NULL", FIXTURE)
        self.assertEqual(result["status"], "executed")
        self.assertEqual(result["actual"]["rows"], [[100], [250], [None]])
        self.assertTrue(result["actual"]["columns"][0]["nullable"])

    def test_fixture_validation(self):
        fixtures = [
            {"schemas": {"a;DROP TABLE events": {"x": "INTEGER"}}, "tables": {}},
            {"schemas": {"e": {"x": "INTEGER); DROP TABLE e;--"}}, "tables": {"e": []}},
            {"schemas": {"e": {"x": "INTEGER"}}, "tables": {"e": [{"x": True}]}},
            {"schemas": {"e": {"x": "INTEGER"}}, "tables": {"e": [{"x": 2**80}]}},
        ]
        for fixture in fixtures:
            self.assertEqual(execute_select("SELECT 1", fixture)["status"], "unsupported")

    def test_result_and_instruction_budgets(self):
        fixture = {"schemas": {"events": {"amount": "INTEGER"}},
                   "tables": {"events": [{"amount": x} for x in range(201)]}}
        self.assertIn("result_row_limit", execute_select("SELECT amount FROM events", fixture)["reason_codes"])
        expensive = "SELECT sum(a.amount*b.amount*c.amount) AS total FROM events a, events b, events c"
        self.assertEqual(execute_select(expensive, fixture)["status"], "timeout")

    def test_parent_input_and_timeout_budgets(self):
        self.assertEqual(execute_select("SELECT 1", FIXTURE, timeout_seconds=0)["status"], "unsupported")
        self.assertEqual(execute_select("SELECT 1", FIXTURE, timeout_seconds=0.000001)["status"], "timeout")
        self.assertEqual(execute_select("SELECT 1", {"huge": "x"*1_000_001})["status"], "unsupported")

    def test_clean_worker_environment(self):
        # A hostile PYTHONSTARTUP/PYTHONPATH is not inherited; no site imports.
        with patch.dict(os.environ, {"PYTHONSTARTUP": "/does/not/exist", "PYTHONPATH": "/tmp/evil",
                                     "CLIENT_SECRET": "not-for-worker"}):
            self.assertEqual(execute_select("SELECT count(*) AS n FROM events", FIXTURE)["status"], "executed")
