import contextlib
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location('m3_inventory', Path(__file__).with_name('inventory.py'))
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


class InventoryPrivacy(unittest.TestCase):
    def test_nginx_auth_values_do_not_reach_report(self):
        secret = 'TEST_ONLY_AUTH_VALUE'
        config = ('location / { proxy_set_header Authorization "Bearer ' + secret + '"; }\n'
                  'proxy_pass https://user:' + secret + '@upstream/path?token=' + secret + ';\n')

        def command(*args, **kwargs):
            return {'exit': 0, 'stdout': config if args == ('nginx', '-T') else '', 'truncated': False}

        output = io.StringIO()
        with patch.object(inventory.platform, 'system', return_value='Linux'), \
             patch.object(inventory, 'run', side_effect=command), \
             patch.object(inventory, 'listing', return_value=[]), \
             patch.object(inventory.Path, 'read_text', return_value='test fixture'), \
             patch.object(inventory.shutil, 'which', return_value=None), \
             contextlib.redirect_stdout(output):
            inventory.main()
        self.assertNotIn(secret, output.getvalue())


if __name__ == '__main__':
    unittest.main()
