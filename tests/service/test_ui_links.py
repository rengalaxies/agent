"""Tracker links come from operator configuration, never analysis text."""
import json
import unittest
from pathlib import Path
from urllib.parse import parse_qs,urlsplit

from agent_service.connectors.base import marker_line,parse_marker
from agent_service.connectors.jira import to_adf
from agent_service.connectors.kaiten import render_comment
from agent_service.ui_auth import UISettings


class TrackerLinks(unittest.TestCase):
    def doc(self):return dict(title='Result',status_line='CURRENT',sections=[dict(title='Evidence',items=['https://evil.invalid'])])

    def test_summary_adf_preserves_only_explicit_trusted_result_link(self):
        doc=self.doc();doc['jira_summary']=self.doc()
        doc['ui_result_url']='https://82.202.141.50/ui/result?resource_id=bitbucket%3Arepo%235'
        adf=to_adf(doc,marker_line('a'*16,'b'*64,1))
        links=[n for b in adf['content'] for n in b.get('content',[]) if n.get('type')=='text' and any(m.get('type')=='link' for m in n.get('marks',[]))]
        self.assertEqual(len(links),1)
        self.assertEqual(links[0]['marks'][0]['attrs']['href'],doc['ui_result_url'])
        self.assertIn('вход',links[0]['text'].lower())

    def test_kaiten_link_survives_truncation_and_single_marker_budget(self):
        doc=self.doc();doc['sections'][0]['items']=['x'*20000]
        doc['ui_result_url']='https://82.202.141.50/ui/result?resource_id=bitbucket%3Arepo%235'
        marker=marker_line('a'*16,'b'*64,1);text=render_comment(doc,marker)
        self.assertIn(doc['ui_result_url'],text);self.assertIn('вход',text.lower())
        self.assertLessEqual(len(text),4096);self.assertEqual(parse_marker(text),('a'*16,'b'*64,1))
        self.assertEqual(text.count('agent-service marker='),1)

    def test_unsafe_link_fields_are_never_rendered_as_a_link(self):
        for value in ('javascript:alert(1)','http://82.202.141.50/ui/result?resource_id=x',
                      'https://user:pw@example.test/ui/result?resource_id=x',
                      'https://example.test/evil?resource_id=x',
                      'https://example.test/ui/result?resource_id=x&token=SECRET',
                      'https://example.test/ui/result?resource_id=x\nInjected'):
            with self.subTest(value=value):
                doc=self.doc();doc['ui_result_url']=value
                self.assertNotIn('"type": "link"',json.dumps(to_adf(doc,'marker')))
                self.assertNotIn(value,render_comment(doc,marker_line('a'*16,'b'*64,1)))

    def test_configured_url_encodes_id_and_never_uses_loopback_exception(self):
        from agent_service.ui_links import result_url
        settings=UISettings(Path('/private/auth.sqlite'),'https://82.202.141.50')
        rid='bitbucket:repo#5 &/?<script>'
        url=result_url(settings,rid)
        self.assertEqual(parse_qs(urlsplit(url).query),{'resource_id':[rid]})
        self.assertEqual(urlsplit(url).fragment,'')
        self.assertIsNone(result_url(UISettings(Path('/private/auth.sqlite'),'http://127.0.0.1:18090',True),rid))

from tests.service.helpers import ServiceCase,HEAD1


class ServiceLinks(ServiceCase):
    def test_service_stamps_configured_link_into_durable_publication(self):
        self.service.ui_settings=UISettings(Path(self.tmp.name)/'auth.sqlite','https://82.202.141.50')
        self.deliver_github(self.pr_payload(HEAD1));self.drain()
        intents=self.service.store.intents('github:acme/orders#7')
        result=[i for i in intents if i['kind']=='result'][-1]
        doc=json.loads(result['body'])
        self.assertEqual(doc.get('ui_result_url'),'https://82.202.141.50/ui/result?resource_id=github%3Aacme%2Forders%237')

    def test_no_link_without_ui_or_for_local_qa_origin(self):
        self.service.ui_settings=UISettings(Path(self.tmp.name)/'auth.sqlite','http://127.0.0.1:18090',True)
        self.deliver_github(self.pr_payload(HEAD1));self.drain()
        docs=[json.loads(i['body']) for i in self.service.store.intents('github:acme/orders#7')]
        self.assertTrue(docs);self.assertTrue(all('ui_result_url' not in doc for doc in docs))

    def test_cli_reconcile_uses_same_configured_publication_link(self):
        import contextlib,io
        from types import SimpleNamespace
        from unittest.mock import patch
        from agent_graph.contracts import Policy
        from agent_service.__main__ import main
        root=Path(self.tmp.name);ui=root/'ui.json'
        ui.write_text(json.dumps(dict(database=str(root/'auth.sqlite'),origin='https://82.202.141.50')));ui.chmod(0o600)
        self.service.analyzer.policy=Policy.model_validate(dict(installation_id='inst-1',environment='test',subject='qa',
            capabilities=['read_context'],repositories=[dict(id='orders',service='orders',root=str(root/'code'),revision='main')],addresses=[]))
        self.service.analyzer.runtime_sources=[]
        config=SimpleNamespace(ui_config_path=ui)
        with patch('agent_service.__main__._service',return_value=(self.service,config)),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['reconcile','--config',str(root/'service.json')]),0)
        docs=[json.loads(i['body']) for i in self.service.store.intents('github:acme/orders#7') if i['kind']=='result']
        self.assertTrue(docs);self.assertIn('ui_result_url',docs[-1])
