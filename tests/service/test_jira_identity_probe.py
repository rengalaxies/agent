"""Offline security boundary checks, not real Jira authentication."""
import importlib.util
import json
from pathlib import Path
import unittest

from agent_service.http import Response


class JiraIdentityProbeTest(unittest.TestCase):
    def execute(self, *, project="KAN", allowed=True, error=None, foreign=False, status=200, last=False):
        path = Path(__file__).resolve().parents[2] / "tools/agent_service/jira_identity_probe.py"
        self.assertTrue(path.exists(), "missing read-only Jira probe")
        spec = importlib.util.spec_from_file_location("jira_identity_probe", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        calls = []

        def request(method, endpoint, **kwargs):
            calls.append((method, endpoint, kwargs))
            if error:
                raise error
            if endpoint.endswith("/myself"):
                data = dict(accountId="user:123", active=True)
            elif "/project/" in endpoint:
                data = dict(key=project, id="10000")
            elif endpoint.endswith("/mypermissions"):
                data = dict(permissions={p: dict(havePermission=allowed) for p in module.PERMISSIONS})
            else:
                data = dict(issues=[dict(id="10001", key="OTHER-1" if foreign else "KAN-1")], isLast=last)
            return Response(status, {}, json.dumps(data).encode())

        result = module.probe(request)
        self.assertTrue(all(method == "GET" for method, _, _ in calls))
        return result, calls

    def test_success_is_only_a_read_probe_and_reports_incomplete_listing(self):
        report, calls = self.execute()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(len(calls), 4)
        self.assertFalse(report["checks"][-1]["complete_listing"])
        self.assertNotIn("summary", json.dumps(report))

    def test_wrong_project_stops_before_permissions_or_search(self):
        report, calls = self.execute(project="OTHER")
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(len(calls), 2)

    def test_missing_permissions_stops_before_reading_tasks(self):
        report, calls = self.execute(allowed=False)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(len(calls), 3)

    def test_exception_details_never_reach_output(self):
        report, calls = self.execute(error=RuntimeError("EMAIL TOKEN PRIVATE_SENTINEL"))
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(len(calls), 1)
        self.assertNotIn("SENTINEL", json.dumps(report))

    def test_http_failure_does_not_pass_with_success_shaped_json(self):
        report, calls = self.execute(status=403)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(len(calls), 1)

    def test_foreign_task_is_rejected(self):
        report, _ = self.execute(foreign=True)
        self.assertEqual(report["status"], "FAIL")

    def test_final_sample_page_does_not_qualify_complete_enumeration(self):
        report, _ = self.execute(last=True)
        self.assertEqual(report["status"], "PASS")
        self.assertFalse(report["checks"][-1]["complete_listing"])
