import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from change_completion.git_bundle import export_review_bundle


@unittest.skipUnless(shutil.which('git'), 'git unavailable')
class GitBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.before, self.after = self.root/'before', self.root/'after'
        self.before.mkdir(); self.after.mkdir()
        (self.before/'consumer.py').write_text('amount = 1\n')
        (self.after/'consumer.py').write_text('amount = 100\n')

    def test_bundle_is_cloneable_and_patch_matches(self):
        output = self.root/'review'
        result = export_review_bundle(self.before, self.after, ['consumer.py'], output)
        self.assertFalse(result['remote_contacted'])
        patch_text=(output/'candidate.patch').read_text()
        self.assertIn('-amount = 1', patch_text)
        self.assertIn('+amount = 100', patch_text)
        clone=self.root/'clone'
        subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', 'clone', '--quiet', str(output/'candidate.bundle'), str(clone)], check=True, capture_output=True)
        self.assertEqual((clone/'consumer.py').read_text(), 'amount = 100\n')
        self.assertEqual((self.before/'consumer.py').read_text(), 'amount = 1\n')
        self.assertFalse((self.before/'.git').exists())

    def test_hostile_inherited_git_config_cannot_execute_hook(self):
        marker=self.root/'hook-ran'
        hooks=self.root/'hooks'; hooks.mkdir()
        hook=hooks/'pre-commit'
        hook.write_text(f'#!/bin/sh\ntouch {marker}\n'); hook.chmod(0o700)
        env={'GIT_CONFIG_COUNT':'1','GIT_CONFIG_KEY_0':'core.hooksPath','GIT_CONFIG_VALUE_0':str(hooks)}
        with patch.dict(os.environ, env):
            export_review_bundle(self.before, self.after, ['consumer.py'], self.root/'review')
        self.assertFalse(marker.exists())

    def test_unsafe_paths_symlinks_existing_output_rejected(self):
        for name in ('../consumer.py', '.git/config', '/etc/passwd', '--output=bad'):
            with self.assertRaises((ValueError, OSError)):
                export_review_bundle(self.before,self.after,[name],self.root/'review')
        (self.after/'consumer.py').unlink()
        (self.after/'consumer.py').symlink_to(self.before/'consumer.py')
        with self.assertRaises((ValueError, OSError)):
            export_review_bundle(self.before,self.after,['consumer.py'],self.root/'review')


    def test_output_under_source_or_symlink_parent_rejected(self):
        link = self.root / 'linked'
        link.symlink_to(self.root, target_is_directory=True)
        for output in (self.before / 'nested', link / 'review'):
            with self.assertRaises(ValueError):
                export_review_bundle(self.before, self.after, ['consumer.py'], output)

if __name__=='__main__':
    unittest.main()
