"""Fixed per-installation UI routes keep independent browser grants."""
from dataclasses import replace
from pathlib import Path
import unittest
from urllib.parse import urlencode
from fastapi.testclient import TestClient
from agent_service.api import create_app
from agent_service.ui_auth import UISettings
from agent_service.ui_links import result_url, validated_url
from tests.service import test_ui_api as fixtures
PASSWORD=fixtures.PASSWORD


class AreaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.UITests.setUpClass(); cls.encoded=fixtures.UITests.encoded

    def setUp(self):
        fixtures.UITests.setUp(self)
        self.legacy = self.client
        self.settings = replace(self.settings, path_prefix='/ui/areas/jira', areas=(
            {'label': 'Kaiten', 'path_prefix': '/ui'},
            {'label': 'Jira', 'path_prefix': '/ui/areas/jira'}))
        self.client = TestClient(create_app(self.service, ui_settings=self.settings, ui_auth=self.auth), base_url=self.settings.origin)
        self.addCleanup(self.client.close)

    def test_prefixed_routes_assets_navigation_and_login_return(self):
        prefix=self.settings.path_prefix
        target=prefix+'/result?resource_id=same-rid'
        r=self.client.get(target, follow_redirects=False, headers={'Sec-Fetch-Site':'cross-site','Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document','Sec-Fetch-User':'?1'})
        self.assertEqual(r.status_code,303)
        self.assertEqual(r.headers['location'],prefix+'/login?'+urlencode({'next':target}))
        html=self.client.get(r.headers['location']).text
        self.assertIn(prefix+'/assets/login.js',html)
        self.assertIn('Области',html);self.assertIn('href="/ui"',html)
        js=self.client.get(prefix+'/assets/login.js').text
        self.assertIn(prefix+'/api/login',js);self.assertNotIn("fetch('/ui/api/",js)
        self.assertIn(prefix+'/result',js)
        workbench=self.client.get(prefix+'/assets/workbench.js').text
        self.assertIn("location.pathname.split('/').pop()",workbench)
        self.assertIn(prefix+'/api/logout',workbench)
        channel=self.client.get(prefix+'/assets/auth-events.js').text
        self.assertIn('impactmap-signout_jira',channel)
        for path in ['/ui/login','/ui/areas/unknown/login',prefix+'/assets/private.json']:
            self.assertEqual(self.client.get(path).status_code,404)
        self.assertEqual(self.client.get(prefix+'/api/csrf',headers={'Sec-Fetch-Site':'cross-site'}).status_code,403)

    def test_encoded_http_paths_are_rejected_without_rejecting_encoded_query_ids(self):
        for path in ['/ui/areas/%6aira/api/csrf','/ui/areas/jira%2fapi/csrf',
                     '/ui/areas/jira/%61pi/csrf','/ui/areas/jira/%2e%2e/jira/api/csrf']:
            with self.subTest(path=path):
                response=self.client.get(path,follow_redirects=False)
                self.assertEqual(response.status_code,404)
                self.assertEqual(response.headers['cache-control'],'no-store')
        response=self.client.get('/ui/areas/jira/result?resource_id=repo%2Fname%235',follow_redirects=False)
        self.assertEqual(response.status_code,303)

    def test_cookie_names_isolate_sessions_and_challenges_and_logout(self):
        p=self.settings.path_prefix
        self.assertNotEqual(self.settings.cookie,replace(self.settings,path_prefix='/ui').cookie)
        self.assertNotEqual(self.settings.challenge_cookie,replace(self.settings,path_prefix='/ui').challenge_cookie)
        challenge=self.client.get(p+'/api/csrf')
        self.assertIn('Path=/',challenge.headers['set-cookie']);self.assertIn('__Host-',challenge.headers['set-cookie'])
        token=challenge.json()['csrf']
        r=self.client.post(p+'/api/login',json={'username':'reader','password':PASSWORD},headers={'Origin':self.settings.origin,'X-CSRF-Token':token})
        self.assertEqual(r.status_code,200)
        self.legacy.cookies.update(self.client.cookies)
        self.assertEqual(self.legacy.get('/ui/api/me').status_code,401)
        self.assertEqual(self.client.get(p+'/api/operations').status_code,403)
        self.service.analyzer.policy.repositories[0].include=['changed.py']
        self.assertEqual(self.client.get(p+'/api/me').status_code,403)

    def test_same_resource_id_in_independent_stores_keeps_grants_and_content(self):
        from copy import deepcopy
        from types import SimpleNamespace
        from agent_service.queue import ServiceStore
        from agent_service.ui_auth import AuthStore
        from agent_service.ui_scope import scope_for_service
        from tests.graph.test_output_contracts import request, result
        from agent_service.envelope import canonical, digest
        root=self.settings.database.parent
        self.service.analyzer.policy.repositories.append(self.service.analyzer.policy.repositories[0].model_copy(
            update={'id':'reporting','service':'reporting','root':str(root/'repos/reporting')}))
        other=SimpleNamespace(installation_id='acme',environment='prod',
            store=ServiceStore(root/'jira-service.sqlite'),analyzer=deepcopy(self.service.analyzer))
        scope=scope_for_service(other)
        jira_settings=replace(self.settings,database=root/'jira-auth.sqlite')
        jira_auth=AuthStore(jira_settings.database,clock=lambda:self.now)
        with jira_auth.transaction() as c:
            c.execute('INSERT INTO users VALUES(?,?,?,?,1,0)',('reader',self.encoded,'reviewer',scope.identity))
        jira=TestClient(create_app(other,ui_settings=jira_settings,ui_auth=jira_auth),base_url=self.settings.origin)
        self.addCleanup(jira.close)
        self.auth.change_user('reader',scope=scope_for_service(self.service).identity)
        for service,version in [(self.service,'kaiten-version'),(other,'jira-version')]:
            raw=result();raw['summary']=version
            store=service.store
            store.apply_snapshot(resource_id='same-rid',provider='bitbucket',kind='pr',version=raw['resource_version'],
                snapshot={},event_id='event',closed=False)
            job=store.claim_job('worker');req=request();req.update(scope_for_service(service).receipt())
            self.assertTrue(store.stamp_ui_scope(job,req))
            doc={};store.complete_job(job,state='ANALYZED',result=raw,reason=raw['reason_code'],
                intent={'kind':'result','result_digest':digest(raw),'body':canonical(doc),'body_digest':digest(doc),'marker':'test'})
        csrf=self.legacy.get('/ui/api/csrf').json()['csrf']
        self.assertEqual(self.legacy.post('/ui/api/login',json={'username':'reader','password':PASSWORD},
            headers={'Origin':self.settings.origin,'X-CSRF-Token':csrf}).status_code,200)
        for client,prefix,version in [(self.legacy,'/ui','kaiten-version'),(jira,self.settings.path_prefix,'jira-version')]:
            if client is jira:
                # An unrelated area's cookie cannot become a Jira session, even when renamed.
                token=self.legacy.cookies.get('__Host-impactmap_session')
                client.cookies.set(jira_settings.cookie,token)
                self.assertEqual(client.get(prefix+'/api/me').status_code,401)
                csrf=client.get(prefix+'/api/csrf').json()['csrf']
                self.assertEqual(client.post(prefix+'/api/login',json={'username':'reader','password':PASSWORD},
                    headers={'Origin':self.settings.origin,'X-CSRF-Token':csrf}).status_code,200)
            response=client.get(prefix+'/api/result?resource_id=same-rid')
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['analysis']['result']['summary'],version)
            view=client.get(prefix+'/api/view?resource_id=same-rid').json()
            self.assertIn(prefix+'/result?resource_id=same-rid',view['list_html'])
        csrf=jira.get(self.settings.path_prefix+'/api/me').json()['csrf']
        self.assertEqual(jira.post(self.settings.path_prefix+'/api/logout',headers={'Origin':self.settings.origin,'X-CSRF-Token':csrf}).status_code,200)
        self.assertEqual(self.legacy.get('/ui/api/me').status_code,200)

    def test_login_frontend_keeps_return_inside_current_area_even_for_malformed_next(self):
        import json, shutil, subprocess
        node=shutil.which('node')
        if not node: self.skipTest('node unavailable')
        prefix=self.settings.path_prefix
        script=self.client.get(prefix+'/assets/login.js').text
        cases=[(prefix+'/result?resource_id=same-rid',prefix+'/result?resource_id=same-rid'),
               ('https://evil.test/ui/result',prefix+'/changes'),
               ('/ui/result?resource_id=foreign',prefix+'/changes'),
               ('/ui/areas/unknown/result',prefix+'/changes'),
               ('http://[',prefix+'/changes')]
        harness="""
const vm=require('node:vm');let input='';process.stdin.on('data',s=>input+=s);
process.stdin.on('end',async()=>{
 const data=JSON.parse(input),targets=[];
 for(const [next] of data.cases){
  let handler,target=null;
  const form={elements:{username:{value:'reader'},password:{value:'password'}},addEventListener:(_,fn)=>handler=fn};
  const elements={login:form,message:{},submit:{}};
  const context={document:{getElementById:id=>elements[id]},URL,URLSearchParams,
   location:{origin:data.origin,search:'?'+new URLSearchParams({next}),replace:v=>target=v},
   fetch:async()=>({ok:true,json:async()=>({csrf:'token'})})};
  vm.runInNewContext(data.script,context);await handler({preventDefault(){}});targets.push(target);
 }
 process.stdout.write(JSON.stringify(targets));
});
"""
        completed=subprocess.run([node,'-e',harness],input=json.dumps({'script':script,'origin':self.settings.origin,'cases':cases}),
            capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(completed.stdout),[expected for _,expected in cases])

    def test_publication_url_retains_prefix(self):
        url=result_url(self.settings,'same-rid')
        self.assertEqual(url,'https://impact.test/ui/areas/jira/result?resource_id=same-rid')
        self.assertEqual(validated_url(url),url)
        for path in ['/ui/areas/jira/../result','/ui/areas/%6aira/result','/ui/areas/jira/result/extra']:
            self.assertIsNone(validated_url('https://impact.test'+path+'?resource_id=one'))


class PrefixValidationTests(unittest.TestCase):
    def test_rejects_noncanonical_prefixes_and_untrusted_registry(self):
        for prefix in ['/ui/','/ui/areas','/ui/areas/Jira','/ui/areas/jira/..','/ui/areas/%6aira','//evil.test','https://evil.test','/ui/areas/jira?x','/ui/areas/a/b']:
            with self.subTest(prefix=prefix),self.assertRaises(ValueError):
                UISettings(Path('/tmp/auth.sqlite'),'https://impact.test',path_prefix=prefix)
        for areas in [[{'label':'x','path_prefix':'https://evil.test'}], [{'label':'x','path_prefix':'/ui'},{'label':'y','path_prefix':'/ui'}]]:
            with self.assertRaises(ValueError):UISettings(Path('/tmp/auth.sqlite'),'https://impact.test',areas=areas)

class BootstrapAreaTests(unittest.TestCase):
    def test_bootstrap_and_box_support_scoped_registry(self):
        import tempfile
        from agent_service.ui_auth import configure_private_ui
        from tools.agent_service.box.config import UI
        registry=[{'label':'Kaiten','path_prefix':'/ui'},{'label':'Jira','path_prefix':'/ui/areas/jira'}]
        cfg=UI(origin='https://impact.test',path_prefix='/ui/areas/jira',areas=registry)
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)
            self.assertTrue(configure_private_ui(state,cfg.origin,path_prefix=cfg.path_prefix,areas=[a.model_dump() for a in cfg.areas])['ok'])
            loaded=UISettings.load(state/'ui/ui.json')
            self.assertEqual(loaded.path_prefix,cfg.path_prefix)
            self.assertEqual(loaded.areas[1].label,'Jira')
            self.assertFalse(configure_private_ui(state,cfg.origin,path_prefix=cfg.path_prefix,areas=[a.model_dump() for a in cfg.areas])['changed'])
