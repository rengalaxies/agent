"""Operator CLI reads passwords interactively and does not contact providers."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agent_service.ui_admin import main
from agent_service.ui_auth import AuthStore, UIError
from agent_service.ui_scope import scope_for_config
from agent_service.config import ServiceConfig


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        policy=self.root/'policy.json';policy.write_text(json.dumps(dict(installation_id='acme',environment='prod',subject='test',capabilities=['read_context'],repositories=[dict(id='orders',service='orders',root=str(self.root/'code'),revision='main')],addresses=[])))
        self.config=self.root/'service.json';self.config.write_text(json.dumps(dict(installation_id='acme',environment='prod',state_path=str(self.root/'service.sqlite'),core={'policy_path':str(policy),'state_dir':str(self.root/'core')})))
        self.ui=self.root/'ui.json';self.ui.write_text(json.dumps(dict(database=str(self.root/'private/auth.sqlite'),origin='https://impact.test')));self.ui.chmod(0o600)
        self.args=['--config',str(self.config),'--ui-config',str(self.ui),'--username','owner']

    def run_cli(self,action,extra=(),passwords=()):
        output=io.StringIO()
        with patch('getpass.getpass',side_effect=passwords),contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):
            rc=main([*self.args,action,*extra])
        return rc,output.getvalue()

    def test_create_change_role_and_revoke_without_password_in_output(self):
        password='author-command-line-password'
        rc,text=self.run_cli('create-user',['--role','reviewer'],[password,password])
        self.assertEqual(rc,0);self.assertNotIn(password,text)
        auth=AuthStore(self.root/'private/auth.sqlite');scope=scope_for_config(ServiceConfig.load(self.config))
        token,_=auth.login('owner',password,scope.identity,'test')
        self.assertEqual(self.run_cli('set-role',['--role','operator'])[0],0)
        with self.assertRaises(UIError):auth.session(token,scope.identity)
        self.assertEqual(self.run_cli('disable-user')[0],0)
        with self.assertRaises(UIError):auth.login('owner',password,scope.identity,'test')

    def test_mismatch_and_secrets_inside_analyzed_root_are_rejected(self):
        self.assertEqual(self.run_cli('create-user',['--role','operator'],['author-password-one','author-password-two'])[0],1)
        data=json.loads(self.ui.read_text());data['database']=str(self.root/'code/auth.sqlite');self.ui.write_text(json.dumps(data))
        rc,text=self.run_cli('create-user',['--role','operator'],['author-password-one']*2)
        self.assertEqual(rc,1);self.assertNotIn(str(self.root),text)
