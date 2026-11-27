"""A deployed UI is opt-in; restoring old state cannot restore old access."""
from contextlib import closing
import json
import shutil
import sys
from pathlib import Path
import sqlite3
import tempfile
import unittest

from pydantic import ValidationError
from agent_service.config import ServiceConfig
from agent_service.ui_auth import AuthStore, UIError
from tools.agent_service.box import config, state
from tools.agent_service.box.layout import Layout
from tools.agent_service.box.tests.test_config import minimal
from tools.agent_service.box.tests.test_state import make_state


class Configuration(unittest.TestCase):
    def test_box_generates_explicit_private_ui_path_only_when_enabled(self):
        kw=dict(state=Path('/var/lib/agent-service'),policy_path=Path('/etc/p.json'),
                constitution=Path('/c.yaml'),release_id='qa')
        cfg=config.BoxConfig.model_validate(minimal(ui={'origin':'https://82.202.141.50'}))
        data=cfg.service(**kw)
        self.assertEqual(data.get('ui_config_path'),'/var/lib/agent-service/ui/ui.json')
        self.assertEqual(ServiceConfig.model_validate(data).ui_config_path,Path(data['ui_config_path']))
        self.assertNotIn('ui_config_path',config.BoxConfig.model_validate(minimal()).service(**kw))

    def test_prefix_and_area_registry_change_activation_identity(self):
        import hashlib
        kw=dict(state=Path('/var/lib/agent-service'),policy_path=Path('/etc/p.json'),
                constitution=Path('/c.yaml'),release_id='qa')
        origin='https://impact.test'
        def fingerprint(**options):
            return config.BoxConfig.model_validate(minimal(ui={'origin':origin,**options})).service(**kw)['ui_origin_fingerprint']
        legacy=fingerprint()
        self.assertEqual(legacy,hashlib.sha256(origin.encode()).hexdigest())
        scoped=fingerprint(path_prefix='/ui/areas/jira')
        self.assertNotEqual(legacy,scoped)
        self.assertNotEqual(scoped,fingerprint(path_prefix='/ui/areas/jira',areas=[{'label':'Jira','path_prefix':'/ui/areas/jira'}]))

    def test_configure_bootstraps_private_auth_without_default_users_and_is_repeatable(self):
        from tools.agent_service.box.cli import Box
        from agent_service.ui_auth import UISettings
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);layout=Layout.at(root/'prefix')
            box=Box.__new__(Box);box.layout=layout;box.release=root/'release'
            box.manifest={'name':'qa','release_id':'qa','contracts':{'constitution':{'path':'c.yaml'}}}
            box.bindings=layout.bindings('qa')
            task=box.release/'app/tools/agent_service/box/tasks.py'
            task.parent.mkdir(parents=True)
            project=Path(__file__).resolve().parents[4]
            shutil.copyfile(project/'tools/agent_service/box/tasks.py',task)
            (box.release/'app/src').symlink_to(project/'src',target_is_directory=True)
            (box.release/'venv').symlink_to(Path(sys.prefix),target_is_directory=True)
            source=root/'box.json';source.write_text(json.dumps(minimal(ui={'origin':'https://82.202.141.50'})))
            cfg=config.load(source)
            box.configure(cfg,source)
            settings=UISettings.load(layout.state/'ui/ui.json')
            auth=AuthStore(settings.database,create=False)
            with auth.transaction() as c:self.assertEqual(c.execute('SELECT count(*) FROM users').fetchone()[0],0)
            auth.create_user('reader','configured-password','reviewer','b'*64)
            box.configure(cfg,source)
            self.assertEqual(UISettings.load(layout.state/'ui/ui.json'),settings)
            first=box.config_digest('qa')
            changed=config.BoxConfig.model_validate(minimal(ui={'origin':'https://new.example.test'}))
            box.configure(changed,source)
            self.assertNotEqual(first,box.config_digest('qa'))
            self.assertEqual(auth.login('reader','configured-password','b'*64,'qa')[1].role,'reviewer')

    def test_service_controlled_ui_symlink_is_rejected_without_changing_victim(self):
        from tools.agent_service.box.cli import Box,Failed
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);layout=Layout.at(root/'prefix')
            box=Box.__new__(Box);box.layout=layout;box.release=root/'release'
            box.manifest={'name':'qa','release_id':'qa','contracts':{'constitution':{'path':'c.yaml'}}}
            box.bindings=layout.bindings('qa')
            task=box.release/'app/tools/agent_service/box/tasks.py';task.parent.mkdir(parents=True)
            project=Path(__file__).resolve().parents[4]
            shutil.copyfile(project/'tools/agent_service/box/tasks.py',task)
            (box.release/'app/src').symlink_to(project/'src',target_is_directory=True)
            (box.release/'venv').symlink_to(Path(sys.prefix),target_is_directory=True)
            victim=root/'victim';victim.mkdir();(victim/'ui.json').write_text('DO_NOT_REPLACE')
            layout.state.mkdir(parents=True);(layout.state/'ui').symlink_to(victim,target_is_directory=True)
            source=root/'box.json';source.write_text(json.dumps(minimal(ui={'origin':'https://impact.test'})))
            with self.assertRaises(Failed):box.configure(config.load(source),source)
            self.assertEqual((victim/'ui.json').read_text(),'DO_NOT_REPLACE')
            self.assertFalse((victim/'auth.sqlite').exists())

    def test_box_refuses_http_origin_and_public_backend(self):
        for override in ({'ui':{'origin':'http://82.202.141.50'}},
                         {'ui':{'origin':'https://82.202.141.50'},'listen':{'host':'0.0.0.0'}}):
            with self.subTest(override=override),self.assertRaises(ValidationError):
                config.BoxConfig.model_validate(minimal(**override))


class RestoredAccess(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.layout=Layout.at(self.tmp.name);make_state(self.layout.state)
        self.path=self.layout.state/'ui/auth.sqlite'
        self.auth=AuthStore(self.path)
        self.auth.create_user('owner','a-long-qa-password','operator','a'*64)

    def test_auth_database_is_verified_in_backup_and_restore_disables_old_access(self):
        token,_=self.auth.login('owner','a-long-qa-password','a'*64,'qa')
        cookie,csrf=self.auth.challenge()
        meta=state.create(self.layout,label='manual',release=None)
        self.assertIn('state/ui/auth.sqlite',meta['files'])
        self.auth.change_user('owner',disabled=True)
        state.restore(self.layout,meta['name'])
        auth=AuthStore(self.path,create=False)
        with self.assertRaises(UIError):auth.session(token,'a'*64)
        with self.assertRaises(UIError):auth.consume_challenge(cookie,csrf)
        with self.assertRaises(UIError):auth.login('owner','a-long-qa-password','a'*64,'qa')
        with auth.transaction() as c:
            self.assertEqual(c.execute('SELECT disabled FROM users').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM sessions').fetchone()[0],0)
        auth.change_user('owner',password='a-new-long-password',disabled=False)
        self.assertIsNotNone(auth.login('owner','a-new-long-password','a'*64,'qa')[0])

    def test_restore_fault_keeps_current_revocation_and_complete_databases(self):
        meta=state.create(self.layout,label='manual',release=None)
        self.auth.change_user('owner',disabled=True)
        def fail(point):
            if point=='file:ui/auth.sqlite':raise RuntimeError('simulated_crash')
        with self.assertRaises(RuntimeError):state.restore(self.layout,meta['name'],fault=fail)
        with self.auth.transaction() as c:
            self.assertEqual(c.execute('SELECT disabled FROM users').fetchone()[0],1)
        self.assertEqual(state.counts(self.layout.state)['events'],3)
        self.assertFalse(state.restore_unfinished(self.layout.state))

    def test_legacy_backup_without_auth_cannot_keep_current_accounts(self):
        self.path.unlink()
        meta=state.create(self.layout,label='manual',release=None)
        auth=AuthStore(self.path);auth.create_user('owner','another-long-password','operator','a'*64)
        state.restore(self.layout,meta['name'])
        self.assertFalse(self.path.exists())

    def test_modified_auth_backup_is_refused_without_touching_current_access(self):
        meta=state.create(self.layout,label='manual',release=None)
        self.assertIn('state/ui/auth.sqlite',meta['files'])
        copy=self.layout.backups/meta['name']/'state/ui/auth.sqlite'
        with closing(sqlite3.connect(copy)) as c:c.execute('UPDATE users SET disabled=1');c.commit()
        with self.assertRaises(state.BackupError):state.restore(self.layout,meta['name'])
        with self.auth.transaction() as c:self.assertEqual(c.execute('SELECT disabled FROM users').fetchone()[0],0)
