"""Storage integrity checks independent of a live cloud account."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from services import audit_volume as audit
from services.audit_pg import AuditUnavailable

class VolumeAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / ".dmrp-audit-volume-v1.json").write_text(json.dumps({
            "project_id":"20853297-65b7-42a8-af40-25c8d2df4e11",
            "dataset":"development","format":1}))
        self.env = patch.dict(os.environ, {"DMRP_AUDIT_DIRECTORY":str(self.root), "DMRP_AUDIT_REQUIRE_MOUNT":"0"})
        self.env.start()
    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()
    def test_read_from_fresh_reader_and_integrity(self):
        run_id = "demo-" + uuid4().hex
        decision = {"outcome":"ACCEPT", "explanation":"Проверено"}
        result = audit.audit_record(run_id, "dev-1", decision)
        self.assertTrue(result["persisted"])
        self.assertEqual(audit.audit_read(run_id)["decision"], decision)
        file = self.root / (run_id + ".json")
        data = json.loads(file.read_text())
        data["decision"]["outcome"] = "REJECT"
        file.write_text(json.dumps(data))
        with self.assertRaises(AuditUnavailable): audit.audit_read(run_id)
    def test_same_id_never_overwrites_different_decision(self):
        run_id = "demo-" + uuid4().hex
        audit.audit_record(run_id, "dev-1", {"outcome":"ACCEPT"})
        audit.audit_record(run_id, "dev-1", {"outcome":"ACCEPT"})
        with self.assertRaises(AuditUnavailable):
            audit.audit_record(run_id, "dev-1", {"outcome":"REJECT"})
        self.assertEqual(audit.audit_read(run_id)["decision"]["outcome"], "ACCEPT")
    def test_no_unmounted_or_unidentified_fallback(self):
        with patch.dict(os.environ, {"DMRP_AUDIT_REQUIRE_MOUNT":"1"}):
            self.assertFalse(audit.audit_ready())
            with self.assertRaises(AuditUnavailable):
                audit.audit_record("demo-"+uuid4().hex, "dev-1", {})
        (self.root / ".dmrp-audit-volume-v1.json").unlink()
        self.assertFalse(audit.audit_ready())
    def test_write_failure_and_invalid_path_fail_closed(self):
        with patch.object(Path, "open", side_effect=PermissionError):
            with self.assertRaises(AuditUnavailable):
                audit.audit_record("demo-"+uuid4().hex,"dev-1",{})
        with self.assertRaises(AuditUnavailable): audit.audit_record("../escape","dev-1",{})
    def test_concurrent_independent_records(self):
        ids = ["demo-"+uuid4().hex for _ in range(12)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda rid: audit.audit_record(rid,"dev-1",{"id":rid}), ids))
        self.assertTrue(all(r["persisted"] for r in results))
        self.assertEqual(len(list(self.root.glob("demo-*.json"))), len(ids))

if __name__ == "__main__":
    unittest.main()
