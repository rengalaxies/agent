"""Real ASGI auth/CSRF/roles without external accounts or connector calls."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from fastapi.testclient import TestClient

from agent_graph.contracts import Policy
from agent_service.api import create_app
from agent_service.queue import ServiceStore
from agent_service.ui_auth import AuthStore, UISettings, hash_password
from agent_service.ui_scope import scope_for_service

PASSWORD='ui-author-test-password'


class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.encoded=hash_password(PASSWORD)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);root=Path(self.tmp.name)
        self.now=1000.0
        policy=Policy.model_validate(dict(installation_id='acme',environment='prod',subject='ui-test',
            capabilities=['read_context'],repositories=[dict(id='orders',service='orders',root=str(root/'repos/orders'),revision='main')],addresses=[]))
        self.service=SimpleNamespace(installation_id='acme',environment='prod',store=ServiceStore(root/'service.sqlite'),
            analyzer=SimpleNamespace(policy=policy,runtime_sources=[]))
        self.settings=UISettings(root/'auth.sqlite','https://impact.test')
        self.auth=AuthStore(self.settings.database,clock=lambda:self.now)
        self.scope=scope_for_service(self.service)
        with self.auth.transaction() as c:
            c.executemany('INSERT INTO users VALUES(?,?,?,?,1,0)',
                [(name,self.encoded,role,self.scope.identity) for name,role in [('reader','reviewer'),('owner','operator')]])
        self.client=TestClient(create_app(self.service,status_token='SERVER_ONLY_SECRET',ui_settings=self.settings,ui_auth=self.auth),base_url=self.settings.origin)
        self.addCleanup(self.client.close)

    def challenge(self):return self.client.get('/ui/api/csrf').json()['csrf']

    def login(self,user='reader',password=PASSWORD):
        return self.client.post('/ui/api/login',json={'username':user,'password':password},
            headers={'Origin':self.settings.origin,'X-CSRF-Token':self.challenge()})

    def test_disabled_by_default_and_old_bearer_boundary_preserved(self):
        client=TestClient(create_app(self.service,status_token='SERVER_ONLY_SECRET'));self.addCleanup(client.close)
        self.assertEqual(client.get('/ui/login').status_code,404)
        self.assertEqual(self.client.get('/resources').status_code,401)
        self.assertEqual(self.client.get('/ui/api/me',headers={'Authorization':'Bearer SERVER_ONLY_SECRET'}).status_code,401)
        self.login();self.assertEqual(self.client.get('/resources').status_code,401)

    def test_auth_precedes_validation_and_all_ui_errors_are_uncached(self):
        for path in ['/ui/api/resources?limit=bad','/ui/api/result','/ui/api/unknown']:
            r=self.client.get(path);self.assertEqual(r.status_code,401)
            self.assertEqual(r.headers['cache-control'],'no-store')
            self.assertNotIn('access-control-allow-origin',r.headers)
        self.assertEqual(self.client.get('/ui/session',follow_redirects=False).headers['location'],'/ui/login')

    def test_login_cookie_security_rotation_and_no_credentials_in_responses(self):
        first=self.login();self.assertEqual(first.status_code,200)
        cookie=first.headers['set-cookie'];self.assertIn('__Host-impactmap_session=',cookie)
        for flag in ['Secure','HttpOnly','SameSite=strict','Path=/']:self.assertIn(flag,cookie)
        old=self.client.cookies.get(self.settings.cookie);self.assertTrue(old)
        self.assertEqual(self.login().status_code,200)
        self.assertNotEqual(old,self.client.cookies.get(self.settings.cookie))
        for path in ['/ui/api/me','/ui/session','/ui/api/resources']:
            r=self.client.get(path);self.assertEqual(r.status_code,200)
            for value in [PASSWORD,self.encoded,'SERVER_ONLY_SECRET',old]:self.assertNotIn(value,r.text)
        response=self.client.get('/ui/api/me');self.assertEqual(response.json()['role'],'reviewer')

    def test_login_csrf_origin_and_host_are_strict(self):
        csrf=self.challenge();body={'username':'reader','password':PASSWORD}
        for headers in [{},{'Origin':'https://other.test','X-CSRF-Token':csrf},
                        {'Origin':self.settings.origin,'X-CSRF-Token':'wrong'},
                        {'Origin':self.settings.origin,'X-CSRF-Token':csrf,'Sec-Fetch-Site':'cross-site'}]:
            self.assertEqual(self.client.post('/ui/api/login',json=body,headers=headers).status_code,403)
        self.assertEqual(self.client.get('/ui/api/csrf',headers={'Host':'evil.test'}).status_code,421)
        self.assertEqual(self.client.post('/ui/api/login',json=body,headers={'Origin':self.settings.origin,'X-CSRF-Token':csrf}).status_code,200)
        self.assertEqual(self.client.post('/ui/api/login',json=body,headers={'Origin':self.settings.origin,'X-CSRF-Token':csrf}).status_code,403)

    def test_logout_requires_session_csrf_and_immediately_revokes(self):
        self.login();me=self.client.get('/ui/api/me').json()
        self.assertEqual(self.client.post('/ui/api/logout',headers={'Origin':self.settings.origin}).status_code,403)
        token=self.client.cookies.get(self.settings.cookie)
        r=self.client.post('/ui/api/logout',headers={'Origin':self.settings.origin,'X-CSRF-Token':me['csrf']})
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.client.get('/ui/api/me').status_code,401)
        self.client.cookies.set(self.settings.cookie,token)
        self.assertEqual(self.client.get('/ui/api/me').status_code,401)

    def test_role_gate_and_revocation_scope_changes_and_expiry(self):
        self.login()
        for path in ['/ui/api/operations','/ui/api/connections']:
            self.assertEqual(self.client.get(path).status_code,403)
        self.auth.change_user('reader',role='operator')
        self.assertEqual(self.client.get('/ui/api/me').status_code,401)
        self.login('owner');self.assertEqual(self.client.get('/ui/api/operations').status_code,200)
        self.service.analyzer.policy.repositories[0].include=['restricted.py']
        self.assertEqual(self.client.get('/ui/api/me').status_code,403)
        self.service.analyzer.policy.repositories[0].include=['*.py','*.json','*.md']
        self.login('owner');self.service.analyzer.policy.capabilities=[]
        self.assertEqual(self.client.get('/ui/api/me').status_code,403)
        self.service.analyzer.policy.capabilities=['read_context']
        self.login('owner');self.now+=1201
        self.assertEqual(self.client.get('/ui/api/me').status_code,401)

    def test_malformed_or_oversized_inputs_do_not_echo_password(self):
        for content in ['{"password":"PRIVATE_INPUT",','["PRIVATE_INPUT"]','{"username":"reader","password":123}']:
            r=self.client.post('/ui/api/login',content=content,headers={'Origin':self.settings.origin,'X-CSRF-Token':self.challenge(),'Content-Type':'application/json'})
            self.assertEqual(r.status_code,400);self.assertNotIn('PRIVATE_INPUT',r.text)
        r=self.client.post('/ui/api/login',content='x'*5000,headers={'Origin':self.settings.origin,'X-CSRF-Token':self.challenge(),'Content-Type':'application/json'})
        self.assertEqual(r.status_code,413)

    def test_bad_password_generic_401_and_throttle_429(self):
        for n in range(5):self.assertEqual(self.login(password='wrong').status_code,401)
        r=self.login();self.assertEqual(r.status_code,429);self.assertEqual(r.headers['cache-control'],'no-store')

    def test_assets_whitelisted_and_methods_read_only(self):
        for file in ['ui.css','login.js','session.js']:
            self.assertEqual(self.client.get('/ui/assets/'+file).status_code,200)
        self.assertEqual(self.client.get('/ui/assets/private.json').status_code,404)
        self.login('owner')
        for path in ['/ui/api/resources','/ui/api/result','/ui/api/connections']:
            r=self.client.post(path,headers={'Origin':self.settings.origin});self.assertEqual(r.status_code,405)
            self.assertEqual(r.headers['cache-control'],'no-store')

    def test_ui_settings_require_https_or_explicit_loopback(self):
        for origin,allow in [('http://impact.test',False),('http://impact.test',True),('http://127.0.0.1',False),('https://impact.test/',False)]:
            with self.assertRaises(ValueError):UISettings(self.settings.database,origin,allow)
        local=UISettings(self.settings.database,'http://127.0.0.1:18088',True)
        self.assertFalse(local.secure);self.assertFalse(local.cookie.startswith('__Host-'))
        for origin in (None,{},'https://impact.test\n'):
            with self.assertRaises(ValueError):UISettings(self.settings.database,origin)

    def test_effective_deadline_and_rotated_csrf_logout_do_not_lie(self):
        self.login();first=self.client.get('/ui/api/me').json()
        self.assertEqual(first['valid_until'],self.now+1200)
        self.assertEqual(first['valid_for_seconds'],1200)
        self.login();second=self.client.get('/ui/api/me').json()
        self.assertNotEqual(first['csrf'],second['csrf'])
        response=self.client.post('/ui/api/logout',headers={'Origin':self.settings.origin,'X-CSRF-Token':first['csrf']})
        self.assertEqual(response.status_code,403)
        self.assertEqual(self.client.get('/ui/api/me').status_code,200)
        self.assertEqual(self.client.post('/ui/api/logout',headers={'Origin':self.settings.origin,'X-CSRF-Token':second['csrf']}).status_code,200)
        self.assertEqual(self.client.get('/ui/api/me').status_code,401)

    def test_insecure_exception_requires_loopback_bind_and_peer(self):
        local=UISettings(self.settings.database,'http://127.0.0.1:18088',True)
        with self.assertRaises(ValueError):local.validate_bind('0.0.0.0')
        local.validate_bind('127.0.0.1')
        remote=TestClient(create_app(self.service,ui_settings=local,ui_auth=self.auth),
                          base_url=local.origin,client=('203.0.113.10',1234))
        self.addCleanup(remote.close)
        self.assertEqual(remote.get('/ui/api/csrf').status_code,403)

    def test_authenticated_http_result_uses_trusted_scope_not_operator_document(self):
        from tests.graph.test_output_contracts import request,result
        from agent_service.envelope import canonical,digest
        repo=self.service.analyzer.policy.repositories[0].model_copy(update={'id':'reporting','service':'reporting','root':str(self.settings.database.parent/'repos/reporting')})
        self.service.analyzer.policy.repositories.append(repo)
        scope=scope_for_service(self.service);self.auth.change_user('reader',scope=scope.identity)
        raw=result();rid='bitbucket:author#5';store=self.service.store
        store.apply_snapshot(resource_id=rid,provider='bitbucket',kind='pr',version=raw['resource_version'],
                             snapshot={'password':'PRIVATE_SNAPSHOT'},event_id='author',closed=False)
        job=store.claim_job('author');req=request();req.update(scope.receipt());store.stamp_ui_scope(job,req)
        doc={'secret':'PRIVATE_OPERATOR_DOCUMENT'}
        store.complete_job(job,state='ANALYZED',result=raw,reason=raw['reason_code'],intent={'kind':'result','result_digest':digest(raw),'body':canonical(doc),'body_digest':digest(doc),'marker':'author'})
        self.assertEqual(self.login().status_code,200)
        self.assertEqual(self.client.get('/ui/api/resources').json()['items'][0]['resource_id'],rid)
        response=self.client.get('/ui/api/result',params={'resource_id':rid})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['analysis']['result']['status'],'USEFUL')
        self.assertNotIn('PRIVATE_',response.text)
        self.assertEqual(self.client.get('/ui/api/result',params={'resource_id':'other-installation#5'}).status_code,404)
        view=self.client.get('/ui/api/view',params={'resource_id':rid})
        self.assertEqual(view.status_code,200)
        self.assertIn('3333333333333333333333333333333333333333',view.json()['result_html'])
        self.assertNotIn('PRIVATE_',view.text)

    def test_workbench_routes_and_view_are_authenticated_read_only_and_fail_closed(self):
        for path in ['/ui/changes','/ui/result?resource_id=foreign']:
            r=self.client.get(path,follow_redirects=False)
            self.assertEqual(r.status_code,303);self.assertTrue(r.headers['location'].startswith('/ui/login?next='))
        self.assertEqual(self.client.get('/ui/api/view').status_code,401)
        self.login()
        for path in ['/ui/changes','/ui/result?resource_id=foreign']:
            r=self.client.get(path);self.assertEqual(r.status_code,200)
            self.assertEqual(r.headers['cache-control'],'no-store')
            self.assertNotIn('PRIVATE_',r.text)
        view=self.client.get('/ui/api/view')
        self.assertEqual(view.status_code,200);self.assertIn('Нет доступных изменений',view.json()['list_html'])
        self.assertEqual(self.client.get('/ui/api/view?resource_id=foreign').status_code,404)
        self.assertEqual(self.client.get('/ui/api/view?resource_id=').status_code,400)
        self.assertEqual(self.client.post('/ui/api/view',headers={'Origin':self.settings.origin}).status_code,405)
        for name in ['workbench.css','workbench.js']:
            self.assertEqual(self.client.get('/ui/assets/'+name).status_code,200)

    def test_real_operator_panels_are_role_gated_and_do_not_return_notice_details(self):
        from agent_service.ui_operator import OperatorMetadata
        self.service.ui_metadata=OperatorMetadata('dry_run',('bitbucket',),(('orders','bitbucket'),),
            (('kaiten',('10',),'bitbucket'),),())
        self.service.store.note('connection_unauthorized','bitbucket','PRIVATE_AUTHORIZATION',ui_scope=self.scope)
        self.login()
        for path in ['/ui/api/operations','/ui/api/connections','/ui/operations','/ui/connections']:
            self.assertEqual(self.client.get(path).status_code,403)
        self.login('owner')
        for section in ['operations','connections']:
            response=self.client.get('/ui/api/'+section)
            self.assertEqual(response.status_code,200);data=response.json()
            self.assertTrue(data['available']);self.assertIn('result_html',data)
            self.assertNotIn('PRIVATE_',response.text)
            self.assertEqual(response.headers['cache-control'],'no-store')
            self.assertEqual(self.client.post('/ui/api/'+section,headers={'Origin':self.settings.origin}).status_code,405)
        html=self.client.get('/ui/api/connections').json()['result_html']
        self.assertIn('Яндекс',html);self.assertIn('NOT_CONNECTED',html)

    def test_tracker_navigation_reaches_login_and_returns_to_same_protected_result(self):
        from urllib.parse import parse_qs,urlsplit
        navigation={'Sec-Fetch-Site':'cross-site','Sec-Fetch-Mode':'navigate',
                    'Sec-Fetch-Dest':'document','Sec-Fetch-User':'?1'}
        target='/ui/result?resource_id=bitbucket%3Aauthor%235'
        response=self.client.get(target,headers=navigation,follow_redirects=False)
        self.assertEqual(response.status_code,303)
        login=response.headers['location']
        self.assertEqual(parse_qs(urlsplit(login).query)['next'],[target])
        self.assertEqual(self.client.get(login,headers=navigation).status_code,200)
        self.login()
        self.assertEqual(self.client.get(target,headers={'Sec-Fetch-Site':'same-origin'}).status_code,200)

    def test_cross_site_fetch_iframe_and_mutation_still_fail_closed(self):
        self.login()
        cross={'Sec-Fetch-Site':'cross-site','Sec-Fetch-Mode':'navigate',
               'Sec-Fetch-Dest':'document','Sec-Fetch-User':'?1'}
        for path in ('/ui/api/resources','/ui/api/csrf','/ui/api/operations'):
            self.assertEqual(self.client.get(path,headers=cross).status_code,403)
        for change in ({'Sec-Fetch-Mode':'cors'},{'Sec-Fetch-Dest':'iframe'},{'Sec-Fetch-User':'?0'}):
            self.assertEqual(self.client.get('/ui/result?resource_id=x',headers={**cross,**change}).status_code,403)
        self.assertEqual(self.client.post('/ui/api/logout',headers={**cross,'Origin':self.settings.origin}).status_code,403)
