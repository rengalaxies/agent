import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tools.agent_service.box.cli import Box


class SidecarRaceTest(unittest.TestCase):
    def test_sqlite_can_remove_sidecar_before_stat_or_chown(self):
        for phase in ("stat", "chown"):
            with self.subTest(phase=phase):
                path = Mock()
                path.name = "service.sqlite-wal"
                path.stat.return_value = SimpleNamespace(st_uid=0)
                if phase == "stat":
                    path.stat.side_effect = FileNotFoundError()
                directory = Mock()
                directory.is_dir.return_value = True
                directory.iterdir.return_value = [path]
                state = Mock()
                state.__truediv__ = Mock(return_value=directory)
                box = Box.__new__(Box)
                box.layout = SimpleNamespace(system=True, state=state)
                with patch("tools.agent_service.box.cli.is_root", return_value=True), patch(
                    "tools.agent_service.box.cli.shutil.chown",
                    side_effect=FileNotFoundError() if phase == "chown" else None,
                ):
                    box.fix_sidecars()
