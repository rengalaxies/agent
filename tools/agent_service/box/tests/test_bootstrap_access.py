"""Staged release ancestors must remain traversable with root umask077."""
import os
from pathlib import Path
import stat
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from tools.agent_service.box import bootstrap
from tools.agent_service.box import layout


class StageAccess(unittest.TestCase):
    def test_new_and_cached_stage_repair_only_manager_owned_parents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'download'
            (source / 'app').mkdir(parents=True)
            (source / 'wheels').mkdir()
            (source / 'manifest.json').write_text('{}')
            (source / 'box').write_text('# fixture')
            releases = root / 'opt/agent-service/releases'
            (root / 'opt').mkdir(mode=0o755)
            private = root / 'private-state'
            private.mkdir(mode=0o700)
            manifest = dict(name='fixture', python='3.12', release_id='fixture', dependencies={'wheels':[]})
            release = SimpleNamespace(verify_tree=lambda path:(manifest,'a'*64), install_wheels=lambda *args:[])
            def run(command, **kwargs):
                if '-m' in command and 'venv' in command:
                    python = Path(command[-1]) / 'bin/python'
                    python.parent.mkdir(parents=True)
                    python.touch()
                return SimpleNamespace(returncode=0, stdout='ok\n')
            previous = os.umask(0o077)
            try:
                with patch.object(bootstrap.subprocess,'run',side_effect=run), \
                        patch.object(bootstrap,'_site_packages',return_value=root/'site'):
                    staged = bootstrap.stage(source,releases,release,layout)
                    for parent in (releases.parent,releases):
                        self.assertEqual(stat.S_IMODE(parent.stat().st_mode),0o755)
                        parent.chmod(0o700)  # an existing installation produced by the earlier bootstrap
                    self.assertEqual(bootstrap.stage(source,releases,release,layout),staged)
                    for parent in (releases.parent,releases):
                        self.assertEqual(stat.S_IMODE(parent.stat().st_mode),0o755)
                    self.assertEqual(stat.S_IMODE(private.stat().st_mode),0o700)
                    self.assertEqual(stat.S_IMODE(root.stat().st_mode),0o700)
            finally:
                os.umask(previous)
