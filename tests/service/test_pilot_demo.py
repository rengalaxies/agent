"""The local pilot show runs end to end on the real service and keeps its promises."""

from pathlib import Path
import tempfile
import unittest

from examples.pilot_orders_reporting.demo import run


class PilotDemoTest(unittest.TestCase):
    def test_change_fix_control_and_restart_keep_one_truthful_comment_each(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = run(Path(tmp) / "demo")
            self.assertTrue((Path(tmp) / "demo" / "site" / "index.html").is_file())
        self.assertEqual([c for c in report["checks"] if not c["ok"]], [])
        self.assertEqual((report["level"], report["model"]), ("LOCAL", "OFF"))


if __name__ == "__main__":
    unittest.main()
